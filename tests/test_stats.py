"""통계: 기간 비교(전월/전년 동월), 코드 추이·예상 소진, 사이트 요약, 시간대 경계."""

from datetime import date, datetime, timedelta

from app import db
from app.models import StockOut, User
from app.utils.time import fmt, local_date_range_utc, utcnow

from .conftest import make_row


def _out(app, created_at, site, code, qty, cancelled=False):
    with app.app_context():
        uid = User.query.filter_by(username="user1").one().id
        db.session.add(
            StockOut(
                user_id=uid, site=site, identifier=code, item_name="disk", quantity=qty,
                created_at=created_at, cancelled_at=(created_at if cancelled else None),
            )
        )
        db.session.commit()


def test_period_compare_mom_and_yoy(user_client, app):
    _out(app, datetime(2026, 9, 10), "S", "C1", 10)
    _out(app, datetime(2026, 8, 10), "S", "C1", 4)
    _out(app, datetime(2025, 9, 10), "S", "C1", 5)   # 전년 동월
    _out(app, datetime(2026, 9, 11), "S", "C1", 99, cancelled=True)  # 취소 건은 제외

    data = user_client.get("/api/stats/outflow/periodic?granularity=month&year=2026").get_json()
    periods = {p["period"]: p for p in data["periods"]}

    assert set(periods) == {"2026-09", "2026-08"}  # 2025 데이터는 비교용으로만
    sep = periods["2026-09"]
    assert sep["total"] == 10
    assert sep["compare"]["mom"] == {"prev": 4, "diff": 6, "pct": 150.0}
    assert sep["compare"]["yoy"] == {"prev": 5, "diff": 5, "pct": 100.0}
    assert periods["2026-08"]["compare"]["mom"] is None  # 7월 데이터 없음


def test_period_compare_yearly(user_client, app):
    _out(app, datetime(2026, 3, 1), "S", "C1", 7)
    _out(app, datetime(2025, 3, 1), "S", "C1", 14)
    data = user_client.get("/api/stats/outflow/periodic?granularity=year").get_json()
    y2026 = data["periods"][0]
    assert y2026["period"] == "2026"
    assert y2026["compare"]["mom"] == {"prev": 14, "diff": -7, "pct": -50.0}
    assert y2026["compare"]["yoy"] is None


def test_code_trend_and_depletion(user_client, app):
    make_row(app, identifier="C1", quantity=6)
    now = utcnow()
    for months_ago, qty in ((0, 2), (1, 2), (2, 2)):
        _out(app, now - timedelta(days=30 * months_ago + 1), "S", "C1", qty)

    codes = user_client.get("/api/stats/codes").get_json()["codes"]
    assert codes[0]["code"] == "C1" and codes[0]["total"] == 6

    data = user_client.get("/api/stats/codes/C1/trend?months=6").get_json()
    assert data["stock"] == 6
    assert data["total"] == 6
    assert len(data["series"]) == 6
    assert data["recent_avg_per_month"] == 2.0
    assert data["recent_months_left"] == 3.0
    assert data["depletion_month"] is not None


def test_code_trend_without_outflow(user_client, app):
    make_row(app, identifier="ZZZ", quantity=3)
    data = user_client.get("/api/stats/codes/ZZZ/trend").get_json()
    assert data["stock"] == 3 and data["months_left"] is None and data["depletion_month"] is None


def test_site_summary(user_client, app):
    make_row(app, identifier="C1", quantity=2, location="서울IDC 3층")
    _out(app, utcnow() - timedelta(days=1), "서울IDC", "C1", 3)
    _out(app, utcnow() - timedelta(days=2), "부산DC", "C1", 9)

    data = user_client.get("/api/sites/서울IDC/summary").get_json()
    assert data["site"] == "서울IDC"
    assert data["total"] == 3
    assert data["by_code"] == [{"code": "C1", "total": 3}]
    assert len(data["recent_out"]) == 1
    assert data["holding"][0]["location"] == "서울IDC 3층"

    assert user_client.get("/sites/서울IDC").status_code == 200


# ---------------------------------------------------------------------------
# 시간대 (B-20)
# ---------------------------------------------------------------------------


def test_fmt_converts_utc_to_kst():
    # 2026-09-16 23:30 UTC = 2026-09-17 08:30 KST
    assert fmt(datetime(2026, 9, 16, 23, 30)) == "2026-09-17 08:30"
    assert fmt(None) is None


def test_local_date_range_utc():
    start, end = local_date_range_utc(date(2026, 9, 17))
    assert start == datetime(2026, 9, 16, 15, 0)
    assert end == datetime(2026, 9, 17, 15, 0)


def test_monthly_grouping_uses_local_timezone(user_client, app):
    """UTC 로는 8월 31일 저녁이지만 KST 로는 9월 1일 새벽인 출고 → 9월로 집계."""
    _out(app, datetime(2026, 8, 31, 20, 0), "S", "C1", 1)
    data = user_client.get("/api/stats/outflow/periodic?granularity=month&year=2026").get_json()
    assert [p["period"] for p in data["periods"]] == ["2026-09"]


def test_date_filter_uses_local_day(user_client, app):
    _out(app, datetime(2026, 8, 31, 20, 0), "S", "C1", 1)  # KST 9/1 05:00
    assert user_client.get("/api/stockout?date=2026-09-01").get_json()["count"] == 1
    assert user_client.get("/api/stockout?date=2026-08-31").get_json()["count"] == 0
    item = user_client.get("/api/stockout").get_json()["items"][0]
    assert item["created_at"] == "2026-09-01 05:00"
    assert item["summary"].startswith("2026.09.01 1ea")
