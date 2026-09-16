"""
대시보드/사이트/디스크 코드 통계 API.

모든 집계는 취소되지 않은 출고(StockOut.cancelled_at IS NULL)만 대상으로 하고,
날짜/월/연 경계는 APP_TIMEZONE(기본 Asia/Seoul) 기준이다 (B-20).
"""

import logging
from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_login import login_required

from .. import db
from ..models import InventoryRow, StockIn, StockOut, StockRequest
from ..utils.time import fmt, local_ts, to_local, utcnow
from .common import fmt_qty, user_label

stats_bp = Blueprint("stats", __name__)
logger = logging.getLogger(__name__)


def _dialect():
    return db.engine.dialect.name


def _active_outflow():
    return StockOut.query.filter(StockOut.cancelled_at.is_(None))


def _code_expr():
    """디스크 코드: 품번(identifier) 우선, 비어 있으면 품명."""
    return db.func.coalesce(
        db.func.nullif(StockOut.identifier, ""), StockOut.item_name, "(코드 없음)"
    )


def _site_expr():
    return db.func.coalesce(db.func.nullif(StockOut.site, ""), "(사이트 미지정)")


def _year_month_exprs():
    ts = local_ts(StockOut.created_at, _dialect())
    year_expr = db.cast(db.func.extract("year", ts), db.Integer)
    month_expr = db.cast(db.func.extract("month", ts), db.Integer)
    return year_expr, month_expr


# ---------------------------------------------------------------------------
# 최근 1년 TOP 10 (사이트 / 디스크)
# ---------------------------------------------------------------------------
@stats_bp.get("/api/stats/outflow")
@login_required
def stats_outflow():
    since = utcnow() - timedelta(days=365)

    base = db.session.query(
        db.func.sum(StockOut.quantity).label("total"),
    ).filter(StockOut.created_at >= since, StockOut.cancelled_at.is_(None))

    site_rows = (
        base.add_columns(StockOut.site.label("label"))
        .filter(StockOut.site.isnot(None))
        .group_by(StockOut.site)
        .order_by(db.desc("total"))
        .limit(10)
        .all()
    )

    item_label = _code_expr()
    item_rows = (
        base.add_columns(item_label.label("label"))
        .group_by(item_label)
        .order_by(db.desc("total"))
        .limit(10)
        .all()
    )

    return jsonify(
        {
            "since": fmt(since, "%Y-%m-%d"),
            "sites": [{"label": r.label, "total": float(r.total or 0)} for r in site_rows],
            "items": [{"label": r.label, "total": float(r.total or 0)} for r in item_rows],
        }
    )


# ---------------------------------------------------------------------------
# 기간(월/년) × 사이트 × 코드 + 전 기간/전년 동기 대비 증감
# ---------------------------------------------------------------------------
def _period_key(row, granularity):
    return f"{row.year:04d}-{row.month:02d}" if granularity == "month" else f"{row.year:04d}"


def _prev_period(period, granularity):
    if granularity == "year":
        return f"{int(period) - 1:04d}"
    y, m = (int(x) for x in period.split("-"))
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def _yoy_period(period, granularity):
    if granularity == "year":
        return None
    y, m = (int(x) for x in period.split("-"))
    return f"{y - 1:04d}-{m:02d}"


def _delta(current, previous):
    if previous is None:
        return None
    diff = current - previous
    pct = (diff / previous * 100.0) if previous else None
    return {"prev": previous, "diff": diff, "pct": pct}


