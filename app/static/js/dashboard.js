const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

let panelOpen = false;
let currentPage = 1;
let sortCol = '';
let sortDir = 'desc';

function sortableHeaderHtml(column) {
  const isActive = sortCol === column;
  const arrow = isActive ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';
  return `<th class="sortable ${isActive ? 'sorted' : ''}" data-column="${esc(column)}">${esc(column)}${arrow}</th>`;
}

function renderPagination(page, totalPages) {
  const box = $('#lowStockPagination');
  if (!box) return;
  if (totalPages <= 1) {
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `
    <button type="button" class="ghost small" id="lowPrevPage" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${page} / ${totalPages} 페이지</span>
    <button type="button" class="ghost small" id="lowNextPage" ${page >= totalPages ? 'disabled' : ''}>다음 →</button>
  `;
  box.querySelector('#lowPrevPage')?.addEventListener('click', () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    loadLowStock();
  });
  box.querySelector('#lowNextPage')?.addEventListener('click', () => {
    if (currentPage >= totalPages) return;
    currentPage += 1;
    loadLowStock();
  });
}

async function loadLowStock() {
  const table = $('#lowStockTable');
  const meta = $('#lowStockMeta');
  if (!table || !meta) return;

  meta.textContent = '조회 중…';

  try {
    const params = new URLSearchParams({low: '1', page: String(currentPage), page_size: '10'});
    if (sortCol) { params.set('sort', sortCol); params.set('dir', sortDir); }
    const response = await fetch('/api/search?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '저재고 조회에 실패했습니다.');

    const columns = data.columns || [];
    const rows = data.items || [];

    table.querySelector('thead').innerHTML = `<tr>${columns.map((column) => sortableHeaderHtml(column)).join('')}<th>파일</th></tr>`;

    table.querySelector('tbody').innerHTML = rows.map((row) => `
      <tr>
        ${columns.map((column) => {
          const value = row.data?.[column];
          const isCode = row.identifier && value !== null && value !== '' && String(value) === String(row.identifier);
          const cell = isCode
            ? `<a class="code-link" href="/ebay/${encodeURIComponent(row.identifier)}" title="eBay 최저가 조회">${esc(value)}</a>`
            : esc(value ?? '');
          return `<td>${cell}</td>`;
        }).join('')}
        <td>${esc(row.file_name || '')}</td>
      </tr>
    `).join('') || '<tr><td class="empty">저재고 항목이 없습니다.</td></tr>';

    currentPage = data.page || 1;
    renderPagination(currentPage, data.total_pages || 1);
    meta.textContent = `저재고 ${data.count || 0}건`;

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
        loadLowStock();
      });
    });
  } catch (error) {
    meta.textContent = error.message;
  }
}

$('#lowStockToggle')?.addEventListener('click', async () => {
  const panel = $('#lowStockPanel');
  if (!panel) return;

  panelOpen = !panelOpen;
  panel.style.display = panelOpen ? 'block' : 'none';
  $('#lowStockToggle').textContent = panelOpen ? '저재고 접기 ↑' : '저재고만 조회 ↓';

  if (panelOpen) {
    currentPage = 1;
    await loadLowStock();
    panel.scrollIntoView({behavior: 'smooth', block: 'start'});
  }
});

function fmtTotal(value) {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
}

function renderBarChart(box, rows) {
  if (!box) return;

  if (!rows.length) {
    box.innerHTML = '<div class="empty">최근 1년간 출고 기록이 없습니다.</div>';
    return;
  }

  const max = Math.max(...rows.map((row) => row.total)) || 1;

  box.innerHTML = rows.map((row) => `
    <div class="bar-row" title="${esc(row.label)} · ${fmtTotal(row.total)}ea">
      <span class="bar-label">${box.id === 'siteChart' ? siteLink(row.label) : esc(row.label)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${(row.total / max) * 100}%"></span></span>
      <span class="bar-value">${fmtTotal(row.total)}ea</span>
    </div>
  `).join('');
}

async function loadStats() {
  const siteBox = $('#siteChart');
  const itemBox = $('#itemChart');
  if (!siteBox && !itemBox) return;

  try {
    const response = await fetch('/api/stats/outflow');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '통계를 불러오지 못했습니다.');

    renderBarChart(siteBox, data.sites || []);
    renderBarChart(itemBox, data.items || []);
  } catch (error) {
    if (siteBox) siteBox.innerHTML = `<div class="empty">${esc(error.message)}</div>`;
    if (itemBox) itemBox.innerHTML = '';
  }
}

loadStats();

