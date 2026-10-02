"""출고/입고/취소/입고요청 흐름 + 시리얼 추적 + 활동 로그."""

from app import db
from app.models import (
    AdminLog,
    DiskUnit,
    InventoryGroup,
    InventoryRow,
    StockIn,
    StockOut,
    StockRequest,
)

from .conftest import api, make_row


def _row(app, row_id):
    with app.app_context():
        return db.session.get(InventoryRow, row_id)


def _actions(app):
    with app.app_context():
        return [a.action for a in AdminLog.query.order_by(AdminLog.id).all()]


# ---------------------------------------------------------------------------
# 출고
# ---------------------------------------------------------------------------


def test_stockout_decrements_and_logs(user_client, app):
    row_id = make_row(app, quantity=5)

    resp = api(
        user_client, "POST", "/api/stockout",
        row_id=row_id, site="서울IDC", quantity=2, reason="장애처리",
        ticket_no="INC-100", handler="김담당",
    )
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["row_quantity"] == 3
    assert data["auto_request_created"] is False
    assert data["item"]["ticket_no"] == "INC-100"
    assert data["item"]["handler"] == "김담당"

    row = _row(app, row_id)
    assert row.quantity == 3
    assert row.data_json["수량"] == 3  # 원본 셀 값도 같이 줄어야 export 가 맞는다
    with app.app_context():
        assert db.session.get(InventoryGroup, row.inventory_group_id).quantity == 3

    assert "stockout" in _actions(app)


def test_stockout_more_than_stock_is_rejected(user_client, app):
    row_id = make_row(app, quantity=1)
    resp = api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=2)
    assert resp.status_code == 400
    assert _row(app, row_id).quantity == 1


def test_stockout_on_deleted_row_is_404(user_client, app):
    row_id = make_row(app, quantity=5)
    with app.app_context():
        db.session.get(InventoryRow, row_id).is_deleted = True
        db.session.commit()
    resp = api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1)
    assert resp.status_code == 404


def test_stockout_to_low_stock_creates_auto_request(user_client, app):
    row_id = make_row(app, quantity=2)
    resp = api(user_client, "POST", "/api/stockout", row_id=row_id, site="부산DC", quantity=2)
    assert resp.get_json()["auto_request_created"] is True

    with app.app_context():
        req = StockRequest.query.filter_by(source="auto").one()
        assert req.status == "requested"
        assert req.quantity == 2  # 0개 남았으니 임계값(1)+1 = 2개 요청
        assert req.site == "부산DC"
    assert "stockrequest_auto" in _actions(app)


def test_stockout_with_serials_tracks_units(user_client, app):
    row_id = make_row(app, quantity=3)
    resp = api(
        user_client, "POST", "/api/stockout",
        row_id=row_id, site="서울IDC", quantity=2, serials="SN-A\nSN-B",
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["item"]["serials"] == ["SN-A", "SN-B"]

    with app.app_context():
        units = {u.serial: u for u in DiskUnit.query.all()}
        assert set(units) == {"SN-A", "SN-B"}
        assert all(u.status == "out" and u.site == "서울IDC" for u in units.values())


def test_stockout_serial_count_mismatch(user_client, app):
    row_id = make_row(app, quantity=3)
    resp = api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=2, serials="SN-1")
    assert resp.status_code == 400
    assert "시리얼 개수" in resp.get_json()["error"]


def test_stockout_serial_already_out_is_rejected(user_client, app):
    row_id = make_row(app, quantity=5)
    api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1, serials="SN-DUP")
    resp = api(user_client, "POST", "/api/stockout", row_id=row_id, site="B", quantity=1, serials="SN-DUP")
    assert resp.status_code == 400
    assert "이미 출고" in resp.get_json()["error"]
    assert _row(app, row_id).quantity == 4  # 두 번째 출고는 롤백됨


# ---------------------------------------------------------------------------
# 출고 취소
# ---------------------------------------------------------------------------


def test_cancel_restores_quantity_units_and_logs(user_client, app):
    row_id = make_row(app, quantity=3)
    out = api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=2, serials="S1,S2").get_json()

    resp = api(user_client, "POST", f"/api/stockout/{out['item']['id']}/cancel", reason="잘못 입력")
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["row_quantity"] == 3
    assert resp.get_json()["item"]["cancelled"] is True

    with app.app_context():
        assert db.session.get(InventoryRow, row_id).quantity == 3
        assert all(u.status == "in_stock" and u.site is None for u in DiskUnit.query.all())
        restore = StockIn.query.filter_by(source="cancel_out").one()
        assert restore.quantity == 2
        assert StockOut.query.one().cancel_reason == "잘못 입력"
    assert "stockout_cancel" in _actions(app)


def test_cancel_twice_is_rejected(user_client, app):
    row_id = make_row(app, quantity=3)
    out = api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1).get_json()
    api(user_client, "POST", f"/api/stockout/{out['item']['id']}/cancel")
    resp = api(user_client, "POST", f"/api/stockout/{out['item']['id']}/cancel")
    assert resp.status_code == 400


def test_cancel_on_deleted_row_stays_uncancelled(user_client, app):
    """원본 행이 없어 취소에 실패하면 취소 선점(claim)도 되돌려져야 한다."""
    row_id = make_row(app, quantity=3)
    out_id = api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1).get_json()["item"]["id"]
    with app.app_context():
        db.session.get(InventoryRow, row_id).is_deleted = True
        db.session.commit()

    assert api(user_client, "POST", f"/api/stockout/{out_id}/cancel").status_code == 400
    with app.app_context():
        assert db.session.get(StockOut, out_id).cancelled_at is None


