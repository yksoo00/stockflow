const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

let currentPage = 1;
let timer = null;
let arriveTarget = null;

const STATUS_LABEL = {
  requested: '요청됨',
  approved: '승인완료',
  arrived: '입고완료',
};

const SOURCE_LABEL = {
  auto: '자동',
  manual: '수동',
};

function fmtQty(value) {
  const num = Number(value);
  return Number.isInteger(num) ? String(num) : String(value);
}

function renderPagination(page, totalPages) {
  const box = $('#requestPagination');
  if (!box) return;
  if (totalPages <= 1) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `
    <button type="button" class="ghost small" id="reqPrevPage" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${page} / ${totalPages} 페이지</span>
    <button type="button" class="ghost small" id="reqNextPage" ${page >= totalPages ? 'disabled' : ''}>다음 →</button>
  `;
  box.querySelector('#reqPrevPage')?.addEventListener('click', () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    search();
  });
  box.querySelector('#reqNextPage')?.addEventListener('click', () => {
    if (currentPage >= totalPages) return;
    currentPage += 1;
    search();
  });
}

function actionsHtml(item) {
  if (item.status === 'requested') {
    if (window.IS_ADMIN) {
      return `<button type="button" class="primary small approve-btn" data-id="${item.id}">승인</button>`;
    }
    return '<span class="status">요청됨</span>';
  }

  if (item.status === 'approved') {
    if (window.IS_ADMIN) {
      return `<button type="button" class="primary small arrive-btn" data-id="${item.id}">물품도착</button>`;
    }
    return '<span class="status completed">승인완료</span>';
  }

  return '<span class="status completed">입고완료</span>';
}

function statusHtml(item) {
  const base = `<span class="status ${item.status === 'arrived' ? 'completed' : ''}">${esc(STATUS_LABEL[item.status] || item.status)}</span>`;
  if (item.stale) {
    return `${base}<span class="stale-tag" title="${item.waiting_days}일 대기 중">${item.waiting_days}일 지연</span>`;
  }
  if (item.status === 'requested' && item.waiting_days > 0) {
    return `${base} <small style="color:var(--muted)">${item.waiting_days}일</small>`;
  }
  return base;
}