// ---------------------------------------------------------------------------
// 기간별(월/년) × 사이트별 사용 디스크
// ---------------------------------------------------------------------------
const periodState = {granularity: 'month', year: null, site: '', yearsLoaded: false};
let periodTimer = null;

function codeChipsHtml(items) {
  return `<div class="code-chips">${items.map((item) => `
    <a class="code-chip" href="/ebay/${encodeURIComponent(item.code)}" title="eBay 최저가 조회">
      ${esc(item.code)} <b>×${fmtTotal(item.total)}</b>
    </a>`).join('')}</div>`;
}

function siteLink(site) {
  if (!site || site.startsWith('(')) return esc(site);
  return `<a class="site-link" href="/sites/${encodeURIComponent(site)}" title="사이트 상세">${esc(site)}</a>`;
}

function deltaHtml(label, delta) {
  if (!delta) return `<span class="delta" title="${esc(label)} 비교 데이터 없음">${esc(label)} —</span>`;
  const dir = delta.diff > 0 ? 'up' : (delta.diff < 0 ? 'down' : '');
  const sign = delta.diff > 0 ? '+' : '';
  const pct = delta.pct === null || delta.pct === undefined ? '' : ` <small>(${sign}${Math.round(delta.pct)}%)</small>`;
  return `<span class="delta ${dir}" title="${esc(label)}: 이전 ${fmtTotal(delta.prev)}ea">${esc(label)} ${sign}${fmtTotal(delta.diff)}${pct}</span>`;
}

function renderPeriodTable(data) {
  const table = $('#periodTable');
  const meta = $('#periodMeta');
  if (!table || !meta) return;

  const periods = data.periods || [];
  const tbody = table.querySelector('tbody');

  if (!periods.length) {
    const scope = data.granularity === 'month' ? `${data.year}년` : '전체 기간';
    tbody.innerHTML = `<tr><td colspan="4" class="empty">${esc(scope)}에 출고 기록이 없습니다.</td></tr>`;
    meta.textContent = '';
    return;
  }

  const html = [];
  let grand = 0;
  let siteCount = 0;

  for (const period of periods) {
    grand += period.total;
    const rowspan = period.sites.length + 1; // 사이트 행들 + 소계 행
    period.sites.forEach((site, index) => {
      siteCount += 1;
      html.push(`<tr>
        ${index === 0 ? `<td class="period-cell" rowspan="${rowspan}">${esc(period.period)}</td>` : ''}
        <td class="site-cell">${siteLink(site.site)}</td>
        <td class="qty-cell">${fmtTotal(site.total)}ea</td>
        <td>${codeChipsHtml(site.items)}</td>
      </tr>`);
    });
    const compare = period.compare || {};
    const momLabel = data.granularity === 'month' ? '전월 대비' : '전년 대비';
    html.push(`<tr class="period-total">
      <td>소계</td>
      <td class="qty-cell">${fmtTotal(period.total)}ea</td>
      <td>${period.sites.length}개 사이트 &nbsp; ${deltaHtml(momLabel, compare.mom)}${data.granularity === 'month' ? ' ' + deltaHtml('전년 동월', compare.yoy) : ''}</td>
    </tr>`);
  }

  tbody.innerHTML = html.join('');
  meta.textContent = `${periods.length}개 기간 · ${siteCount}건 · 합계 ${fmtTotal(grand)}ea`;
}

function renderYearOptions(years, selected) {
  const select = $('#periodYear');
  if (!select) return;
  const list = years.length ? years : [new Date().getFullYear()];
  select.innerHTML = list.map((y) => `<option value="${y}" ${y === selected ? 'selected' : ''}>${y}년</option>`).join('');
}

async function loadPeriodStats() {
  const meta = $('#periodMeta');
  if (meta) meta.textContent = '조회 중…';

  try {
    const params = new URLSearchParams({granularity: periodState.granularity});
    if (periodState.granularity === 'month' && periodState.year) params.set('year', String(periodState.year));
    if (periodState.site) params.set('site', periodState.site);

    const response = await fetch('/api/stats/outflow/periodic?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '기간별 통계를 불러오지 못했습니다.');

    if (!periodState.yearsLoaded || !periodState.year) {
      periodState.year = data.year || (data.years || [])[0] || new Date().getFullYear();
      renderYearOptions(data.years || [], periodState.year);
      periodState.yearsLoaded = true;
    }

    renderPeriodTable(data);
  } catch (error) {
    if (meta) meta.textContent = error.message;
  }
}

$('#granularitySeg')?.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-granularity]');
  if (!button) return;
  periodState.granularity = button.dataset.granularity;
  $('#granularitySeg').querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === button));
  // 년도별 보기에서는 연도 선택이 의미 없으므로 숨긴다.
  const yearSelect = $('#periodYear');
  if (yearSelect) yearSelect.style.display = periodState.granularity === 'month' ? '' : 'none';
  loadPeriodStats();
});