@stats_bp.get("/api/stats/outflow/periodic")
@login_required
def stats_outflow_periodic():
    """
    쿼리스트링:
      granularity = month | year   (기본 month)
      year        = 2026           (month 모드에서만, 기본 올해)
      site        = 사이트명        (선택, 부분 일치)

    응답 periods[*]:
      period, total, sites[{site,total,items[{code,total}]}],
      compare: { mom: {prev,diff,pct} | null, yoy: {...} | null }
        mom = 직전 기간(전월/전년) 대비, yoy = 전년 동월 대비 (월별에서만)
    """
    granularity = request.args.get("granularity", "month").strip().lower()
    if granularity not in {"month", "year"}:
        granularity = "month"

    site_filter = request.args.get("site", "").strip()
    year_expr, month_expr = _year_month_exprs()
    code_expr = _code_expr()
    site_expr = _site_expr()

    group_cols = [year_expr.label("year")]
    if granularity == "month":
        group_cols.append(month_expr.label("month"))

    query = db.session.query(
        *group_cols,
        site_expr.label("site"),
        code_expr.label("code"),
        db.func.sum(StockOut.quantity).label("total"),
    ).filter(StockOut.cancelled_at.is_(None))

    year = None
    if granularity == "month":
        year = request.args.get("year", type=int) or to_local(utcnow()).year
        # 전년 동월 비교를 위해 전년도까지 같이 읽는다.
        query = query.filter(year_expr.in_([year, year - 1]))

    if site_filter:
        query = query.filter(StockOut.site.ilike(f"%{site_filter}%"))

    rows = query.group_by(*group_cols, site_expr, code_expr).all()

    periods = {}
    for row in rows:
        period = _period_key(row, granularity)
        total = float(row.total or 0)
        p = periods.setdefault(period, {"period": period, "total": 0.0, "sites": {}})
        p["total"] += total
        s = p["sites"].setdefault(row.site, {"site": row.site, "total": 0.0, "items": []})
        s["total"] += total
        s["items"].append({"code": row.code, "total": total})

    totals = {k: v["total"] for k, v in periods.items()}

    result = []
    for period in sorted(periods, reverse=True):
        if granularity == "month" and not period.startswith(f"{year:04d}-"):
            continue  # 전년도 데이터는 비교용으로만 쓴다
        p = periods[period]
        sites = sorted(p["sites"].values(), key=lambda s: -s["total"])
        for s in sites:
            s["items"].sort(key=lambda i: -i["total"])

        prev = _prev_period(period, granularity)
        yoy = _yoy_period(period, granularity)
        result.append(
            {
                "period": period,
                "total": p["total"],
                "sites": sites,
                "compare": {
                    "mom": _delta(p["total"], totals.get(prev)) if prev in totals else None,
                    "yoy": _delta(p["total"], totals.get(yoy)) if yoy and yoy in totals else None,
                },
            }
        )

    years = [
        int(y)
        for (y,) in db.session.query(year_expr)
        .filter(StockOut.cancelled_at.is_(None))
        .distinct()
        .order_by(year_expr.desc())
        .all()
        if y is not None
    ]

    return jsonify(
        {"granularity": granularity, "year": year, "years": years, "periods": result}
    )


# ---------------------------------------------------------------------------
# 디스크 코드별 소비 추이 + 예상 소진 시점
# ---------------------------------------------------------------------------
@stats_bp.get("/api/stats/codes")
@login_required
def stats_codes():
    """최근 1년간 출고가 있었던 코드 목록 (많이 나간 순). 코드 선택 드롭다운용."""
    since = utcnow() - timedelta(days=365)
    code_expr = _code_expr()
    rows = (
        db.session.query(code_expr.label("code"), db.func.sum(StockOut.quantity).label("total"))
        .filter(StockOut.created_at >= since, StockOut.cancelled_at.is_(None))
        .group_by(code_expr)
        .order_by(db.desc("total"))
        .limit(50)
        .all()
    )
    return jsonify({"codes": [{"code": r.code, "total": float(r.total or 0)} for r in rows]})


@stats_bp.get("/api/stats/codes/<path:code>/trend")
@login_required
def stats_code_trend(code):
    """
    months=12 (기본) 개월 동안의 월별 출고량 + 현재 재고 + 예상 소진.

    예상 소진: 최근 N개월 평균 월 출고량(0 이면 None) 으로 현재 재고를 나눈 개월 수.
    """
    months = min(max(request.args.get("months", 12, type=int), 3), 36)
    now_local = to_local(utcnow())

    # 기간 시작: (months-1) 개월 전 1일
    start_year, start_month = now_local.year, now_local.month
    for _ in range(months - 1):
        start_month -= 1
        if start_month == 0:
            start_month = 12
            start_year -= 1
    since = utcnow() - timedelta(days=31 * months)  # 넉넉히 읽고 파이썬에서 잘라낸다

    code_expr = _code_expr()
    year_expr, month_expr = _year_month_exprs()

    rows = (
        db.session.query(
            year_expr.label("year"),
            month_expr.label("month"),
            db.func.sum(StockOut.quantity).label("total"),
        )
        .filter(
            StockOut.created_at >= since,
            StockOut.cancelled_at.is_(None),
            code_expr == code,
        )
        .group_by(year_expr, month_expr)
        .all()
    )
    by_month = {f"{r.year:04d}-{r.month:02d}": float(r.total or 0) for r in rows}

    series = []
    y, m = start_year, start_month
    for _ in range(months):
        key = f"{y:04d}-{m:02d}"
        series.append({"month": key, "total": by_month.get(key, 0.0)})
        m += 1
        if m == 13:
            m = 1
            y += 1

    total = sum(p["total"] for p in series)
    avg_per_month = total / months if months else 0.0

    # 현재 재고: 코드가 identifier 또는 item_name 과 일치하는 삭제되지 않은 행의 수량 합
    stock = (
        db.session.query(db.func.coalesce(db.func.sum(InventoryRow.quantity), 0.0))
        .filter(
            InventoryRow.is_deleted == False,  # noqa: E712
            db.or_(InventoryRow.identifier == code, InventoryRow.item_name == code),
        )
        .scalar()
    )
    stock = float(stock or 0)

    months_left = (stock / avg_per_month) if avg_per_month > 0 else None
    depletion = None
    if months_left is not None:
        depletion = fmt(utcnow() + timedelta(days=30.4 * months_left), "%Y-%m")

    # 최근 3개월 평균도 함께 — 최근 추세가 다르면 그쪽이 더 현실적이다.
    recent = series[-3:]
    recent_avg = sum(p["total"] for p in recent) / len(recent) if recent else 0.0
    recent_months_left = (stock / recent_avg) if recent_avg > 0 else None

    return jsonify(
        {
            "code": code,
            "months": months,
            "series": series,
            "total": total,
            "avg_per_month": avg_per_month,
            "recent_avg_per_month": recent_avg,
            "stock": stock,
            "months_left": months_left,
            "recent_months_left": recent_months_left,
            "depletion_month": depletion,
        }
    )


