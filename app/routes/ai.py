import json
import logging
import os
import re

from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import Text, cast, or_

from .. import db
from ..models import InventoryChange, InventoryRow
from ..services.inventory.normalize import normalize_row
from .common import admin_required_api, log_action, serialize_row, sync_group_quantity

ai_bp = Blueprint("ai", __name__)
logger = logging.getLogger(__name__)


def detect_ai_action(message, rows):
    """
    Conservative, deterministic mutation proposal
    for common Korean inventory commands.
    """

    m = message.strip()

    qm = re.search(
        r"(?:수량|재고)\s*(?:을|를)?\s*(?:\D*?)?"
        r"(\d+(?:\.\d+)?)\s*"
        r"(?:개|대|장|ea)?",
        m,
        re.I,
    )

    if not qm:
        return None

    value = qm.group(1)

    target = None

    # -----------------------------------------------------
    # 정확한 identifier/code 우선
    # -----------------------------------------------------

    for r in rows:
        candidates = [r.identifier, r.model, r.item_name]

        if any(c and str(c).lower() in m.lower() for c in candidates):
            target = r
            break

    if not target:
        return None

    quantity_col = "수량"

    for k in target.data_json or {}:
        if re.search(r"수량|재고|qty|quantity", str(k), re.I):
            quantity_col = k
            break

    return {
        "row_id": target.id,
        "field": quantity_col,
        "value": value,
        "reason": f"AI 요청: {message}",
        "description": (
            f"{target.identifier or target.model or target.item_name or '대상 행'}"
            f"의 {quantity_col}을(를) {value}로 변경"
        ),
    }


@ai_bp.post("/chat")
@login_required
def ai_chat():

    payload = request.get_json(silent=True) or {}

    message = str(payload.get("message", "")).strip()

    file_id = payload.get("file_id")

    sheet_id = payload.get("sheet_id")

    if not message:
        return jsonify({"error": "메시지를 입력하세요."}), 400

    key = os.getenv("GEMINI_API_KEY", "").strip()

    if not key:
        return jsonify({"error": ("GEMINI_API_KEY가 .env에 설정되지 않았습니다.")}), 400

    try:
        from google import genai

        client = genai.Client(api_key=key)

        # =================================================
        # 1. 기본 DB 범위
        # =================================================

        base_query = InventoryRow.query.filter_by(is_deleted=False)

        if file_id:
            base_query = base_query.filter_by(excel_file_id=file_id)

        if sheet_id:
            base_query = base_query.filter_by(sheet_id=sheet_id)

        # =================================================
        # 2. 메시지에서 검색어 추출
        # =================================================

        stop_words = {
            "몇개",
            "몇",
            "개수",
            "수량",
            "재고",
            "알려줘",
            "알려",
            "조회",
            "검색",
            "찾아줘",
            "찾아",
            "보여줘",
            "보여",
            "확인",
            "확인해줘",
            "있어",
            "있나요",
            "뭐야",
            "무엇",
            "얼마",
            "얼마나",
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "의",
            "에",
            "에서",
            "으로",
            "로",
            "좀",
            "해주세요",
            "해줘",
        }

        terms = re.findall(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣._:/-]{1,}", message)

        stop_words_lower = {x.lower() for x in stop_words}

        search_terms = [t for t in terms if t.lower() not in stop_words_lower]

        # =================================================
        # 3. DB 검색
        # =================================================

        rows = []

        if search_terms:
            search_terms = sorted(set(search_terms), key=len, reverse=True)

            conditions = []

            for term in search_terms:
                like = f"%{term}%"

                conditions.extend(
                    [
                        InventoryRow.identifier.like(like),
                        InventoryRow.item_name.like(like),
                        InventoryRow.manufacturer.like(like),
                        InventoryRow.model.like(like),
                        InventoryRow.capacity.like(like),
                        InventoryRow.location.like(like),
                        InventoryRow.status.like(like),
                        cast(InventoryRow.data_json, Text).like(like),
                    ]
                )

            rows = (
                base_query.filter(or_(*conditions))
                .order_by(InventoryRow.id.desc())
                .limit(100)
                .all()
            )

        # =================================================
        # 4. 검색 결과 없음
        # =================================================

        if not rows:
            return jsonify(
                {
                    "answer": (
                        f'"{message}"에 해당하는 재고 데이터를 DB에서 찾지 못했습니다.'
                    ),
                    "sources": [],
                    "action": None,
                }
            )

        # =================================================
        # 5. 정확한 identifier 우선
        # =================================================

        exact_rows = []

        for r in rows:
            identifier = str(r.identifier or "").strip()

            for term in search_terms:
                if identifier.lower() == term.lower():
                    exact_rows.append(r)

                    break

        if exact_rows:
            rows = exact_rows

        # =================================================
        # 6. DB 결과를 AI에게 전달
        # =================================================

        context = "\n".join(
            json.dumps(serialize_row(r), ensure_ascii=False, default=str) for r in rows
        )

        # =================================================
        # 7. AI Prompt
        # =================================================

        prompt = f"""
너는 사내 재고관리 시스템의 AI 도우미다.

반드시 아래 DB 조회 결과만 근거로 답변해야 한다.

규칙:
1. DB 조회 결과에 없는 재고 정보는 절대 추측하지 않는다.
2. 수량을 물어보면 DB의 quantity 또는 실제 Excel의 수량/재고 컬럼 값을 사용한다.
3. 품번/Code/identifier가 정확히 일치하는 데이터가 있으면 그것을 최우선으로 사용한다.
4. 여러 행이 검색되면 각각의 데이터를 구분해서 답한다.
5. DB에 데이터가 없으면 없다고 답한다.
6. 존재하지 않는 데이터를 만들어내지 않는다.
7. 사용자가 단순히 몇 개인지 물으면 불필요하게 장황하게 설명하지 말고 숫자를 명확하게 답한다.

사용자 질문:
{message}

DB 조회 결과:
{context}
"""

        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"), contents=prompt
        )

        return jsonify(
            {
                "answer": (resp.text or "응답이 없습니다."),
                "sources": [serialize_row(r) for r in rows[:20]],
                "action": detect_ai_action(message, rows),
            }
        )

    except Exception:
        # Gemini 오류 본문에는 API 키 일부/요청 내용이 섞여 나올 수 있어 로그에만 남긴다.
        logger.exception("AI chat failed | user_id=%s", current_user.id)
        return jsonify(
            {
                "error": "AI 호출 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.",
                "request_id": getattr(g, "request_id", "-"),
            }
        ), 502