$('#periodYear')?.addEventListener('change', (event) => {
  periodState.year = Number(event.target.value) || null;
  loadPeriodStats();
});

$('#periodSite')?.addEventListener('input', (event) => {
  clearTimeout(periodTimer);
  periodState.site = event.target.value.trim();
  periodTimer = setTimeout(loadPeriodStats, 300);
});

loadPeriodStats();

// ---------------------------------------------------------------------------
// 디스크 코드별 소비 추이 + 예상 소진
// ---------------------------------------------------------------------------
function renderTrend(data) {
  const stats = $('#trendStats');
  const chart = $('#trendChart');
  const labels = $('#trendLabels');
  const meta = $('#trendMeta');
  if (!stats || !chart) return;

  const monthsLeft = data.recent_months_left ?? data.months_left;
  const depleting = monthsLeft !== null && monthsLeft !== undefined;
  const depletionText = depleting
    ? (monthsLeft < 1 ? '1개월 이내' : `약 ${Math.round(monthsLeft)}개월 후`)
    : '출고 이력 없음';
  const warn = depleting && monthsLeft <= 3;

  stats.innerHTML = `
    <div class="trend-stat"><span>현재 재고</span><strong>${fmtTotal(data.stock)}ea</strong><small>코드 일치 행 합계</small></div>
    <div class="trend-stat"><span>${data.months}개월 출고</span><strong>${fmtTotal(data.total)}ea</strong><small>월 평균 ${fmtTotal(Number(data.avg_per_month.toFixed(2)))}ea</small></div>
    <div class="trend-stat"><span>최근 3개월 평균</span><strong>${fmtTotal(Number(data.recent_avg_per_month.toFixed(2)))}ea</strong><small>/월</small></div>
    <div class="trend-stat ${warn ? 'warn' : ''}"><span>예상 소진</span><strong>${esc(depletionText)}</strong><small>${data.depletion_month ? `${esc(data.depletion_month)} 무렵 · 최근 3개월 속도 기준` : '최근 3개월 출고 없음'}</small></div>
  `;

  const max = Math.max(...data.series.map((p) => p.total), 1);
  chart.innerHTML = data.series.map((p) => `
    <div class="col" title="${esc(p.month)} · ${fmtTotal(p.total)}ea">
      <b>${p.total ? fmtTotal(p.total) : ''}</b>
      <span class="bar" style="height:${Math.max((p.total / max) * 100, p.total ? 4 : 1)}%"></span>
    </div>
  `).join('');
  labels.innerHTML = data.series.map((p) => `<span>${esc(p.month.slice(2).replace('-', '/'))}</span>`).join('');
  meta.textContent = `${data.code} · 최근 ${data.months}개월`;
}

async function loadTrend(code) {
  const meta = $('#trendMeta');
  if (!code) return;
  if (meta) meta.textContent = '조회 중…';
  try {
    const response = await fetch(`/api/stats/codes/${encodeURIComponent(code)}/trend?months=12`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '추이를 불러오지 못했습니다.');
    renderTrend(data);
  } catch (error) {
    if (meta) meta.textContent = error.message;
  }
}

async function initTrend() {
  const select = $('#trendCode');
  const list = $('#trendCodeList');
  if (!select) return;
  try {
    const response = await fetch('/api/stats/codes');
    const data = await response.json();
    const codes = data.codes || [];
    if (!codes.length) {
      select.innerHTML = '<option value="">출고 이력이 있는 코드가 없습니다</option>';
      $('#trendStats').innerHTML = '<div class="empty">최근 1년간 출고 기록이 없습니다.</div>';
      return;
    }
    select.innerHTML = codes.map((c) => `<option value="${esc(c.code)}">${esc(c.code)} (${fmtTotal(c.total)}ea)</option>`).join('');
    if (list) list.innerHTML = codes.map((c) => `<option value="${esc(c.code)}">`).join('');
    loadTrend(codes[0].code);
  } catch (_) {
    select.innerHTML = '<option value="">불러오기 실패</option>';
  }
}

$('#trendCode')?.addEventListener('change', (event) => loadTrend(event.target.value));
$('#trendCodeInput')?.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  const code = event.target.value.trim();
  if (code) loadTrend(code);
});
initTrend();