def test_cancel_by_other_user_is_forbidden(app, client):
    """일반 사용자는 본인 출고만 취소할 수 있다. (관리자가 만든 출고를 user1 이 취소 시도)"""
    from .conftest import csrf_token_from, login

    row_id = make_row(app, quantity=3)

    login(client, "admin", "adminpass123")
    client.csrf = csrf_token_from(client, "/")
    out = api(client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1).get_json()
    client.post("/logout", data={"csrf_token": client.csrf})

    login(client, "user1", "userpass123")
    client.csrf = csrf_token_from(client, "/")
    resp = api(client, "POST", f"/api/stockout/{out['item']['id']}/cancel")
    assert resp.status_code == 403


def test_cancelled_outflow_excluded_from_stats(user_client, app):
    row_id = make_row(app, quantity=5)
    out = api(user_client, "POST", "/api/stockout", row_id=row_id, site="X", quantity=3).get_json()
    api(user_client, "POST", f"/api/stockout/{out['item']['id']}/cancel")

    data = user_client.get("/api/stats/outflow/periodic?granularity=year").get_json()
    assert data["periods"] == []

    listed = user_client.get("/api/stockout?include_cancelled=0").get_json()
    assert listed["count"] == 0
    listed_all = user_client.get("/api/stockout").get_json()
    assert listed_all["count"] == 1 and listed_all["items"][0]["cancelled"] is True


# ---------------------------------------------------------------------------
# 입고
# ---------------------------------------------------------------------------


def test_stockin_with_serials(user_client, app):
    row_id = make_row(app, quantity=1)
    resp = api(user_client, "POST", "/api/stockin", row_id=row_id, quantity=2, serials="N1\nN2", reason="구매")
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["row_quantity"] == 3

    with app.app_context():
        assert {u.serial for u in DiskUnit.query.filter_by(status="in_stock")} == {"N1", "N2"}
        entry = StockIn.query.one()
        assert entry.reason == "구매" and entry.source == "manual"
    assert "stockin" in _actions(app)


def test_stockin_duplicate_in_stock_serial_is_rejected(user_client, app):
    row_id = make_row(app, quantity=1)
    api(user_client, "POST", "/api/stockin", row_id=row_id, quantity=1, serials="SAME")
    resp = api(user_client, "POST", "/api/stockin", row_id=row_id, quantity=1, serials="SAME")
    assert resp.status_code == 400
    assert _row(app, row_id).quantity == 2


def test_serial_roundtrip_in_then_out_then_lookup(user_client, app):
    row_id = make_row(app, quantity=0)
    api(user_client, "POST", "/api/stockin", row_id=row_id, quantity=1, serials="RT-1")
    api(user_client, "POST", "/api/stockout", row_id=row_id, site="대전DC", quantity=1, serials="RT-1")

    listing = user_client.get("/api/units?status=out").get_json()
    assert listing["count"] == 1 and listing["items"][0]["site"] == "대전DC"

    detail = user_client.get("/api/units/RT-1").get_json()
    assert detail["unit"]["status"] == "out"
    assert [h["type"] for h in detail["history"]] == ["out", "in"]


# ---------------------------------------------------------------------------
# 입고요청 승인/도착 (+ 시리얼)
# ---------------------------------------------------------------------------


def test_request_approve_arrive_flow_with_logs(admin_client, app):
    row_id = make_row(app, quantity=1)
    created = api(admin_client, "POST", "/api/stockrequest", row_id=row_id, site="서울IDC", quantity=2, reason="보충").get_json()
    rid = created["item"]["id"]

    approved = api(admin_client, "POST", f"/api/stockrequest/{rid}/approve").get_json()
    assert approved["item"]["status"] == "approved"
    assert approved["pending"]["count"] == 0

    arrived = api(admin_client, "POST", f"/api/stockrequest/{rid}/arrive", serials="A1\nA2").get_json()
    assert arrived["item"]["status"] == "arrived"
    assert arrived["row_quantity"] == 3

    with app.app_context():
        assert DiskUnit.query.filter_by(status="in_stock").count() == 2
        stock_in = StockIn.query.filter_by(source="auto_request").one()
        assert stock_in.stock_request_id == rid

    actions = _actions(app)
    for expected in ("stockrequest_create", "stockrequest_approve", "stockrequest_arrive"):
        assert expected in actions


def test_arrive_requires_approved(admin_client, app):
    row_id = make_row(app, quantity=1)
    rid = api(admin_client, "POST", "/api/stockrequest", row_id=row_id, site="A", quantity=1).get_json()["item"]["id"]
    assert api(admin_client, "POST", f"/api/stockrequest/{rid}/arrive").status_code == 400


def test_stale_request_flagged(admin_client, app):
    from datetime import timedelta

    from app.utils.time import utcnow

    row_id = make_row(app, quantity=1)
    api(admin_client, "POST", "/api/stockrequest", row_id=row_id, site="A", quantity=1)
    with app.app_context():
        req = StockRequest.query.one()
        req.created_at = utcnow() - timedelta(days=5)
        db.session.commit()

    summary = admin_client.get("/api/stockrequest/pending-count").get_json()
    assert summary == {"count": 1, "stale": 1, "stale_days": 3}

    item = admin_client.get("/api/stockrequest").get_json()["items"][0]
    assert item["stale"] is True and item["waiting_days"] == 5


# ---------------------------------------------------------------------------
# 활동 로그 페이지/목록에 사용자 작업이 보이는지
# ---------------------------------------------------------------------------


def test_activity_log_api_includes_stockout(admin_client, app):
    row_id = make_row(app, quantity=5)
    api(admin_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1)
    data = admin_client.get("/api/adminlog?action=stockout").get_json()
    assert data["count"] == 1
    assert data["items"][0]["action_label"] == "출고"
    assert "A" in data["items"][0]["detail"]