async function search() {
  const table = $('#requestTable');
  const meta = $('#requestMeta');
  if (!table || !meta) return;

  meta.textContent = '조회 중…';

  const params = new URLSearchParams({
    page: String(currentPage),
    page_size: '10',
    q: $('#requestSearch')?.value.trim() || '',
    site: $('#requestSite')?.value.trim() || '',
    status: $('#requestStatus')?.value || '',
    date: $('#requestDate')?.value || '',
  });

  try {
    const response = await fetch(`/api/stockrequest?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '요청 목록을 불러오지 못했습니다.');

    const items = data.items || [];

    table.querySelector('tbody').innerHTML = items.map((item) => `
      <tr data-identifier="${esc(item.identifier || '')}" class="${item.stale ? 'stale-row' : ''}">
        <td>${esc(item.created_at)}</td>
        <td>${esc(SOURCE_LABEL[item.source] || item.source)}</td>
        <td>${esc(item.identifier || '')}</td>
        <td>${esc(item.item_name || '')}</td>
        <td>${item.site ? `<a class="site-link" href="/sites/${encodeURIComponent(item.site)}">${esc(item.site)}</a>` : ''}</td>
        <td>${fmtQty(item.quantity)}ea</td>
        <td>${esc(item.reason || '')}</td>
        <td>${esc(item.requested_by || '-')}</td>
        <td>${statusHtml(item)}</td>
        <td>${actionsHtml(item)}</td>
      </tr>
    `).join('') || '<tr><td class="empty" colspan="10">요청 내역이 없습니다.</td></tr>';

    currentPage = data.page || 1;
    renderPagination(currentPage, data.total_pages || 1);
    const staleCount = items.filter((i) => i.stale).length;
    meta.textContent = `총 ${data.count || 0}건` + (staleCount ? ` · 이 페이지에 ${data.stale_days}일 이상 지연 ${staleCount}건` : '');

    table.querySelectorAll('.approve-btn').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        approve(button);
      });
    });
    table.querySelectorAll('.arrive-btn').forEach((button) => {
      const item = items.find((i) => String(i.id) === button.dataset.id);
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        openArriveModal(item, button);
      });
    });

    if (window.IS_ADMIN) {
      table.querySelectorAll('tbody tr[data-identifier]:not([data-identifier=""])').forEach((tr) => {
        tr.classList.add('row-clickable');
        tr.addEventListener('click', (event) => {
          if (event.target.closest('a, button')) return;
          window.location.href = '/ebay/' + encodeURIComponent(tr.dataset.identifier);
        });
      });
    }
  } catch (error) {
    meta.textContent = error.message;
  }
}

async function approve(button) {
  const id = button.dataset.id;
  button.disabled = true;
  button.textContent = '처리 중…';

  try {
    const response = await fetch(`/api/stockrequest/${id}/approve`, {method: 'POST'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '승인에 실패했습니다.');
    await search();
    window.refreshPendingBadge?.();
    showResultModal('승인되었습니다.', 'success');
  } catch (error) {
    button.disabled = false;
    button.textContent = '승인';
    showResultModal('승인 실패하였습니다. ' + error.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// 물품도착 — 시리얼(선택)을 받아 입고 처리
// ---------------------------------------------------------------------------
function openArriveModal(item) {
  arriveTarget = item;
  $('#arriveModalBody').innerHTML = `
    <div class="modal-field"><span class="modal-label">품목</span><span class="modal-value">${esc(item.identifier || item.item_name || '')}</span></div>
    <div class="modal-field"><span class="modal-label">입고 수량</span><span class="modal-value">${fmtQty(item.quantity)}ea → ${esc(item.site || '-')}</span></div>
    <div class="modal-field">
      <span class="modal-label">시리얼번호 (선택)</span>
      <textarea class="modal-textarea" id="arriveSerials" placeholder="한 줄에 하나씩. 입력하면 개수가 수량(${fmtQty(item.quantity)})과 같아야 합니다."></textarea>
    </div>
  `;
  $('#arriveModal').style.display = 'flex';
}

function closeArriveModal() {
  $('#arriveModal').style.display = 'none';
  arriveTarget = null;
}

async function submitArrive() {
  if (!arriveTarget) return;
  const button = $('#arriveModalSubmit');
  button.disabled = true;
  button.textContent = '처리 중…';

  try {
    const response = await fetch(`/api/stockrequest/${arriveTarget.id}/arrive`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({serials: $('#arriveSerials')?.value || ''}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '물품도착 처리에 실패했습니다.');
    closeArriveModal();
    await search();
    window.refreshPendingBadge?.();
    showResultModal(`입고되었습니다. (현재 재고 ${data.row_quantity})`, 'success');
  } catch (error) {
    showResultModal('입고 실패하였습니다. ' + error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = '입고 처리';
  }
}

$('#arriveModalClose')?.addEventListener('click', closeArriveModal);
$('#arriveModalDismiss')?.addEventListener('click', closeArriveModal);
$('#arriveModalSubmit')?.addEventListener('click', submitArrive);
$('#arriveModal')?.addEventListener('click', (event) => {
  if (event.target === $('#arriveModal')) closeArriveModal();
});

['#requestSearch', '#requestSite'].forEach((selector) => $(selector)?.addEventListener('input', () => {
  clearTimeout(timer);
  currentPage = 1;
  timer = setTimeout(search, 250);
}));

['#requestStatus', '#requestDate'].forEach((selector) => $(selector)?.addEventListener('change', () => {
  currentPage = 1;
  search();
}));

search();
