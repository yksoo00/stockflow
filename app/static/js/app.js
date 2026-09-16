function escHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[c]));
}

function showResultModal(message, type) {
  document.querySelectorAll('.result-modal-overlay').forEach((el) => el.remove());

  const overlay = document.createElement('div');
  overlay.className = 'result-modal-overlay';
  overlay.innerHTML = `
    <div class="result-modal-box ${type === 'error' ? 'error' : 'success'}">
      <div class="result-modal-icon">${type === 'error' ? '✕' : '✓'}</div>
      <p class="result-modal-message">${escHtml(message)}</p>
      <button type="button" class="primary result-modal-ok">확인</button>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector('.result-modal-ok').addEventListener('click', close);
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) close();
  });

  const timer = setTimeout(close, 2600);
  overlay.querySelector('.result-modal-ok').addEventListener('click', () => clearTimeout(timer));
}

window.showResultModal = showResultModal;

// ---------------------------------------------------------------------------
// CSRF: 서버(Flask-WTF)가 모든 POST/PATCH/DELETE 에 토큰을 요구한다.
// 각 페이지 스크립트의 fetch 호출을 일일이 고치는 대신, 같은 출처로 가는
// 상태 변경 요청에 X-CSRFToken 헤더를 자동으로 붙인다.
// ---------------------------------------------------------------------------
(() => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.getAttribute('content') : '';
  if (!token || typeof window.fetch !== 'function') return;

  const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
  const nativeFetch = window.fetch.bind(window);

  window.fetch = (input, init = {}) => {
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    if (SAFE_METHODS.has(method)) return nativeFetch(input, init);

    const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
    if (url.origin !== window.location.origin) return nativeFetch(input, init);

    const headers = new Headers((init && init.headers) || (input && input.headers) || undefined);
    if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', token);
    return nativeFetch(input, { ...init, headers });
  };
})();

// 모바일 사이드바 토글
document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.getElementById('navToggle');
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('navBackdrop');
  if (!toggle || !sidebar) return;

  const close = () => {
    sidebar.classList.remove('open');
    backdrop?.classList.remove('show');
  };

  toggle.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    backdrop?.classList.toggle('show');
  });

  backdrop?.addEventListener('click', close);
  sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', close));
});

// ---------------------------------------------------------------------------
// 사이드바 '입고 요청' 미승인 배지. 서버가 페이지 렌더링 시 초기값을 넣어주고,
// 여기서는 관리자에 한해 60초마다 갱신한다 (다른 탭에서 승인해도 숫자가 맞도록).
// ---------------------------------------------------------------------------
(() => {
  const badge = document.getElementById('pendingBadge');
  if (!badge || !window.IS_ADMIN) return;

  const render = (count, stale, staleDays) => {
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.hidden = !(count > 0);
    // 기준일(STOCKREQUEST_STALE_DAYS) 이상 방치된 건이 있으면 진한 색 + 깜빡임으로 강조
    badge.classList.toggle('stale', stale > 0);
    badge.title = (stale > 0 ? `${stale}건이 ${staleDays}일 이상 방치됨 · ` : '') + `승인 대기 ${count}건`;
  };

  const refresh = async () => {
    try {
      const response = await fetch('/api/stockrequest/pending-count');
      if (!response.ok) return;
      const data = await response.json();
      render(Number(data.count) || 0, Number(data.stale) || 0, data.stale_days);
    } catch (_) {
      /* 네트워크 오류는 무시 — 다음 주기에 다시 시도 */
    }
  };

  setInterval(refresh, 60 * 1000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refresh();
  });
  window.refreshPendingBadge = refresh;
})();

document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('flash-data');
  if (!el) return;

  try {
    const messages = JSON.parse(el.textContent);
    messages.forEach(([category, message], index) => {
      setTimeout(() => showResultModal(message, category === 'error' ? 'error' : 'success'), index * 2800);
    });
  } catch (error) {
    console.error('flash 메시지 파싱 실패', error);
  }
});
