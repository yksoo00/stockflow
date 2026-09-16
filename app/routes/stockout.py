import logging
from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from .. import db
from ..models import DiskUnit, StockOut, StockRequest, User
from ..services.notify import mail
from ..utils.time import fmt, local_date_range_utc, utcnow
from .common import (
    apply_site_filter,
    fmt_qty,
    lock_row,
    log_action,
    low_stock_threshold,
    parse_serials,
    serial_snapshot,
    set_row_quantity,
    user_label,
)
from .stockin import apply_stock_in

stockout_bp = Blueprint("stockout", __name__)
logger = logging.getLogger(__name__)


def _serialize(entry):
    return {
        "id": entry.id,
        "row_id": entry.inventory_row_id,
        "identifier": entry.identifier,
        "item_name": entry.item_name,
        "site": entry.site,
        "quantity": entry.quantity,
        "reason": entry.reason,
        "ticket_no": entry.ticket_no,
        "handler": entry.handler,
        "serials": parse_serials(entry.serials),
        "created_at": fmt(entry.created_at),
        # "2026.09.09 1ea 장애처리" 형식의 요약 한 줄
        "summary": "{date} {qty}ea {reason}".format(
            date=fmt(entry.created_at, "%Y.%m.%d"),
            qty=fmt_qty(entry.quantity),
            reason=entry.reason or "",
        ),
        "user": user_label(entry.user),
        "user_id": entry.user_id,
        "cancelled": entry.is_cancelled,
        "cancelled_at": fmt(entry.cancelled_at),
        "cancelled_by": user_label(entry.cancelled_by),
        "cancel_reason": entry.cancel_reason,
    }


def _take_units(row, serials, *, stock_out):
    """출고 시리얼을 DiskUnit 에서 'out' 으로 표시. 재고 상태가 아니면 ValueError."""
    for serial in serials:
        unit = DiskUnit.query.filter_by(serial=serial).first()
        if unit is None:
            # 입고 때 시리얼을 안 적었던 디스크일 수 있으니, 출고 시점에 등록하며 바로 out 처리한다.
            unit = DiskUnit(
                serial=serial,
                identifier=row.identifier,
                item_name=row.item_name,
                inventory_row_id=row.id,
            )
            db.session.add(unit)
        elif unit.status != DiskUnit.STATUS_IN_STOCK:
            raise ValueError(
                f"시리얼 {serial} 은(는) 이미 출고 상태입니다 (사이트: {unit.site or '-'})."
            )

        unit.status = DiskUnit.STATUS_OUT
        unit.site = stock_out.site
        unit.stock_out = stock_out