# ---------------------------------------------------------------------------
# 사이트 상세
# ---------------------------------------------------------------------------
@stats_bp.get("/api/sites/<path:site>/summary")
@login_required
def site_summary(site):
    """
    사이트 하나에 대한 요약: 최근 12개월 월별 출고, 코드별 누적, 최근 출고/입고/요청,
    그리고 '위치(location)' 가 이 사이트와 일치하는 보유 재고.
    """
    year_expr, month_expr = _year_month_exprs()
    code_expr = _code_expr()
    since = utcnow() - timedelta(days=365)

    monthly = (
        db.session.query(
            year_expr.label("year"),
            month_expr.label("month"),
            db.func.sum(StockOut.quantity).label("total"),
        )
        .filter(StockOut.site == site, StockOut.cancelled_at.is_(None), StockOut.created_at >= since)
        .group_by(year_expr, month_expr)
        .order_by(year_expr, month_expr)
        .all()
    )

    by_code = (
        db.session.query(code_expr.label("code"), db.func.sum(StockOut.quantity).label("total"))
        .filter(StockOut.site == site, StockOut.cancelled_at.is_(None))
        .group_by(code_expr)
        .order_by(db.desc("total"))
        .limit(30)
        .all()
    )

    recent_out = (
        _active_outflow().filter(StockOut.site == site).order_by(StockOut.created_at.desc()).limit(20).all()
    )
    recent_in = StockIn.query.filter(StockIn.site == site).order_by(StockIn.created_at.desc()).limit(20).all()
    open_requests = (
        StockRequest.query.filter(StockRequest.site == site, StockRequest.status != "arrived")
        .order_by(StockRequest.created_at.desc())
        .limit(20)
        .all()
    )

    holding = (
        InventoryRow.query.filter(
            InventoryRow.is_deleted == False,  # noqa: E712
            InventoryRow.location.ilike(f"%{site}%"),
        )
        .order_by(InventoryRow.quantity.asc())
        .limit(100)
        .all()
    )

    all_time_total = (
        db.session.query(db.func.coalesce(db.func.sum(StockOut.quantity), 0.0))
        .filter(StockOut.site == site, StockOut.cancelled_at.is_(None))
        .scalar()
    )

    return jsonify(
        {
            "site": site,
            "total": float(all_time_total or 0),
            "monthly": [
                {"month": f"{r.year:04d}-{r.month:02d}", "total": float(r.total or 0)} for r in monthly
            ],
            "by_code": [{"code": r.code, "total": float(r.total or 0)} for r in by_code],
            "recent_out": [
                {
                    "id": o.id,
                    "created_at": fmt(o.created_at),
                    "code": o.identifier or o.item_name,
                    "quantity": fmt_qty(o.quantity),
                    "reason": o.reason,
                    "ticket_no": o.ticket_no,
                    "handler": o.handler,
                    "user": user_label(o.user),
                }
                for o in recent_out
            ],
            "recent_in": [
                {
                    "id": i.id,
                    "created_at": fmt(i.created_at),
                    "code": i.identifier or i.item_name,
                    "quantity": fmt_qty(i.quantity),
                    "source": i.source,
                    "user": user_label(i.user),
                }
                for i in recent_in
            ],
            "open_requests": [
                {
                    "id": r.id,
                    "created_at": fmt(r.created_at),
                    "code": r.identifier or r.item_name,
                    "quantity": fmt_qty(r.quantity),
                    "status": r.status,
                    "requested_by": user_label(r.requested_by),
                }
                for r in open_requests
            ],
            "holding": [
                {
                    "row_id": h.id,
                    "file_id": h.excel_file_id,
                    "code": h.identifier or h.item_name,
                    "capacity": h.capacity,
                    "quantity": h.quantity,
                    "location": h.location,
                }
                for h in holding
            ],
        }
    )
