const $ = (selector) => document.querySelector(selector);

const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));

let timer = null;
let users = [];

const ROLE_LABEL = {admin: '관리자', user: '일반 사용자'};

function rowHtml(u) {
  const isSelf = u.id === window.USER_ID;
  return `
    <tr data-id="${u.id}" class="${u.active ? '' : 'cancelled-row'}">
      <td class="no-strike"><b>${esc(u.username)}</b>${isSelf ? ' <span class="tag info">나</span>' : ''}${u.must_change_password ? ' <span class="tag danger" title="임시 비밀번호 상태">임시PW</span>' : ''}</td>
      <td class="no-strike"><input class="inline-edit" data-field="name" value="${esc(u.name || '')}" placeholder="이름"></td>
      <td class="no-strike"><input class="inline-edit" data-field="position" value="${esc(u.position || '')}" placeholder="직책"></td>
      <td class="no-strike">
        <select class="inline-edit" data-field="role" ${isSelf ? 'disabled title="자기 자신의 역할은 바꿀 수 없습니다"' : ''}>
          ${(window.ROLES || ['admin', 'user']).map((r) => `<option value="${r}" ${u.role === r ? 'selected' : ''}>${ROLE_LABEL[r] || r}</option>`).join('')}
        </select>
      </td>
      <td class="no-strike"><input class="inline-edit" data-field="email" type="email" value="${esc(u.email || '')}" placeholder="이메일"></td>
      <td class="no-strike"><input class="inline-edit" data-field="site" value="${esc((u.sites || []).join(', '))}" placeholder="담당 사이트 (쉼표 구분)" title="여러 개면 쉼표로 구분"></td>
      <td class="no-strike">${u.active ? '<span class="tag ok">활성</span>' : '<span class="tag danger">비활성</span>'}</td>
      <td class="no-strike">${esc(u.created_at || '')}</td>
      <td class="no-strike">
        <button type="button" class="ghost small reset-btn" data-id="${u.id}">PW 초기화</button>
        ${isSelf ? '' : `<button type="button" class="ghost small toggle-btn" data-id="${u.id}" data-active="${u.active ? '1' : '0'}">${u.active ? '비활성화' : '활성화'}</button>`}
      </td>
    </tr>
  `;
}

async function load() {
  const meta = $('#userMeta');
  const table = $('#userTable');
  if (!table) return;
  meta.textContent = '조회 중…';
  try {
    const params = new URLSearchParams({q: $('#userSearch')?.value.trim() || ''});
    const response = await fetch('/api/users?' + params.toString());
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '조회에 실패했습니다.');
    users = data.items || [];
    table.querySelector('tbody').innerHTML = users.map(rowHtml).join('') || '<tr><td colspan="9" class="empty">사용자가 없습니다.</td></tr>';
    meta.textContent = `총 ${users.length}명 · 활성 ${users.filter((u) => u.active).length}명`;
    bind(table);
  } catch (error) {
    meta.textContent = error.message;
  }
}

async function patchUser(id, payload) {
  const response = await fetch(`/api/users/${id}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '저장에 실패했습니다.');
  return data.item;
}

function bind(table) {
  table.querySelectorAll('.inline-edit').forEach((input) => {
    const tr = input.closest('tr');
    const id = Number(tr.dataset.id);
    const original = users.find((u) => u.id === id);
    const save = async () => {
      const field = input.dataset.field;
      const value = input.value.trim();
      if (String(original?.[field] ?? '') === value) return;
      try {
        const item = await patchUser(id, {[field]: value});
        Object.assign(original, item);
        if (field === 'site') input.value = (item.sites || []).join(', ');
        showResultModal('저장되었습니다.', 'success');
        if (field === 'role') load();
      } catch (error) {
        input.value = original?.[field] ?? '';
        showResultModal(error.message, 'error');
      }
    };
    input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'blur', save);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && input.tagName !== 'SELECT') input.blur();
    });
  });

  table.querySelectorAll('.toggle-btn').forEach((button) => {
    button.addEventListener('click', async () => {
      const id = Number(button.dataset.id);
      const active = button.dataset.active === '1';
      const u = users.find((x) => x.id === id);
      if (!confirm(`${u.name || u.username} 계정을 ${active ? '비활성화' : '활성화'}할까요?${active ? '\n비활성화하면 로그인할 수 없습니다. 이력은 그대로 남습니다.' : ''}`)) return;
      try {
        await patchUser(id, {active: !active});
        await load();
        showResultModal(active ? '비활성화되었습니다.' : '활성화되었습니다.', 'success');
      } catch (error) {
        showResultModal(error.message, 'error');
      }
    });
  });

  table.querySelectorAll('.reset-btn').forEach((button) => {
    button.addEventListener('click', async () => {
      const id = Number(button.dataset.id);
      const u = users.find((x) => x.id === id);
      if (!confirm(`${u.name || u.username} 의 비밀번호를 초기화할까요?\n임시 비밀번호가 한 번만 표시되며, 사용자는 다음 로그인 때 변경해야 합니다.`)) return;
      try {
        const response = await fetch(`/api/users/${id}/reset-password`, {method: 'POST'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '초기화에 실패했습니다.');
        $('#resetModalBody').innerHTML = `
          <p><b>${esc(u.name || u.username)}</b> (${esc(u.username)}) 의 임시 비밀번호입니다. 이 창을 닫으면 다시 볼 수 없습니다.</p>
          <div class="temp-pw">${esc(data.temp_password)}</div>
          <p class="sheet-help">사용자에게 안전한 경로로 전달하세요. 로그인하면 바로 비밀번호 변경 화면으로 이동합니다.</p>
        `;
        $('#resetModal').style.display = 'flex';
        load();
      } catch (error) {
        showResultModal(error.message, 'error');
      }
    });
  });
}

const closeReset = () => { $('#resetModal').style.display = 'none'; };
$('#resetModalClose')?.addEventListener('click', closeReset);
$('#resetModalOk')?.addEventListener('click', closeReset);

$('#userSearch')?.addEventListener('input', () => {
  clearTimeout(timer);
  timer = setTimeout(load, 250);
});

load();
