let currentPage = 1;

const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

function formatPrice(item) {
  if (item.price === null || item.price === undefined) return '가격 정보 없음';
  const total = item.price + (item.shipping || 0);
  const currency = item.currency || 'USD';
  const shippingText = item.shipping ? ` (배송비 ${item.shipping.toFixed(2)} 포함)` : ' (무료배송)';
  return `${currency} ${total.toFixed(2)}${shippingText}`;
}

function cardHtml(item, isCheapest) {
  const image = item.image
    ? `<img src="${esc(item.image)}" alt="${esc(item.title)}">`
    : '<div class="ebay-card-noimg">이미지 없음</div>';

  return `
    <a class="ebay-card ${isCheapest ? 'cheapest' : ''}" href="${esc(item.url || '#')}" target="_blank" rel="noopener noreferrer">
      ${isCheapest ? '<span class="ebay-badge">최저가</span>' : ''}
      ${image}
      <div class="ebay-card-body">
        <b>${esc(item.title || '제목 없음')}</b>
        <span class="ebay-price">${esc(formatPrice(item))}</span>
        <span class="ebay-meta">${esc(item.condition || '')}${item.seller ? ' · ' + esc(item.seller) : ''}</span>
      </div>
    </a>
  `;
}

function renderPagination(page, hasNext, totalPages) {
  const box = $('#ebayPagination');
  if (!box) return;
  if (page <= 1 && !hasNext) {
    box.innerHTML = '';
    return;
  }
  const pageLabel = totalPages ? `${page} / ${totalPages} 페이지` : `${page} 페이지`;
  box.innerHTML = `
    <button type="button" class="ghost small" id="ebayPrevPage" ${page <= 1 ? 'disabled' : ''}>← 이전</button>
    <span>${pageLabel}</span>
    <button type="button" class="ghost small" id="ebayNextPage" ${hasNext ? '' : 'disabled'}>다음 →</button>
  `;
  box.querySelector('#ebayPrevPage')?.addEventListener('click', async () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    await search();
  });
  box.querySelector('#ebayNextPage')?.addEventListener('click', async () => {
    if (!hasNext) return;
    currentPage += 1;
    await search();
  });
}

async function search() {
  const code = $('#ebaySearch').value.trim();
  const meta = $('#ebayMeta');
  const box = $('#ebayResults');

  if (!code) return;

  meta.textContent = '조회 중…';
  box.innerHTML = '';

  try {
    const params = new URLSearchParams({q: code, page: String(currentPage)});
    const response = await fetch('/api/ebay/search?' + params.toString());
    const data = await response.json();

    if (!response.ok) throw new Error(data.error || 'eBay 조회에 실패했습니다.');

    const items = data.items || [];
    const sourceLabel = data.source === 'api' ? 'eBay API' : '공개 페이지 스크랩(참고용)';

    meta.innerHTML = '';

    if (data.warning) {
      meta.innerHTML += `<span class="ebay-warning">⚠ ${esc(data.warning)}</span>`;
    }

    const totalLabel = data.total !== null && data.total !== undefined ? ` · 전체 ${data.total}건` : '';

    meta.innerHTML += items.length
      ? `<span>${items.length}건 표시${totalLabel} · 최저가순 정렬 · 조회 방식: ${sourceLabel}</span>`
      : `<span>조회된 매물이 없습니다.</span>`;

    box.innerHTML = items.map((item, index) => cardHtml(item, currentPage === 1 && index === 0)).join('');

    currentPage = data.page || currentPage;
    renderPagination(currentPage, Boolean(data.has_next), data.total_pages);
  } catch (error) {
    meta.innerHTML = `<span class="ebay-error">✕ ${esc(error.message)}</span>`;
    renderPagination(1, false, null);
  }
}

$('#ebaySearchBtn').addEventListener('click', () => {
  currentPage = 1;
  search();
});

$('#ebaySearch').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    currentPage = 1;
    search();
  }
});

(async function init() {
  if (window.EBAY_CODE) {
    $('#ebaySearch').value = window.EBAY_CODE;
    await search();
  }
}());