@ai_bp.post("/apply")
@admin_required_api
def ai_apply():

    payload = request.get_json(silent=True) or {}

    row_id = payload.get("row_id")

    field = payload.get("field")

    value = payload.get("value")

    reason = payload.get("reason", "AI 대화에 의한 변경")

    if not row_id or not field:
        return jsonify({"error": "변경 대상이 없습니다."}), 400

    row = db.get_or_404(InventoryRow, int(row_id))

    if row.is_deleted:
        return jsonify({"error": "삭제된 행은 수정할 수 없습니다."}), 400

    data = dict(row.data_json or {})

    old = data.get(field)

    data[field] = value

    n = normalize_row(data)

    row.data_json = data
    row.identifier = n.get("identifier")
    row.item_name = n.get("item_name")
    row.manufacturer = n.get("manufacturer")
    row.model = n.get("model")
    row.capacity = n.get("capacity")
    row.quantity = n.get("quantity")
    row.required_quantity = n.get("required_quantity")
    row.location = n.get("location")
    row.status = n.get("status")
    sync_group_quantity(row.group)

    log_action(
        "ai_apply",
        detail=f"{row.identifier or row.id}: {field} {old!r}→{value!r} (AI 제안)",
        target_type="inventory_row",
        target_id=row.id,
    )

    db.session.add(
        InventoryChange(
            inventory_row_id=row.id,
            user_id=current_user.id,
            change_type="ai_update",
            field_name=field,
            old_value=str(old),
            new_value=str(value),
            reason=reason,
            source="ai",
        )
    )

    db.session.commit()

    return jsonify({"ok": True, "item": serialize_row(row)})
