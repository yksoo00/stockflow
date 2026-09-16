"""대시보드 기간별 출고 통계 API 와 사이드바 미승인 배지."""

from datetime import datetime

from app import db
from app.models import StockOut, StockRequest, User


def _seed_stockouts(app):
    with app.app_context():
        uid = User.query.filter_by(username="user1").one().id
        rows = [
            # (created_at, site, identifier, item_name, qty)
            (datetime(2026, 9, 3), "서울IDC", "ST4000NM0035", "4TB SAS", 3),
            (datetime(2026, 9, 10), "서울IDC", "ST4000NM0035", "4TB SAS", 2),
            (datetime(2026, 9, 12), "서울IDC", "3285194-C", "8TB SATA", 1),
            (datetime(2026, 9, 20), "부산DC", "3285194-C", "8TB SATA", 4),
            (datetime(2026, 8, 5), "부산DC", "", "품번없는디스크", 1),
            (datetime(2025, 12, 31), "대전DC", "ST4000NM0035", "4TB SAS", 7),
        ]
        for created_at, site, ident, name, qty in rows:
            db.session.add(
                StockOut(
                    user_id=uid,
                    site=site,
                    identifier=ident,
                    item_name=name,
                    quantity=qty,
                    created_at=created_at,
                )
            )
        db.session.commit()


def test_periodic_month_groups_by_site_and_code(user_client, app):
    _seed_stockouts(app)

    data = user_client.get("/api/stats/outflow/periodic?granularity=month&year=2026").get_json()

    assert data["granularity"] == "month"
    assert data["year"] == 2026
    assert data["years"] == [2026, 2025]

    periods = {p["period"]: p for p in data["periods"]}
    assert list(periods) == ["2026-09", "2026-08"]  # 최신 먼저

    sep = periods["2026-09"]
    assert sep["total"] == 10
    # 출고량 많은 사이트가 먼저
    assert [s["site"] for s in sep["sites"]] == ["서울IDC", "부산DC"]

    seoul = sep["sites"][0]
    assert seoul["total"] == 6
    assert seoul["items"] == [
        {"code": "ST4000NM0035", "total": 5},  # 3 + 2 합산
        {"code": "3285194-C", "total": 1},
    ]

    # 품번이 비어 있으면 품명으로 대체
    aug = periods["2026-08"]
    assert aug["sites"][0]["items"][0]["code"] == "품번없는디스크"


def test_periodic_year_ignores_year_filter(user_client, app):
    _seed_stockouts(app)

    data = user_client.get("/api/stats/outflow/periodic?granularity=year").get_json()

    assert data["year"] is None
    assert [p["period"] for p in data["periods"]] == ["2026", "2025"]
    assert data["periods"][0]["total"] == 11
    assert data["periods"][1]["sites"][0]["site"] == "대전DC"


def test_periodic_site_filter(user_client, app):
    _seed_stockouts(app)

    data = user_client.get("/api/stats/outflow/periodic?granularity=year&site=부산").get_json()

    sites = {s["site"] for p in data["periods"] for s in p["sites"]}
    assert sites == {"부산DC"}


def test_periodic_invalid_granularity_falls_back_to_month(user_client):
    data = user_client.get("/api/stats/outflow/periodic?granularity=weird").get_json()
    assert data["granularity"] == "month"


# ---------------------------------------------------------------------------
# 미승인 입고요청 배지
# ---------------------------------------------------------------------------


def _seed_requests(app, requested=2, approved=1):
    with app.app_context():
        uid = User.query.filter_by(username="user1").one().id
        for _ in range(requested):
            db.session.add(
                StockRequest(identifier="X", item_name="x", site="A", quantity=1,
                             status="requested", requested_by_id=uid)
            )
        for _ in range(approved):
            db.session.add(
                StockRequest(identifier="Y", item_name="y", site="A", quantity=1,
                             status="approved", requested_by_id=uid)
            )
        db.session.commit()


def _badge(html):
    start = html.index('id="pendingBadge"')
    return html[start : html.index('</span>', start)]


def test_badge_hidden_when_nothing_pending(admin_client):
    html = admin_client.get("/").get_data(as_text=True)
    assert ' hidden' in _badge(html)


def test_badge_shows_pending_count_for_admin(admin_client, app):
    _seed_requests(app, requested=2, approved=1)
    html = admin_client.get("/").get_data(as_text=True)
    badge = _badge(html)
    assert ' hidden' not in badge
    assert badge.endswith('>2')


def test_badge_not_shown_to_regular_user(user_client, app):
    _seed_requests(app, requested=3)
    html = user_client.get("/").get_data(as_text=True)
    assert ' hidden' in _badge(html)


def test_pending_count_api(admin_client, app):
    _seed_requests(app, requested=3)
    data = admin_client.get("/api/stockrequest/pending-count").get_json()
    assert data["count"] == 3
    assert data["stale"] == 0  # 방금 만든 요청은 지연 아님
    assert data["stale_days"] == 3


def test_pending_count_api_is_admin_only(user_client):
    assert user_client.get("/api/stockrequest/pending-count").status_code == 403
