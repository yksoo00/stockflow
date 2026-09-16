const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

const fmt = (value) => (Number.isInteger(value) ? String(value) : String(Number(Number(value).toFixed(2))));

const STATUS_LABEL = {requested: '요청됨', approved: '승인완료', arrived: '입고완료'};
const SOURCE_LABEL = {manual: '수동', auto_request: '자동(요청승인)', cancel_out: '출고취소 원복'};

function last12Months() {
  const out = [];
  const now = new Date();
  for (let i = 11; i >= 0; i -= 1) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  }
  return out;
}

function renderColumns(box, labelsBox, series) {
  const max = Math.max(...series.map((p) => p.total), 1);
  box.innerHTML = series.map((p) => `
    <div class="col" title="${esc(p.month)} · ${fmt(p.total)}ea">
      <b>${p.total ? fmt(p.total) : ''}</b>
      <span class="bar" style="height:${Math.max((p.total / max) * 100, p.total ? 4 : 1)}%"></span>
    </div>`).join('');
  labelsBox.innerHTML = series.map((p) => `<span>${esc(p.month.slice(2).replace('-', '/'))}</span>`).join('');
}

function emptyRow(cols, text) {
  return `<tr><td colspan="${cols}" class="empty">${esc(text)}</td></tr>`;
}

async function load() {
  try {
    const response = await fetch(`/api/sites/${encodeURIComponent(window.SITE)}/summary`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '사이트 정보를 불러오지 못했습니다.');

    const months = last12Months();
    const byMonth = Object.fromEntries((data.monthly || []).map((m) => [m.month, m.total]));
    const series = months.map((m) => ({month: m, total: byMonth[m] || 0}));
    const yearTotal = series.reduce((s, p) => s + p.total, 0);

    $('#siteTotal').textContent = `${fmt(data.total)}ea`;
    $('#siteYear').textContent = `${fmt(yearTotal)}ea`;
    $('#siteAvg').textContent = fmt(Number((yearTotal / 12).toFixed(1)));
    $('#siteOpen').textContent = `${(data.open_requests || []).length}건`;

    renderColumns($('#siteChart'), $('#siteLabels'), series);

    const codes = data.by_code || [];
    const maxCode = Math.max(...codes.map((c) => c.total), 1);
    $('#siteByCode').innerHTML = codes.length ? codes.map((c) => `
      <div class="bar-row">
        <span class="bar-label"><a class="code-link" href="/ebay/${encodeURIComponent(c.code)}">${esc(c.code)}</a></span>
        <span class="bar-track"><span class="bar-fill" style="width:${(c.total / maxCode) * 100}%"></span></span>
        <span class="bar-value">${fmt(c.total)}ea</span>
      </div>`).join('') : '<div class="empty">출고 기록이 없습니다.</div>';

    $('#siteRequests').innerHTML = (data.open_requests || []).map((r) => `
      <tr><td>${esc(r.created_at)}</td><td>${esc(r.code || '')}</td><td>${esc(r.quantity)}ea</td><td><span class="tag ${r.status === 'approved' ? 'ok' : 'info'}">${esc(STATUS_LABEL[r.status] || r.status)}</span></td><td>${esc(r.requested_by || '-')}</td></tr>
    `).join('') || emptyRow(5, '진행 중인 요청이 없습니다.');

    $('#siteOut').innerHTML = (data.recent_out || []).map((o) => `
      <tr><td>${esc(o.created_at)}</td><td>${esc(o.code || '')}</td><td>${esc(o.quantity)}ea</td><td>${esc(o.reason || '')}</td><td>${esc(o.ticket_no || '')}</td><td>${esc(o.handler || '')}</td><td>${esc(o.user || '')}</td></tr>
    `).join('') || emptyRow(7, '출고 이력이 없습니다.');

    $('#siteIn').innerHTML = (data.recent_in || []).map((i) => `
      <tr><td>${esc(i.created_at)}</td><td>${esc(i.code || '')}</td><td>${esc(i.quantity)}ea</td><td>${esc(SOURCE_LABEL[i.source] || i.source)}</td><td>${esc(i.user || '')}</td></tr>
    `).join('') || emptyRow(5, '입고 이력이 없습니다.');

    $('#siteHolding').innerHTML = (data.holding || []).map((h) => `
      <tr><td>${esc(h.code || '')}</td><td>${esc(h.capacity || '')}</td><td class="${h.quantity !== null && h.quantity <= 1 ? 'qty low' : ''}">${esc(h.quantity ?? '')}</td><td>${esc(h.location || '')}</td><td><a class="site-link" href="/files/${h.file_id}">Excel →</a></td></tr>
    `).join('') || emptyRow(5, "'위치' 가 이 사이트인 재고 행이 없습니다.");
  } catch (error) {
    showResultModal(error.message, 'error');
  }
}

load();
