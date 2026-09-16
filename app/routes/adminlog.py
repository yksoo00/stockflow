import logging
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from .. import db
from ..models import AdminLog, User
from ..utils.time import fmt, local_date_range_utc
from .common import admin_required, admin_required_api

adminlog_bp = Blueprint("adminlog", __name__)
logger = logging.getLogger(__name__)


ACTION_LABEL = {
    # 재고/Excel
    "excel_upload": "Excel 업로드",
    "excel_delete": "Excel 삭제",
    "excel_export": "Excel 수정본 내보내기",
    "row_edit": "재고 수정",
    "row_delete": "재고 행 삭제",
    "column_add": "컬럼 추가",
    "ai_apply": "AI 제안 적용",
    # 출고/입고
    "stockout": "출고",
    "stockout_cancel": "출고 취소",
    "stockin": "입고",
    "stockrequest_create": "입고요청",
    "stockrequest_auto": "입고요청 자동생성",
    "stockrequest_approve": "입고요청 승인",
    "stockrequest_arrive": "물품도착 처리",
    # 계정
    "login": "로그인",
    "logout": "로그아웃",
    "login_inactive": "비활성 계정 로그인 시도",
    "user_create": "계정 생성",
    "user_update": "계정 수정",
    "password_change": "비밀번호 변경",
    "password_reset": "비밀번호 초기화",
    "profile_update": "프로필 수정",
}


def _serialize(entry):
    return {
        "id": entry.id,
        "action": entry.action,
        "action_label": ACTION_LABEL.get(entry.action, entry.action),
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "detail": entry.detail,
        "created_at": fmt(entry.created_at),
        "user": (entry.user.name or entry.user.username) if entry.user else None,
    }


@adminlog_bp.get("/api/adminlog")
@admin_required_api
def list_adminlog():

    page = max(request.args.get("page", 1, type=int), 1)
    page_size = min(max(request.args.get("page_size", 10, type=int), 1), 200)
    sort_col = request.args.get("sort", "").strip()
    sort_dir = request.args.get("dir", "desc").strip().lower()
    sort_dir = "asc" if sort_dir == "asc" else "desc"

    q = request.args.get("q", "").strip()
    action = request.args.get("action", "").strip()
    date = request.args.get("date", "").strip()

    query = AdminLog.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                AdminLog.action.ilike(like),
                AdminLog.detail.ilike(like),
                AdminLog.target_type.ilike(like),
            )
        )

    if action:
        query = query.filter(AdminLog.action == action)

    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
            start, end = local_date_range_utc(day)
            query = query.filter(AdminLog.created_at >= start, AdminLog.created_at < end)
        except ValueError:
            pass

    total = query.count()
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)

    sortable_columns = {
        "created_at": AdminLog.created_at,
        "action": AdminLog.action,
        "target_type": AdminLog.target_type,
    }

    if sort_col == "user":
        query = query.outerjoin(User, AdminLog.user_id == User.id)
        column_expr = db.func.coalesce(User.name, User.username)
    else:
        column_expr = sortable_columns.get(sort_col, AdminLog.created_at)

    order_by_clause = column_expr.asc() if sort_dir == "asc" else column_expr.desc()

    rows = (
        query.order_by(order_by_clause)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return jsonify(
        {
            "items": [_serialize(entry) for entry in rows],
            "count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "actions": [
                {"value": key, "label": label} for key, label in ACTION_LABEL.items()
            ],
        }
    )


@adminlog_bp.get("/adminlog")
@admin_required
def adminlog_page():
    return render_template("pages/adminlog/list.html")