@stockout_bp.post("/api/stockout")
@login_required
def create_stockout():

    payload = request.get_json(silent=True) or {}

    row_id = payload.get("row_id")
    site = str(payload.get("site", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    ticket_no = str(payload.get("ticket_no", "")).strip() or None
    handler = str(payload.get("handler", "")).strip() or None
    serials = parse_serials(payload.get("serials"))

    try:
        quantity = float(payload.get("quantity"))
    except (TypeError, ValueError):
        quantity = None

    if not row_id:
        return jsonify({"error": "row_id가 필요합니다."}), 400

    if not site:
        return jsonify({"error": "출고할 사이트를 입력하세요."}), 400

    if not quantity or quantity <= 0:
        return jsonify({"error": "출고 수량은 0보다 커야 합니다."}), 400

    if serials and len(serials) != int(quantity):
        return jsonify(
            {"error": f"시리얼 개수({len(serials)})가 출고 수량({fmt_qty(quantity)})과 다릅니다."}
        ), 400

    # 행 잠금 (동시 출고로 음수 재고가 되는 것을 막는다)
    row = lock_row(row_id)
    if row is None:
        return jsonify({"error": "해당 재고 행이 없거나 삭제되었습니다."}), 404

    current_qty = row.quantity or 0

    if quantity > current_qty:
        db.session.rollback()
        return jsonify(
            {"error": f"현재 재고({fmt_qty(current_qty)})보다 많은 수량은 출고할 수 없습니다."}
        ), 400

    # 1) 수량 차감 (data_json/정규화 필드/그룹 합계까지)
    new_qty = current_qty - quantity
    set_row_quantity(row, new_qty)

    # 2) 출고 이력
    entry = StockOut(
        inventory_row_id=row.id,
        user_id=current_user.id,
        identifier=row.identifier,
        item_name=row.item_name,
        site=site,
        quantity=quantity,
        reason=reason or None,
        ticket_no=ticket_no,
        handler=handler,
        serials=serial_snapshot(serials),
        created_at=utcnow(),
    )
    db.session.add(entry)

    # 3) 시리얼 개체 추적
    if serials:
        try:
            _take_units(row, serials, stock_out=entry)
        except ValueError as exc:
            db.session.rollback()
            return jsonify({"error": str(exc)}), 400

    # 4) 자동 입고요청 — 출고 후 재고가 임계값 이하로 떨어지면 매번 새 건으로 생성.
    #    요청수량 = (임계값+1) - 현재수량  →  기본 임계값 1 이면 1개 남았을 때 1개, 0개면 2개
    threshold = low_stock_threshold()
    auto_request_created = new_qty <= threshold
    auto_request = None

    if auto_request_created:
        auto_request = StockRequest(
            inventory_row_id=row.id,
            identifier=row.identifier,
            item_name=row.item_name,
            site=site,
            quantity=max((threshold + 1) - new_qty, 1),
            reason=f"출고 후 재고 {fmt_qty(new_qty)}개 — 자동 생성된 입고요청",
            source="auto",
            status="requested",
            requested_by_id=current_user.id,
        )
        db.session.add(auto_request)

    db.session.flush()

    detail = f"{row.identifier or row.item_name or row.id} {fmt_qty(quantity)}개 → {site} (잔여 {fmt_qty(new_qty)})"
    if reason:
        detail += f", 사유: {reason}"
    if ticket_no:
        detail += f", 티켓: {ticket_no}"
    if handler:
        detail += f", 담당: {handler}"
    if serials:
        detail += f", 시리얼 {len(serials)}건"
    log_action("stockout", detail=detail, target_type="stock_out", target_id=entry.id)

    if auto_request is not None:
        log_action(
            "stockrequest_auto",
            detail=f"{row.identifier or row.item_name} {fmt_qty(auto_request.quantity)}개 입고요청 자동 생성 (#{auto_request.id})",
            target_type="stock_request",
            target_id=auto_request.id,
        )

    db.session.commit()

    logger.info(
        "Stock-out recorded | row_id=%s | site=%s | quantity=%s | user_id=%s | auto_request=%s",
        row.id,
        site,
        quantity,
        current_user.id,
        auto_request.id if auto_request else None,
    )

    # 5) 알림 (커밋 이후, 실패해도 요청은 성공)
    try:
        if auto_request is not None:
            mail.notify_stock_request_created(auto_request, current_user)
            mail.notify_low_stock(row, new_qty, site)
    except Exception:
        logger.exception("Stock-out notification failed | stock_out_id=%s", entry.id)

    return jsonify(
        {
            "ok": True,
            "item": _serialize(entry),
            "row_quantity": new_qty,
            "auto_request_created": auto_request_created,
        }
    )


# =========================================================
# 출고 취소 / 반납 — 수량 원복. 관리자 또는 본인이 처리한 출고만.
# =========================================================
@stockout_bp.post("/api/stockout/<int:stockout_id>/cancel")
@login_required
def cancel_stockout(stockout_id):

    payload = request.get_json(silent=True) or {}
    cancel_reason = str(payload.get("reason", "")).strip() or None

    entry = db.get_or_404(StockOut, stockout_id)

    if entry.is_cancelled:
        return jsonify({"error": "이미 취소된 출고입니다."}), 400

    if current_user.role != "admin" and entry.user_id != current_user.id:
        return jsonify({"error": "본인이 처리한 출고만 취소할 수 있습니다."}), 403

    row = lock_row(entry.inventory_row_id) if entry.inventory_row_id else None
    if row is None:
        return jsonify(
            {"error": "원본 재고 행이 삭제되어 수량을 되돌릴 수 없습니다. 관리자에게 문의하세요."}
        ), 400

    serials = parse_serials(entry.serials)

    # 수량 원복 = 입고 이력(cancel_out)으로 남겨 감사 추적이 가능하게 한다.
    # 시리얼은 apply_stock_in 의 개수 검증을 거치지 않고 여기서 직접 되돌린다.
    new_qty, stock_in = apply_stock_in(
        row,
        entry.quantity,
        reason=f"출고 #{entry.id} 취소 원복" + (f" — {cancel_reason}" if cancel_reason else ""),
        source="cancel_out",
        user_id=current_user.id,
        site=entry.site,
    )
    stock_in.serials = entry.serials

    for unit in DiskUnit.query.filter_by(stock_out_id=entry.id).all():
        unit.status = DiskUnit.STATUS_IN_STOCK
        unit.site = None
        unit.stock_out_id = None
        unit.stock_in = stock_in

    entry.cancelled_at = utcnow()
    entry.cancelled_by_id = current_user.id
    entry.cancel_reason = cancel_reason

    db.session.flush()
    log_action(
        "stockout_cancel",
        detail=f"출고 #{entry.id} 취소: {entry.identifier or entry.item_name} {fmt_qty(entry.quantity)}개 원복 (잔여 {fmt_qty(new_qty)})"
        + (f", 사유: {cancel_reason}" if cancel_reason else "")
        + (f", 시리얼 {len(serials)}건" if serials else ""),
        target_type="stock_out",
        target_id=entry.id,
    )
    db.session.commit()

    logger.info(
        "Stock-out cancelled | stock_out_id=%s | row_id=%s | quantity=%s | user_id=%s",
        entry.id,
        row.id,
        entry.quantity,
        current_user.id,
    )

    return jsonify({"ok": True, "item": _serialize(entry), "row_quantity": new_qty})


@stockout_bp.get("/api/stockout")
@login_required
def list_stockout():

    page = max(request.args.get("page", 1, type=int), 1)
    page_size = min(max(request.args.get("page_size", 10, type=int), 1), 200)
    sort_col = request.args.get("sort", "").strip()
    sort_dir = request.args.get("dir", "desc").strip().lower()
    sort_dir = "asc" if sort_dir == "asc" else "desc"

    q = request.args.get("q", "").strip()
    date = request.args.get("date", "").strip()
    include_cancelled = request.args.get("include_cancelled", "1") != "0"

    query = StockOut.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                StockOut.identifier.ilike(like),
                StockOut.item_name.ilike(like),
                StockOut.site.ilike(like),
                StockOut.reason.ilike(like),
                StockOut.ticket_no.ilike(like),
                StockOut.handler.ilike(like),
                StockOut.serials.ilike(like),
            )
        )

    query = apply_site_filter(query, StockOut.site, request.args)

    if not include_cancelled:
        query = query.filter(StockOut.cancelled_at.is_(None))

    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
            start, end = local_date_range_utc(day)
            query = query.filter(StockOut.created_at >= start, StockOut.created_at < end)
        except ValueError:
            pass

    total = query.count()
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)

    sortable_columns = {
        "created_at": StockOut.created_at,
        "identifier": StockOut.identifier,
        "item_name": StockOut.item_name,
        "site": StockOut.site,
        "quantity": StockOut.quantity,
        "reason": StockOut.reason,
        "ticket_no": StockOut.ticket_no,
        "handler": StockOut.handler,
    }

    if sort_col == "user":
        query = query.outerjoin(User, StockOut.user_id == User.id)
        column_expr = db.func.coalesce(User.name, User.username)
    else:
        column_expr = sortable_columns.get(sort_col, StockOut.created_at)

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


@stockout_bp.get("/stockout")
@login_required
def stockout_page():
    return render_template("pages/stockout/list.html")
