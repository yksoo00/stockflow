const $ = (selector) => document.querySelector(selector);

let timer = null;
let sheets = [];
let selectedSheets = [];
let activeFilter = '';
let editMode = false;
let currentPage = 1;
let currentColumns = [];
let currentRows = {};
let modalRow = null;
let sortCol = '';
let sortDir = 'desc';

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

function showToast(message, type) {
  showResultModal(message, type);
}

function renderPagination(page, totalPages) {
  const box = $('#pagination');
  if (!box) return;
  if (totalPages <= 1) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `
    <button type="button" class="ghost small" id="prevPage" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${page} / ${totalPages} 페이지</span>
    <button type="button" class="ghost small" id="nextPage" ${page >= totalPages ? 'disabled' : ''}>다음 →</button>
  `;
  box.querySelector('#prevPage')?.addEventListener('click', async () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    await search();
  });
  box.querySelector('#nextPage')?.addEventListener('click', async () => {
    if (currentPage >= totalPages) return;
    currentPage += 1;
    await search();
  });
}

function ids() {
  return selectedSheets.join(',');
}

function updateSelectionText() {
  const element = $('#sheetSelectionText');
  if (element) element.textContent = selectedSheets.length ? `${selectedSheets.length}개 선택` : '전체';
}

function updateSearchPlaceholder() {
  const input = $('#sheetSearch');
  if (!input) return;
  input.placeholder = activeFilter
    ? `${activeFilter} 기준으로 검색`
    : '전체 컬럼에서 검색';
}

function renderTabs() {
  const box = $('#sheetTabs');
  if (!box) return;

  box.innerHTML = sheets.length
    ? sheets.map((sheet) => `
      <button type="button"
              class="sheet-tab ${selectedSheets.includes(sheet.id) ? 'active' : ''}"
              data-id="${sheet.id}"
              aria-pressed="${selectedSheets.includes(sheet.id)}">
        <span>${esc(sheet.name)}</span><small>${esc(sheet.type)}</small>
      </button>
    `).join('')
    : '<span class="empty-inline">Sheet가 없습니다.</span>';

  box.querySelectorAll('.sheet-tab').forEach((button) => {
    button.addEventListener('click', async () => {
      const id = Number(button.dataset.id);
      toggleSheet(id);
      await refreshForSelection();
    });
  });
}

function renderPicker() {
  const box = $('#sheetPickerMenu');
  if (!box) return;

  box.innerHTML = sheets.length
    ? `
      <div class="sheet-picker-actions">
        <button type="button" class="sheet-picker-action" data-select="all">전체 선택</button>
        <button type="button" class="sheet-picker-action" data-select="none">전체 해제</button>
      </div>
      ${sheets.map((sheet) => `
        <label class="sheet-option">
          <input type="checkbox" value="${sheet.id}" ${selectedSheets.includes(sheet.id) ? 'checked' : ''}>
          <span>${esc(sheet.name)}</span>
        </label>
      `).join('')}
    `
    : '<div class="sheet-option-empty">Sheet 없음</div>';

  box.querySelector('[data-select="all"]')?.addEventListener('click', async () => {
    selectedSheets = sheets.map((sheet) => sheet.id);
    await refreshForSelection();
  });

  box.querySelector('[data-select="none"]')?.addEventListener('click', async () => {
    selectedSheets = [];
    await refreshForSelection();
  });

  box.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener('change', async () => {
      selectedSheets = [...box.querySelectorAll('input[type="checkbox"]:checked')]
        .map((item) => Number(item.value));
      await refreshForSelection();
    });
  });
}

function toggleSheet(id) {
  selectedSheets = selectedSheets.includes(id)
    ? selectedSheets.filter((value) => value !== id)
    : [...selectedSheets, id];
}

async function refreshForSelection() {
  updateSelectionText();
  renderPicker();
  renderTabs();
  currentPage = 1;
  await loadFilters();
  await search();
}

async function loadSheets() {
  const response = await fetch(`/api/sheets/${window.FILE_ID}`);
  if (!response.ok) throw new Error('Sheet 목록을 불러오지 못했습니다.');
  const data = await response.json();
  sheets = data.items || [];
  renderPicker();
  renderTabs();
  updateSelectionText();
}

