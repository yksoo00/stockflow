const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

let currentPage = 1;
let timer = null;
let sortCol = 'created_at';
let sortDir = 'desc';
let cancelTarget = null;

const SORT_COLUMNS = {
  일시: 'created_at',
  Code: 'identifier',
  품명: 'item_name',
  사이트: 'site',
  수량: 'quantity',
  사유: 'reason',
  티켓: 'ticket_no',
  담당자: 'handler',
  처리자: 'user',
};

function renderPagination(page, totalPages) {
  const box = $('#stockoutPagination');
  if (!box) return;
  if (totalPages <= 1) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `
    <button type="button" class="ghost small" id="stockoutPrev" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${page} / ${totalPages} 페이지</span>
    <button type="button" class="ghost small" id="stockoutNext" ${page >= totalPages ? 'disabled' : ''}>다음 →</button>
  `;
  box.querySelector('#stockoutPrev')?.addEventListener('click', () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    search();
  });
  box.querySelector('#stockoutNext')?.addEventListener('click', () => {
    if (currentPage >= totalPages) return;
    currentPage += 1;
    search();
  });
}

function canCancel(item) {
  if (item.cancelled) return false;
  return window.IS_ADMIN || (window.USER_ID && item.user_id === window.USER_ID);
}

function rowHtml(item) {
  const cancelled = item.cancelled;
  const siteCell = item.site
    ? `<a class="site-link" href="/sites/${encodeURIComponent(item.site)}">${esc(item.site)}</a>`
    : '';
  const serialHint = item.serials && item.serials.length
    ? ` <span class="tag info" title="${esc(item.serials.join('\n'))}">S/N ${item.serials.length}</span>`
    : '';
  return `
    <tr class="${cancelled ? 'cancelled-row' : ''}">
      <td>${esc(item.created_at)}</td>
      <td>${esc(item.identifier || '')}${serialHint}</td>
      <td>${esc(item.item_name || '')}</td>
      <td class="no-strike">${siteCell}</td>
      <td>${esc(item.quantity)}ea</td>
      <td>${esc(item.reason || '')}</td>
      <td>${esc(item.ticket_no || '')}</td>
      <td>${esc(item.handler || '')}</td>
      <td>${esc(item.user || '')}</td>
      <td class="no-strike">${
        cancelled
          ? `<span class="tag danger" title="${esc(item.cancelled_by || '')} · ${esc(item.cancelled_at || '')}${item.cancel_reason ? ' · ' + esc(item.cancel_reason) : ''}">취소됨</span>`
          : (canCancel(item) ? `<button type="button" class="ghost small cancel-btn" data-id="${item.id}">취소</button>` : '')
      }</td>
    </tr>
  `;
}

async function search() {
  const meta = $('#stockoutMeta');
  const table = $('#stockoutTable');
  if (!meta || !table) return;

  meta.textContent = '조회 중…';

  const params = new URLSearchParams({
    page: String(currentPage),
    q: $('#stockoutSearch')?.value.trim() || '',
    site: $('#stockoutSite')?.value.trim() || '',
    date: $('#stockoutDate')?.value || '',
    include_cancelled: $('#stockoutShowCancelled')?.checked ? '1' : '0',
    sort: sortCol,
    dir: sortDir,
  });

  try {
    const response = await fetch('/api/stockout?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '조회에 실패했습니다.');

    const rows = data.items || [];
    table.querySelector('tbody').innerHTML = rows.length
      ? rows.map(rowHtml).join('')
      : '<tr><td colspan="10" class="empty">출고 이력이 없습니다.</td></tr>';

    table.querySelectorAll('.cancel-btn').forEach((button) => {
      const item = rows.find((r) => String(r.id) === button.dataset.id);
      button.addEventListener('click', () => openCancelModal(item));
    });

    currentPage = data.page || 1;
    renderPagination(currentPage, data.total_pages || 1);
    meta.textContent = `총 ${data.count || 0}건`;
    renderSortableHead();
  } catch (error) {
    meta.textContent = error.message;
  }
}

function renderSortableHead() {
  const thead = document.querySelector('#stockoutTable thead tr');
  if (!thead) return;

  thead.querySelectorAll('th').forEach((th) => {
    const label = th.textContent.replace(/[▲▼]/g, '').trim();
    const column = SORT_COLUMNS[label];
    if (!column) return;

    const isActive = sortCol === column;
    th.textContent = label + (isActive ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '');
    th.classList.add('sortable');
    th.classList.toggle('sorted', isActive);
    th.dataset.column = column;

    th.onclick = () => {
      if (sortCol === column) {
        sortDir = sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        sortCol = column;
        sortDir = 'asc';
      }
      currentPage = 1;
      search();
    };
  });
}

// ---------------------------------------------------------------------------
// 출고 취소
// ---------------------------------------------------------------------------
function openCancelModal(item) {
  cancelTarget = item;
  $('#cancelModalBody').innerHTML = `
    <div class="modal-field"><span class="modal-label">품목</span><span class="modal-value">${esc(item.identifier || item.item_name || '')}</span></div>
    <div class="modal-field"><span class="modal-label">출고</span><span class="modal-value">${esc(item.created_at)} · ${esc(item.site || '')} · ${esc(item.quantity)}ea</span></div>
    ${item.serials && item.serials.length ? `<div class="modal-field"><span class="modal-label">시리얼</span><span class="modal-value">${esc(item.serials.join(', '))}</span></div>` : ''}
    <div class="modal-field"><span class="modal-label">취소 사유</span><input class="modal-input" id="cancelReason" placeholder="예: 잘못 입력 / 현장 반납"></div>
    <p class="sheet-help">취소하면 재고 수량이 ${esc(item.quantity)}개 되돌아가고, 입고 내역에 '출고취소 원복'으로 남습니다. 시리얼이 있으면 다시 재고 상태가 됩니다.</p>
  `;
  $('#cancelModal').style.display = 'flex';
  $('#cancelReason')?.focus();
}

function closeCancelModal() {
  $('#cancelModal').style.display = 'none';
  cancelTarget = null;
}

async function submitCancel() {
  if (!cancelTarget) return;
  const button = $('#cancelModalSubmit');
  button.disabled = true;
  button.textContent = '처리 중…';
  try {
    const response = await fetch(`/api/stockout/${cancelTarget.id}/cancel`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({reason: $('#cancelReason')?.value.trim() || ''}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '취소에 실패했습니다.');
    closeCancelModal();
    await search();
    showResultModal(`출고가 취소되었습니다. (현재 재고 ${data.row_quantity})`, 'success');
  } catch (error) {
    showResultModal('출고 취소 실패. ' + error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = '취소하고 수량 되돌리기';
  }
}

$('#cancelModalClose')?.addEventListener('click', closeCancelModal);
$('#cancelModalDismiss')?.addEventListener('click', closeCancelModal);
$('#cancelModalSubmit')?.addEventListener('click', submitCancel);
$('#cancelModal')?.addEventListener('click', (event) => {
  if (event.target === $('#cancelModal')) closeCancelModal();
});

['#stockoutSearch', '#stockoutSite'].forEach((selector) => {
  $(selector)?.addEventListener('input', () => {
    clearTimeout(timer);
    currentPage = 1;
    timer = setTimeout(search, 250);
  });
});

$('#stockoutDate')?.addEventListener('change', () => {
  currentPage = 1;
  search();
});

$('#stockoutShowCancelled')?.addEventListener('change', () => {
  currentPage = 1;
  search();
});

search();
