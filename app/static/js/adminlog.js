const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

let currentPage = 1;
let timer = null;
let sortCol = 'created_at';
let sortDir = 'desc';
let actionsLoaded = false;

const SORT_COLUMNS = {
  일시: 'created_at',
  사용자: 'user',
  작업: 'action',
  대상: 'target_type',
};

function renderPagination(page, totalPages) {
  const box = $('#logPagination');
  if (!box) return;
  if (totalPages <= 1) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `
    <button type="button" class="ghost small" id="logPrev" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${page} / ${totalPages} 페이지</span>
    <button type="button" class="ghost small" id="logNext" ${page >= totalPages ? 'disabled' : ''}>다음 →</button>
  `;
  box.querySelector('#logPrev')?.addEventListener('click', () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    search();
  });
  box.querySelector('#logNext')?.addEventListener('click', () => {
    if (currentPage >= totalPages) return;
    currentPage += 1;
    search();
  });
}

function renderSortableHead() {
  const thead = document.querySelector('#logTable thead tr');
  if (!thead) return;

  thead.querySelectorAll('th').forEach((th) => {
    const label = th.textContent.replace(/[\u25b2\u25bc]/g, '').trim();
    const column = SORT_COLUMNS[label];
    if (!column) return;

    const isActive = sortCol === column;
    th.textContent = label + (isActive ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '');
    th.classList.add('sortable');
    th.classList.toggle('sorted', isActive);

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

async function search() {
  const table = $('#logTable');
  const meta = $('#logMeta');
  if (!table || !meta) return;

  meta.textContent = '조회 중…';

  const params = new URLSearchParams({
    page: String(currentPage),
    q: $('#logSearch')?.value.trim() || '',
    action: $('#logAction')?.value || '',
    date: $('#logDate')?.value || '',
    sort: sortCol,
    dir: sortDir,
  });

  try {
    const response = await fetch('/api/adminlog?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '조회에 실패했습니다.');

    if (!actionsLoaded && data.actions) {
      const select = $('#logAction');
      data.actions.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.value;
        option.textContent = item.label;
        select.appendChild(option);
      });
      actionsLoaded = true;
    }

    const rows = data.items || [];

    table.querySelector('tbody').innerHTML = rows.length
      ? rows.map((item) => `
          <tr>
            <td>${esc(item.created_at)}</td>
            <td>${esc(item.user || '')}</td>
            <td>${esc(item.action_label)}</td>
            <td>${esc(item.target_type || '')}${item.target_id ? ' #' + esc(item.target_id) : ''}</td>
            <td>${esc(item.detail || '')}</td>
          </tr>
        `).join('')
      : '<tr><td colspan="5" class="empty">기록이 없습니다.</td></tr>';

    currentPage = data.page || 1;
    renderPagination(currentPage, data.total_pages || 1);
    meta.textContent = `총 ${data.count || 0}건`;
    renderSortableHead();
  } catch (error) {
    meta.textContent = error.message;
  }
}

$('#logSearch')?.addEventListener('input', () => {
  clearTimeout(timer);
  currentPage = 1;
  timer = setTimeout(search, 250);
});

$('#logDate')?.addEventListener('change', () => {
  currentPage = 1;
  search();
});

$('#logAction')?.addEventListener('change', () => {
  currentPage = 1;
  search();
});

search();