async function loadFilters() {
  const params = new URLSearchParams({file_id: window.FILE_ID});
  if (ids()) params.set('sheet_ids', ids());

  const response = await fetch(`/api/filters?${params.toString()}`);
  if (!response.ok) throw new Error('검색 필드를 불러오지 못했습니다.');

  const data = await response.json();
  const list = data.filters || [];
  if (activeFilter && !list.some((item) => item.name === activeFilter)) activeFilter = '';
  updateSearchPlaceholder();

  const box = $('#dynamicFilters');
  if (!box) return;

  box.innerHTML = list.length ? `
    <div class="filter-bar">
      <span class="filter-label">검색 기준</span>
      <div class="filter-buttons">
        <button type="button" class="filter-button ${!activeFilter ? 'active' : ''}" data-filter="">전체</button>
        ${list.map((filter) => `
          <button type="button" class="filter-button ${activeFilter === filter.name ? 'active' : ''}" data-filter="${esc(filter.name)}">${esc(filter.name)}</button>
        `).join('')}
      </div>
    </div>
    <div class="filter-help">버튼으로 검색 기준만 고르고, 검색어는 위의 <b>하나의 검색창</b>에 입력하세요.</div>
  ` : '';

  box.querySelectorAll('.filter-button').forEach((button) => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.filter || '';
      currentPage = 1;
      updateSearchPlaceholder();
      box.querySelectorAll('.filter-button').forEach((item) => item.classList.toggle('active', item === button));
      $('#sheetSearch')?.focus();
      search();
    });
  });
}

function isQty(column) {
  return /수량|재고|qty|quantity/i.test(column);
}

function sortableHeaderHtml(column) {
  const isActive = sortCol === column;
  const arrow = isActive ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';
  return `<th class="sortable ${isActive ? 'sorted' : ''}" data-column="${esc(column)}">${esc(column)}${arrow}</th>`;
}

function closeRowModal() {
  const modal = $('#rowModal');
  if (modal) modal.style.display = 'none';
  modalRow = null;
}

function renderRowModalView(row) {
  $('#rowModalBody').innerHTML = currentColumns.map((column) => `
    <div class="modal-field">
      <span class="modal-label">${esc(column)}</span>
      <span class="modal-value">${esc(row.data?.[column] ?? '(비어있음)')}</span>
    </div>
  `).join('');

  $('#rowModalFoot').innerHTML = window.IS_ADMIN
    ? `
      <button type="button" class="ghost" id="rowModalCloseBtn">닫기</button>
      <button type="button" class="ghost" id="rowModalStockinBtn">입고</button>
      <button type="button" class="ghost" id="rowModalStockoutBtn">출고</button>
      <button type="button" class="ghost" id="rowModalRequestBtn">입고요청</button>
      <button type="button" class="primary" id="rowModalEditBtn">수정</button>
    `
    : `
      <button type="button" class="ghost" id="rowModalCloseBtn">닫기</button>
      <button type="button" class="ghost" id="rowModalStockinBtn">입고</button>
      <button type="button" class="ghost" id="rowModalStockoutBtn">출고</button>
      <button type="button" class="primary" id="rowModalRequestBtn">입고요청</button>
    `;

  $('#rowModalCloseBtn').addEventListener('click', closeRowModal);
  $('#rowModalEditBtn')?.addEventListener('click', () => renderRowModalEdit(row));
  $('#rowModalStockinBtn')?.addEventListener('click', () => renderRowModalStockIn(row));
  $('#rowModalStockoutBtn')?.addEventListener('click', () => renderRowModalStockOut(row));
  $('#rowModalRequestBtn')?.addEventListener('click', () => renderRowModalRequest(row));
}

