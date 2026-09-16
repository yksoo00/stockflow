const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

let currentPage = 1;
let timer = null;

function renderPagination(page, totalPages) {
  const box = $('#unitPagination');
  if (!box) return;
  if (totalPages <= 1) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `
    <button type="button" class="ghost small" id="unitPrev" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${page} / ${totalPages} 페이지</span>
    <button type="button" class="ghost small" id="unitNext" ${page >= totalPages ? 'disabled' : ''}>다음 →</button>
  `;
  box.querySelector('#unitPrev')?.addEventListener('click', () => { currentPage -= 1; search(); });
  box.querySelector('#unitNext')?.addEventListener('click', () => { currentPage += 1; search(); });
}

async function search() {
  const table = $('#unitTable');
  const meta = $('#unitMeta');
  if (!table) return;
  meta.textContent = '조회 중…';

  const params = new URLSearchParams({
    page: String(currentPage),
    q: $('#unitSearch')?.value.trim() || '',
    status: $('#unitStatus')?.value || '',
    site: $('#unitSite')?.value.trim() || '',
  });

  try {
    const response = await fetch('/api/units?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '조회에 실패했습니다.');

    $('#unitsInStock').textContent = `${data.summary?.in_stock ?? 0}개`;
    $('#unitsOut').textContent = `${data.summary?.out ?? 0}개`;

    const items = data.items || [];
    table.querySelector('tbody').innerHTML = items.map((u) => `
      <tr>
        <td><b>${esc(u.serial)}</b></td>
        <td>${esc(u.identifier || '')}</td>
        <td>${esc(u.item_name || '')}</td>
        <td><span class="tag ${u.status === 'in_stock' ? 'ok' : 'danger'}">${esc(u.status_label)}</span></td>
        <td>${u.site ? `<a class="site-link" href="/sites/${encodeURIComponent(u.site)}">${esc(u.site)}</a>` : ''}</td>
        <td>${esc(u.updated_at || '')}</td>
        <td><button type="button" class="ghost small history-btn" data-serial="${esc(u.serial)}">이력</button></td>
      </tr>
    `).join('') || '<tr><td colspan="7" class="empty">등록된 시리얼이 없습니다. 입고/출고 때 시리얼을 입력하면 여기에 쌓입니다.</td></tr>';

    table.querySelectorAll('.history-btn').forEach((b) => b.addEventListener('click', () => openHistory(b.dataset.serial)));

    currentPage = data.page || 1;
    renderPagination(currentPage, data.total_pages || 1);
    meta.textContent = `총 ${data.count || 0}건`;
  } catch (error) {
    meta.textContent = error.message;
  }
}

async function openHistory(serial) {
  try {
    const response = await fetch(`/api/units/${encodeURIComponent(serial)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '이력을 불러오지 못했습니다.');
    const u = data.unit;
    $('#unitModalBody').innerHTML = `
      <div class="modal-field"><span class="modal-label">시리얼</span><span class="modal-value"><b>${esc(u.serial)}</b></span></div>
      <div class="modal-field"><span class="modal-label">품목</span><span class="modal-value">${esc(u.identifier || u.item_name || '')}</span></div>
      <div class="modal-field"><span class="modal-label">현재</span><span class="modal-value"><span class="tag ${u.status === 'in_stock' ? 'ok' : 'danger'}">${esc(u.status_label)}</span> ${u.site ? '· ' + esc(u.site) : ''}</span></div>
      <table class="mini-table" style="margin-top:12px">
        <thead><tr><th>일시</th><th>구분</th><th>사이트</th><th>사유</th><th>처리자</th></tr></thead>
        <tbody>${(data.history || []).map((h) => `
          <tr class="${h.cancelled ? 'cancelled-row' : ''}">
            <td>${esc(h.at)}</td>
            <td>${h.type === 'out' ? '<span class="tag danger">출고</span>' : '<span class="tag ok">입고</span>'}${h.cancelled ? ' <span class="tag">취소됨</span>' : ''}</td>
            <td class="no-strike">${esc(h.site || '')}</td>
            <td>${esc(h.reason || '')}${h.ticket_no ? ` · 티켓 ${esc(h.ticket_no)}` : ''}${h.handler ? ` · ${esc(h.handler)}` : ''}</td>
            <td>${esc(h.user || '')}</td>
          </tr>`).join('') || '<tr><td colspan="5" class="empty">이력 없음</td></tr>'}</tbody>
      </table>
    `;
    $('#unitModal').style.display = 'flex';
  } catch (error) {
    showResultModal(error.message, 'error');
  }
}

const closeModal = () => { $('#unitModal').style.display = 'none'; };
$('#unitModalClose')?.addEventListener('click', closeModal);
$('#unitModalOk')?.addEventListener('click', closeModal);

['#unitSearch', '#unitSite'].forEach((s) => $(s)?.addEventListener('input', () => {
  clearTimeout(timer);
  currentPage = 1;
  timer = setTimeout(search, 250);
}));
$('#unitStatus')?.addEventListener('change', () => { currentPage = 1; search(); });

search();
