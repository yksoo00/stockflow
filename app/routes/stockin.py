import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from .. import db
from ..models import DiskUnit, StockIn, User
from ..utils.time import fmt, utcnow
from .common import (
    fmt_qty,
    lock_row,
    log_action,
    parse_serials,
    serial_snapshot,
    set_row_quantity,
    user_label,
)

stockin_bp = Blueprint("stockin", __name__)
logger = logging.getLogger(__name__)


SOURCE_LABEL = {
    "manual": "수동",
    "auto_request": "자동(요청승인)",
    "cancel_out": "출고취소 원복",
}


def _serialize(entry):
    return {
        "id": entry.id,
        "row_id": entry.inventory_row_id,
        "request_id": entry.stock_request_id,
        "identifier": entry.identifier,
        "item_name": entry.item_name,
        "site": entry.site,
        "quantity": entry.quantity,
        "reason": entry.reason,
        "source": entry.source,
        "source_label": SOURCE_LABEL.get(entry.source, entry.source),
        "serials": parse_serials(entry.serials),
        "created_at": fmt(entry.created_at),
        "summary": "{date} {qty}ea {reason}".format(
            date=fmt(entry.created_at, "%Y.%m.%d"),
            qty=fmt_qty(entry.quantity),
            reason=entry.reason or "",
        ),
        "user": user_label(entry.user),
    }


def register_units(row, serials, *, stock_in):
    """
    입고 시리얼을 DiskUnit 으로 등록한다.
    이미 존재하는 시리얼이 'out' 상태면 재입고로 보고 in_stock 으로 되돌리고,
    'in_stock' 이면 중복 입고이므로 ValueError.
    """
    for serial in serials:
        unit = DiskUnit.query.filter_by(serial=serial).first()
        if unit is None:
            unit = DiskUnit(serial=serial)
            db.session.add(unit)
        elif unit.status == DiskUnit.STATUS_IN_STOCK:
            raise ValueError(f"시리얼 {serial} 은(는) 이미 재고 상태입니다.")

        unit.identifier = row.identifier
        unit.item_name = row.item_name
        unit.inventory_row_id = row.id
        unit.status = DiskUnit.STATUS_IN_STOCK
        unit.site = None
        unit.stock_in = stock_in
        unit.stock_out_id = None


def apply_stock_in(
    row,
    quantity,
    *,
    reason,
    source,
    user_id,
    site=None,
    stock_request_id=None,
    serials=None,
):
    """
    InventoryRow.quantity를 실제로 가산하고 StockIn 이력을 한 줄 남기는 공용 로직.
    수동입고(/api/stockin), 입고요청 물품도착(stockrequest.py), 출고취소(stockout.py) 모두 여기를 거친다.
    row 는 lock_row() 로 잠근 상태여야 한다.
    """
    serials = serials or []
    if serials and len(serials) != int(quantity):
        raise ValueError(
            f"시리얼 개수({len(serials)})가 입고 수량({fmt_qty(quantity)})과 다릅니다."
        )

    new_qty = (row.quantity or 0) + quantity
    set_row_quantity(row, new_qty)

    entry = StockIn(
        inventory_row_id=row.id,
        stock_request_id=stock_request_id,
        user_id=user_id,
        identifier=row.identifier,
        item_name=row.item_name,
        site=site,
        quantity=quantity,
        reason=reason,
        source=source,
        serials=serial_snapshot(serials),
        created_at=utcnow(),
    )
    db.session.add(entry)

    if serials:
        register_units(row, serials, stock_in=entry)

    return new_qty, entry


# =========================================================
# 수동입고
# =========================================================
@stockin_bp.post("/api/stockin")
@login_required
def create_stockin():

    payload = request.get_json(silent=True) or {}

    row_id = payload.get("row_id")
    serials = parse_serials(payload.get("serials"))

    try:
        quantity = float(payload.get("quantity"))
    except (TypeError, ValueError):
        quantity = None

    if not row_id:
        return jsonify({"error": "row_id가 필요합니다."}), 400

    if not quantity or quantity <= 0:
        return jsonify({"error": "입고 수량은 0보다 커야 합니다."}), 400

    row = lock_row(row_id)
    if row is None:
        return jsonify({"error": "해당 재고 행이 없거나 삭제되었습니다."}), 404

    try:
        new_qty, entry = apply_stock_in(
            row,
            quantity,
            reason=str(payload.get("reason", "")).strip() or "수동입고",
            source="manual",
            user_id=current_user.id,
            site=str(payload.get("site", "")).strip() or None,
            serials=serials,
        )
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400

    db.session.flush()
    log_action(
        "stockin",
        detail=f"{row.identifier or row.item_name or row.id} {fmt_qty(quantity)}개 입고 (잔여 {fmt_qty(new_qty)})"
        + (f", 시리얼 {len(serials)}건" if serials else ""),
        target_type="stock_in",
        target_id=entry.id,
    )
    db.session.commit()

    logger.info(
        "Manual stock-in recorded | row_id=%s | quantity=%s | user_id=%s",
        row.id,
        quantity,
        current_user.id,
    )

    return jsonify({"ok": True, "item": _serialize(entry), "row_quantity": new_qty})


# =========================================================
# 입고 내역 조회
# =========================================================
@stockin_bp.get("/api/stockin")
@login_required
def list_stockin():

    page = max(request.args.get("page", 1, type=int), 1)
    page_size = min(max(request.args.get("page_size", 10, type=int), 1), 200)
    sort_col = request.args.get("sort", "").strip()
    sort_dir = request.args.get("dir", "desc").strip().lower()
    sort_dir = "asc" if sort_dir == "asc" else "desc"

    q = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    site = request.args.get("site", "").strip()

    query = StockIn.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                StockIn.identifier.ilike(like),
                StockIn.item_name.ilike(like),
                StockIn.site.ilike(like),
                StockIn.reason.ilike(like),
                StockIn.serials.ilike(like),
            )
        )

    if source:
        query = query.filter(StockIn.source == source)

    if site:
        query = query.filter(StockIn.site.ilike(f"%{site}%"))

    total = query.count()
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)

    sortable_columns = {
        "created_at": StockIn.created_at,
        "identifier": StockIn.identifier,
        "item_name": StockIn.item_name,
        "site": StockIn.site,
        "quantity": StockIn.quantity,
        "source": StockIn.source,
    }

    if sort_col == "user":
        query = query.outerjoin(User, StockIn.user_id == User.id)
        column_expr = db.func.coalesce(User.name, User.username)
    else:
        column_expr = sortable_columns.get(sort_col, StockIn.created_at)

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
            "sort": sort_col,
            "dir": sort_dir,
        }
    )


@stockin_bp.get("/stockin")
@login_required
def stockin_page():
    return render_template("pages/stockin/list.html")
