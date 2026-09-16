"""디스크 개체(시리얼) 추적 API."""

import logging

from flask import Blueprint, jsonify, request
from flask_login import login_required

from .. import db
from ..models import DiskUnit, StockIn, StockOut
from ..utils.time import fmt
from .common import apply_site_filter, fmt_qty, serialize_unit, user_label

units_bp = Blueprint("units", __name__)
logger = logging.getLogger(__name__)


@units_bp.get("/api/units")
@login_required
def list_units():
    """
    q      = 시리얼/코드/사이트 부분 일치
    status = in_stock | out
    site   = 사이트 부분 일치
    """
    page = max(request.args.get("page", 1, type=int), 1)
    page_size = min(max(request.args.get("page_size", 20, type=int), 1), 200)
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()

    query = DiskUnit.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                DiskUnit.serial.ilike(like),
                DiskUnit.identifier.ilike(like),
                DiskUnit.item_name.ilike(like),
                DiskUnit.site.ilike(like),
            )
        )
    if status in {DiskUnit.STATUS_IN_STOCK, DiskUnit.STATUS_OUT}:
        query = query.filter(DiskUnit.status == status)
    query = apply_site_filter(query, DiskUnit.site, request.args)

    total = query.count()
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)

    rows = (
        query.order_by(DiskUnit.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    in_stock = DiskUnit.query.filter_by(status=DiskUnit.STATUS_IN_STOCK).count()
    out = DiskUnit.query.filter_by(status=DiskUnit.STATUS_OUT).count()

    return jsonify(
        {
            "items": [serialize_unit(u) for u in rows],
            "count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "summary": {"in_stock": in_stock, "out": out},
        }
    )


@units_bp.get("/api/units/<path:serial>")
@login_required
def unit_detail(serial):
    """시리얼 하나의 현재 상태 + 이 시리얼이 포함된 입출고 이력."""
    unit = DiskUnit.query.filter_by(serial=serial).first()
    if unit is None:
        return jsonify({"error": "등록되지 않은 시리얼입니다."}), 404

    like = f"%{serial}%"
    outs = StockOut.query.filter(StockOut.serials.ilike(like)).order_by(StockOut.created_at.desc()).all()
    ins = StockIn.query.filter(StockIn.serials.ilike(like)).order_by(StockIn.created_at.desc()).all()

    history = [
        {
            "type": "out",
            "id": o.id,
            "at": fmt(o.created_at),
            "site": o.site,
            "quantity": fmt_qty(o.quantity),
            "reason": o.reason,
            "ticket_no": o.ticket_no,
            "handler": o.handler,
            "user": user_label(o.user),
            "cancelled": o.is_cancelled,
        }
        for o in outs
    ] + [
        {
            "type": "in",
            "id": i.id,
            "at": fmt(i.created_at),
            "site": i.site,
            "quantity": fmt_qty(i.quantity),
            "reason": i.reason,
            "source": i.source,
            "user": user_label(i.user),
        }
        for i in ins
    ]
    history.sort(key=lambda h: h["at"] or "", reverse=True)

    return jsonify({"unit": serialize_unit(unit), "history": history})