function renderRowModalEdit(row) {
  $('#rowModalBody').innerHTML = currentColumns.map((column) => `
    <div class="modal-field">
      <span class="modal-label">${esc(column)}</span>
      <input class="modal-input" data-column="${esc(column)}" value="${esc(row.data?.[column] ?? '')}">
    </div>
  `).join('');

  $('#rowModalFoot').innerHTML = `
    <button type="button" class="ghost" id="rowModalCancelBtn">취소</button>
    <button type="button" class="primary" id="rowModalSaveBtn">저장</button>
  `;

  $('#rowModalCancelBtn').addEventListener('click', () => renderRowModalView(row));
  $('#rowModalSaveBtn').addEventListener('click', () => saveRowModal(row));
}

async function saveRowModal(row) {
  const payload = {};
  $('#rowModalBody').querySelectorAll('.modal-input').forEach((input) => {
    payload[input.dataset.column] = input.value.trim();
  });

  const saveBtn = $('#rowModalSaveBtn');
  saveBtn.disabled = true;
  saveBtn.textContent = '저장 중…';

  try {
    const response = await fetch(`/api/rows/${row.id}`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({data: payload, reason: '상세보기에서 직접 수정'}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '수정에 실패했습니다.');

    row.data = {...row.data, ...payload};
    currentRows[row.id] = row;
    renderRowModalView(row);
    await search();
    showToast('저장되었습니다.');
  } catch (error) {
    saveBtn.disabled = false;
    saveBtn.textContent = '저장';
    showToast('저장 실패하였습니다. ' + error.message, 'error');
  }
}

function openRowModal(row) {
  modalRow = row;
  $('#rowModal').style.display = 'flex';
  renderRowModalView(row);
}

function renderRowModalStockOut(row) {
  const currentQty = row.quantity ?? 0;

  $('#rowModalBody').innerHTML = `
    <div class="modal-field">
      <span class="modal-label">품목</span>
      <span class="modal-value">${esc(row.identifier || row.item_name || ('#' + row.id))}</span>
    </div>
    <div class="modal-field">
      <span class="modal-label">현재 수량</span>
      <span class="modal-value">${esc(currentQty)}</span>
    </div>
    <div class="modal-field">
      <span class="modal-label">출고 수량</span>
      <input type="number" min="0" max="${esc(currentQty)}" step="any" class="modal-input" id="stockoutQty" value="${esc(currentQty)}">
    </div>
    <div class="modal-field">
      <span class="modal-label">출고 사이트</span>
      ${window.siteInputHtml('stockoutSite', '예: 서울 IDC, A사이트 등')}
    </div>
    <div class="modal-field">
      <span class="modal-label">출고 사유</span>
      <input class="modal-input" id="stockoutReason" placeholder="예: 장애처리">
    </div>
    <div class="modal-field">
      <span class="modal-label">장애 티켓 번호</span>
      <input class="modal-input" id="stockoutTicket" placeholder="예: INC-2026-0912 (선택)">
    </div>
    <div class="modal-field">
      <span class="modal-label">현장 담당자</span>
      <input class="modal-input" id="stockoutHandler" placeholder="예: 김OO (선택)">
    </div>
    <div class="modal-field">
      <span class="modal-label">시리얼번호</span>
      <textarea class="modal-textarea" id="stockoutSerials" placeholder="한 줄에 하나씩 (선택). 입력하면 개수가 출고 수량과 같아야 합니다."></textarea>
    </div>
  `;

  $('#rowModalFoot').innerHTML = `
    <button type="button" class="ghost" id="rowModalCancelStockoutBtn">취소</button>
    <button type="button" class="primary" id="rowModalStockoutSubmitBtn">출고</button>
  `;

  $('#rowModalCancelStockoutBtn').addEventListener('click', () => renderRowModalView(row));
  $('#rowModalStockoutSubmitBtn').addEventListener('click', () => submitStockOut(row));

  $('#stockoutSite').focus();
}

async function submitStockOut(row) {
  const site = $('#stockoutSite').value.trim();
  const reason = $('#stockoutReason').value.trim();
  const ticket_no = $('#stockoutTicket')?.value.trim() || '';
  const handler = $('#stockoutHandler')?.value.trim() || '';
  const serials = $('#stockoutSerials')?.value || '';
  const quantity = Number($('#stockoutQty').value);

  if (!site) {
    showToast('출고할 사이트를 입력하세요.', 'error');
    return;
  }

  if (!quantity || quantity <= 0) {
    showToast('출고 수량을 올바르게 입력하세요.', 'error');
    return;
  }

  const serialCount = serials.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean).length;
  if (serialCount && serialCount !== quantity) {
    showToast(`시리얼 개수(${serialCount})가 출고 수량(${quantity})과 다릅니다.`, 'error');
    return;
  }

  const submitBtn = $('#rowModalStockoutSubmitBtn');
  submitBtn.disabled = true;
  submitBtn.textContent = '처리 중…';

  try {
    const response = await fetch('/api/stockout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({row_id: row.id, site, quantity, reason, ticket_no, handler, serials}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '출고 처리에 실패했습니다.');

    row.quantity = data.row_quantity;
    currentRows[row.id] = row;
    closeRowModal();
    await search();
    showToast(data.auto_request_created ? '출고되었습니다. (재고 부족 → 입고요청 자동 생성됨)' : '출고되었습니다.');
  } catch (error) {
    submitBtn.disabled = false;
    submitBtn.textContent = '출고';
    showToast('출고 실패하였습니다. ' + error.message, 'error');
  }
}

function renderRowModalStockIn(row) {
  const currentQty = row.quantity ?? 0;

  $('#rowModalBody').innerHTML = `
    <div class="modal-field">
      <span class="modal-label">품목</span>
      <span class="modal-value">${esc(row.identifier || row.item_name || ('#' + row.id))}</span>
    </div>
    <div class="modal-field">
      <span class="modal-label">현재 수량</span>
      <span class="modal-value">${esc(currentQty)}</span>
    </div>
    <div class="modal-field">
      <span class="modal-label">입고 수량</span>
      <input type="number" min="0" step="any" class="modal-input" id="stockinQty" placeholder="예: 5">
    </div>
    <div class="modal-field">
      <span class="modal-label">입고 사유</span>
      <input class="modal-input" id="stockinReason" placeholder="예: 구매 입고 (선택)">
    </div>
    <div class="modal-field">
      <span class="modal-label">시리얼번호</span>
      <textarea class="modal-textarea" id="stockinSerials" placeholder="한 줄에 하나씩 (선택). 입력하면 개수가 입고 수량과 같아야 합니다."></textarea>
    </div>
  `;

  $('#rowModalFoot').innerHTML = `
    <button type="button" class="ghost" id="rowModalCancelStockinBtn">취소</button>
    <button type="button" class="primary" id="rowModalStockinSubmitBtn">입고</button>
  `;

  $('#rowModalCancelStockinBtn').addEventListener('click', () => renderRowModalView(row));
  $('#rowModalStockinSubmitBtn').addEventListener('click', () => submitStockIn(row));

  $('#stockinQty').focus();
}

async function submitStockIn(row) {
  const quantity = Number($('#stockinQty').value);
  const reason = $('#stockinReason')?.value.trim() || '';
  const serials = $('#stockinSerials')?.value || '';

  if (!quantity || quantity <= 0) {
    showToast('입고 수량을 올바르게 입력하세요.', 'error');
    return;
  }

  const serialCount = serials.split(/[\n,;]+/).map((s) => s.trim()).filter(Boolean).length;
  if (serialCount && serialCount !== quantity) {
    showToast(`시리얼 개수(${serialCount})가 입고 수량(${quantity})과 다릅니다.`, 'error');
    return;
  }

  const submitBtn = $('#rowModalStockinSubmitBtn');
  submitBtn.disabled = true;
  submitBtn.textContent = '처리 중…';

  try {
    const response = await fetch('/api/stockin', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({row_id: row.id, quantity, reason, serials}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '입고 처리에 실패했습니다.');

    row.quantity = data.row_quantity;
    currentRows[row.id] = row;
    closeRowModal();
    await search();
    showToast('입고되었습니다.');
  } catch (error) {
    submitBtn.disabled = false;
    submitBtn.textContent = '입고';
    showToast('입고 실패하였습니다. ' + error.message, 'error');
  }
}

function renderRowModalRequest(row) {
  const currentQty = row.quantity ?? 0;

  $('#rowModalBody').innerHTML = `
    <div class="modal-field">
      <span class="modal-label">품목</span>
      <span class="modal-value">${esc(row.identifier || row.item_name || ('#' + row.id))}</span>
    </div>
    <div class="modal-field">
      <span class="modal-label">현재 수량</span>
      <span class="modal-value">${esc(currentQty)}</span>
    </div>
    <div class="modal-field">
      <span class="modal-label">사이트</span>
      ${window.siteInputHtml('requestSite', '예: 서울 IDC, A사이트 등')}
    </div>
    <div class="modal-field">
      <span class="modal-label">요청 수량</span>
      <input type="number" min="0" step="any" class="modal-input" id="requestQty" placeholder="예: 2">
    </div>
    <div class="modal-field">
      <span class="modal-label">요청 이유</span>
      <input class="modal-input" id="requestReason" placeholder="예: 재고 부족 대비">
    </div>
  `;

  $('#rowModalFoot').innerHTML = `
    <button type="button" class="ghost" id="rowModalCancelRequestBtn">취소</button>
    <button type="button" class="primary" id="rowModalRequestSubmitBtn">요청</button>
  `;

  $('#rowModalCancelRequestBtn').addEventListener('click', () => renderRowModalView(row));
  $('#rowModalRequestSubmitBtn').addEventListener('click', () => submitRequest(row));

  $('#requestSite').focus();
}

async function submitRequest(row) {
  const site = $('#requestSite').value.trim();
  const quantity = Number($('#requestQty').value);
  const reason = $('#requestReason').value.trim();

  if (!site) {
    showToast('요청할 사이트를 입력하세요.', 'error');
    return;
  }

  if (!quantity || quantity <= 0) {
    showToast('요청 수량을 올바르게 입력하세요.', 'error');
    return;
  }

  const submitBtn = $('#rowModalRequestSubmitBtn');
  submitBtn.disabled = true;
  submitBtn.textContent = '처리 중…';

  try {
    const response = await fetch('/api/stockrequest', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({row_id: row.id, site, quantity, reason}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '요청에 실패했습니다.');

    closeRowModal();
    showToast('입고요청되었습니다.');
  } catch (error) {
    submitBtn.disabled = false;
    submitBtn.textContent = '요청';
    showToast('요청 실패하였습니다. ' + error.message, 'error');
  }
}

function updateEditButton() {
  const button = $('#editSheetBtn');
  if (!button) return;
  button.textContent = editMode ? '수정 모드 종료' : '선택한 Sheet 수정하기';
  button.classList.toggle('primary', editMode);
}

function rowHtml(row, columns) {
  const cells = columns.map((column) => {
    const value = row.data?.[column] ?? '';
    const low = isQty(column) && value !== '' && !Number.isNaN(Number(value)) && Number(value) <= 1;

    if (!editMode) {
      return `<td class="${low ? 'qty low' : ''}">${esc(value)}</td>`;
    }

    return `
      <td class="${low ? 'qty low' : ''} editable-cell" data-column="${esc(column)}">
        <input class="cell-editor" value="${esc(value)}" aria-label="${esc(column)} 수정">
      </td>
    `;
  }).join('');

  return `<tr data-id="${row.id}">${cells}${editMode ? '<td class="row-action"><button type="button" class="primary small row-save">저장</button></td>' : ''}</tr>`;
}

async function search() {
  const input = $('#sheetSearch');
  const table = $('#sheetTable');
  if (!input || !table) return;

  const text = input.value.trim();
  const filters = activeFilter && text ? {[activeFilter]: text} : {};
  const params = new URLSearchParams({
    file_id: window.FILE_ID,
    q: activeFilter ? '' : text,
    filters: JSON.stringify(filters),
    page_size: '10',
    page: String(currentPage),
  });
  if (ids()) params.set('sheet_ids', ids());
  if (sortCol) { params.set('sort', sortCol); params.set('dir', sortDir); }

  try {
    const response = await fetch(`/api/search?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '검색에 실패했습니다.');

    const columns = data.columns || [];
    currentColumns = columns;
    currentRows = {};
    (data.items || []).forEach((row) => { currentRows[row.id] = row; });
    table.querySelector('thead').innerHTML = `<tr>${columns.map((column) => sortableHeaderHtml(column)).join('')}${editMode ? '<th class="action-col">작업</th>' : ''}</tr>`;
    table.querySelector('tbody').innerHTML = (data.items || []).map((row) => rowHtml(row, columns)).join('');
    currentPage = data.page || 1;
    renderPagination(currentPage, data.total_pages || 1);
    $('#resultMeta').textContent = `검색 결과 ${data.count || 0}건 · ${columns.length}개 컬럼 · ${selectedSheets.length ? `${selectedSheets.length}개 Sheet` : '전체 Sheet'}`;

    table.querySelectorAll('th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const column = th.dataset.column;
        if (sortCol === column) {
          sortDir = sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          sortCol = column;
          sortDir = 'asc';
        }
        currentPage = 1;
        search();
      });
    });

    if (editMode) {
      table.querySelectorAll('.row-save').forEach((button) => {
        button.addEventListener('click', () => saveRow(button.closest('tr'), columns, button));
      });
    }
  } catch (error) {
    $('#resultMeta').textContent = error.message;
  }
}

async function saveRow(tr, columns, button) {
  const id = Number(tr.dataset.id);
  const payload = {};
  tr.querySelectorAll('.cell-editor').forEach((input) => {
    payload[input.closest('.editable-cell').dataset.column] = input.value.trim();
  });

  button.disabled = true;
  button.textContent = '저장 중…';

  try {
    const response = await fetch(`/api/rows/${id}`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({data: payload, reason: '웹 Sheet 셀 직접 수정'}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '수정에 실패했습니다.');
    button.textContent = '저장 완료';
    setTimeout(() => { if (button) button.textContent = '저장'; }, 900);
    showToast('저장되었습니다.');
  } catch (error) {
    button.disabled = false;
    button.textContent = '저장';
    showToast('저장 실패하였습니다. ' + error.message, 'error');
  }
}

$('#sheetSearch')?.addEventListener('input', () => {
  clearTimeout(timer);
  currentPage = 1;
  timer = setTimeout(search, 250);
});

$('#sheetPicker')?.addEventListener('click', (event) => {
  if (event.target.closest('.sheet-picker-button')) $('#sheetPicker').classList.toggle('open');
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('.sheet-picker')) {
    document.querySelectorAll('.sheet-picker').forEach((element) => element.classList.remove('open'));
  }
});

$('#editSheetBtn')?.addEventListener('click', async () => {
  if (!editMode && selectedSheets.length !== 1) {
    alert('수정하려면 Sheet를 정확히 하나 선택하세요.');
    return;
  }
  editMode = !editMode;
  updateEditButton();
  await search();
});

$('#sheetTable')?.addEventListener('click', (event) => {
  if (editMode) return;
  if (event.target.closest('button, input, a')) return;
  const tr = event.target.closest('tbody tr[data-id]');
  if (!tr) return;
  const row = currentRows[Number(tr.dataset.id)];
  if (row) openRowModal(row);
});

$('#rowModalClose')?.addEventListener('click', closeRowModal);

$('#rowModal')?.addEventListener('click', (event) => {
  if (event.target.id === 'rowModal') closeRowModal();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeRowModal();
});

$('#addColumn')?.addEventListener('click', async () => {
  if (selectedSheets.length !== 1) {
    alert('컬럼을 추가하려면 Sheet를 정확히 하나 선택하세요.');
    return;
  }
  const name = prompt('추가할 컬럼명을 입력하세요.')?.trim();
  if (!name) return;

  try {
    const response = await fetch('/api/columns', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sheet_id: selectedSheets[0], name}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '컬럼 추가에 실패했습니다.');
    await loadSheets();
    await loadFilters();
    await search();
    showToast('컬럼이 추가되었습니다.');
  } catch (error) {
    showToast('컬럼 추가에 실패하였습니다. ' + error.message, 'error');
  }
});

(async function init() {
  try {
    await loadSheets();
    await loadFilters();
    await search();
  } catch (error) {
    $('#resultMeta').textContent = error.message;
  }
}());
