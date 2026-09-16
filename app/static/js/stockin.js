const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

let currentPage = 1;
let timer = null;
let sortCol = 'created_at';
let sortDir = 'desc';

const SORT_COLUMNS = {
  일시: 'created_at',
  Code: 'identifier',
  품명: 'item_name',
  사이트: 'site',
  수량: 'quantity',
  사유: 'reason',
  처리자: 'user',
};

function renderPagination(page, totalPages) {
  const box = $('#stockinPagination');
  if (!box) return;
  if (totalPages <= 1) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `
    <button type="button" class="ghost small" id="stockinPrev" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${page} / ${totalPages} 페이지</span>
    <button type="button" class="ghost small" id="stockinNext" ${page >= totalPages ? 'disabled' : ''}>다음 →</button>
  `;
  box.querySelector('#stockinPrev')?.addEventListener('click', () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    search();
  });
  box.querySelector('#stockinNext')?.addEventListener('click', () => {
    if (currentPage >= totalPages) return;
    currentPage += 1;
    search();
  });
}

async function search() {
  const meta = $('#stockinMeta');
  const table = $('#stockinTable');
  if (!meta || !table) return;

  meta.textContent = '조회 중…';

  const params = new URLSearchParams({
    page: String(currentPage),
    q: $('#stockinSearch')?.value.trim() || '',
    source: $('#stockinSource')?.value || '',
    ...window.siteParams('stockin'),
    sort: sortCol,
    dir: sortDir,
  });

  try {
    const response = await fetch('/api/stockin?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '조회에 실패했습니다.');

    const rows = data.items || [];

    table.querySelector('tbody').innerHTML = rows.length
      ? rows.map((item) => `
          <tr>
            <td>${esc(item.created_at)}</td>
            <td>${esc(item.source_label || item.source)}</td>
            <td>${esc(item.identifier || '')}${item.serials && item.serials.length ? `<span class="tag info" title="${esc(item.serials.join('\n'))}">S/N ${item.serials.length}</span>` : ''}</td>
            <td>${esc(item.item_name || '')}</td>
            <td>${item.site ? `<a class="site-link" href="/sites/${encodeURIComponent(item.site)}">${esc(item.site)}</a>` : ''}</td>
            <td>${esc(item.quantity)}ea</td>
            <td>${esc(item.reason || '')}</td>
            <td>${esc(item.user || '')}</td>
          </tr>
        `).join('')
      : '<tr><td colspan="8" class="empty">입고 이력이 없습니다.</td></tr>';

    currentPage = data.page || 1;
    renderPagination(currentPage, data.total_pages || 1);
    meta.textContent = `총 ${data.count || 0}건`;
    renderSortableHead();
  } catch (error) {
    meta.textContent = error.message;
  }
}

function renderSortableHead() {
  const thead = document.querySelector('#stockinTable thead tr');
  if (!thead) return;

  thead.querySelectorAll('th').forEach((th) => {
    const column = SORT_COLUMNS[th.textContent.replace(/[\u25b2\u25bc]/g, '').trim()];
    if (!column) return;

    const isActive = sortCol === column;
    const label = th.textContent.replace(/[\u25b2\u25bc]/g, '').trim();
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

$('#stockinSearch')?.addEventListener('input', () => {
  clearTimeout(timer);
  currentPage = 1;
  timer = setTimeout(search, 250);
});
window.bindSiteScope('stockin', () => { currentPage = 1; search(); });

$('#stockinSource')?.addEventListener('change', () => {
  currentPage = 1;
  search();
});

search();
