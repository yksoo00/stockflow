const qs = s => document.querySelector(s);

const esc = v =>
    String(v ?? '').replace(/[&<>'"]/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[c]));

async function chatFiles() {
    const r = await fetch('/api/files');
    const j = await r.json();

    qs('#chatFile').innerHTML =
        '<option value="">전체 Excel</option>' +
        (j.items || []).map(f =>
            `<option value="${f.id}">${esc(f.name)}</option>`
        ).join('');
}

async function chatSheets() {
    const fid = qs('#chatFile').value;

    qs('#chatSheet').innerHTML =
        '<option value="">전체 Sheet</option>';

    if (!fid) return;

    const r = await fetch('/api/sheets/' + fid);
    const j = await r.json();

    qs('#chatSheet').innerHTML +=
        (j.items || []).map(s =>
            `<option value="${s.id}">${esc(s.name)}</option>`
        ).join('');
}

qs('#chatFile').addEventListener('change', chatSheets);

qs('#chatForm').addEventListener('submit', async e => {

    e.preventDefault();

    const input = qs('#chatInput');
    const msg = input.value.trim();

    if (!msg) return;

    const box = qs('#chatMessages');

    /* 사용자 메시지 */
    box.insertAdjacentHTML(
        'beforeend',
        `<div class="chat-bubble user">${esc(msg)}</div>`
    );

    input.value = '';

    /* 조회 중 */
    const pending = document.createElement('div');
    pending.className = 'chat-bubble assistant';
    pending.textContent = 'DB 조회 후 답변을 생성하는 중…';

    box.appendChild(pending);
    box.scrollTop = box.scrollHeight;

    try {

        const payload = {
            message: msg,
            file_id: qs('#chatFile').value || null,
            sheet_id: qs('#chatSheet').value || null
        };

        const r = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const j = await r.json();

        pending.remove();

        if (!r.ok) {
            box.insertAdjacentHTML(
                'beforeend',
                `<div class="chat-bubble assistant error">
                    ${esc(j.error || 'AI 오류')}
                </div>`
            );

            return;
        }

        let html = esc(j.answer || '응답 없음')
            .replace(/\n/g, '<br>');

        /*
         * AI가 변경 제안을 반환한 경우
         */
        if (j.action) {

            const actionJson =
                encodeURIComponent(JSON.stringify(j.action));

            html += `
                <div class="ai-action">
                    <b>변경 제안</b>

                    <p>
                        ${esc(j.action.description)}
                    </p>

                    <button
                        class="primary small ai-apply"
                        data-action="${actionJson}">
                        이 변경 적용
                    </button>
                </div>
            `;
        }

        /*
         * DB 검색 결과가 있으면 간단히 표시
         */
        if (Array.isArray(j.sources) && j.sources.length > 0) {

            html += `
                <details class="ai-sources">
                    <summary>
                        참고한 DB 데이터 ${j.sources.length}건
                    </summary>

                    <div class="ai-source-list">
                        ${j.sources.map(row => `
                            <div class="ai-source-item">
                                <b>
                                    ${esc(
                                        row.identifier ||
                                        row.model ||
                                        row.item_name ||
                                        `행 ${row.row_number}`
                                    )}
                                </b>

                                ${
                                    row.item_name
                                        ? `<span>${esc(row.item_name)}</span>`
                                        : ''
                                }

                                ${
                                    row.quantity !== null &&
                                    row.quantity !== undefined
                                        ? `<span>수량: ${esc(row.quantity)}</span>`
                                        : ''
                                }
                            </div>
                        `).join('')}
                    </div>
                </details>
            `;
        }

        box.insertAdjacentHTML(
            'beforeend',
            `<div class="chat-bubble assistant">${html}</div>`
        );

        /*
         * 변경 적용 버튼
         */
        box.querySelectorAll('.ai-apply').forEach(button => {

            button.onclick = async () => {

                const action =
                    JSON.parse(
                        decodeURIComponent(
                            button.dataset.action
                        )
                    );

                if (!confirm(
                    `${action.description}\n\n실제로 변경할까요?`
                )) {
                    return;
                }

                try {

                    const rr = await fetch('/api/ai/apply', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(action)
                    });

                    const jj = await rr.json();

                    if (!rr.ok) {
                        alert(jj.error || '변경 실패');
                        return;
                    }

                    alert('변경되었습니다.');

                    button.disabled = true;
                    button.textContent = '변경 완료';

                } catch (err) {
                    alert('변경 요청 실패: ' + err.message);
                }
            };
        });

    } catch (err) {

        pending.textContent =
            'AI 요청 실패: ' + err.message;
    }

    box.scrollTop = box.scrollHeight;
});

/* 초기화 */
chatFiles();