"""
같은 입고요청 '물품도착' / 같은 출고 '취소' 가 동시에 두 번 들어와도 재고가 한 번만 바뀌는지.

메모리 SQLite 는 연결이 하나뿐이라 동시성을 재현할 수 없어서, 파일 SQLite 에 스레드 두 개로 요청을 보낸다.
상태 확인과 수량 반영 사이를 넓히려고 lock_row 에 지연을 넣는다 (예전 코드는 이 사이에서 둘 다 통과했다).
"""

import threading
import time

import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db, limiter
from app.models import InventoryRow, StockIn, User
from app.routes import common, stockout, stockrequest

from .conftest import api, csrf_token_from, login, make_row


@pytest.fixture
def file_app(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-0123456789abcdef",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'race.db'}",
            "WTF_CSRF_ENABLED": True,
        }
    )
    limiter.reset()
    with app.app_context():
        db.create_all()
        db.session.add(
            User(
                username="admin",
                name="관리자",
                role="admin",
                password_hash=generate_password_hash("adminpass123"),
            )
        )
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def _admin(app):
    client = app.test_client()
    assert login(client, "admin", "adminpass123").status_code == 302
    client.csrf = csrf_token_from(client, "/")
    return client


def _slow_lock_row(monkeypatch):
    def slow(row_id):
        time.sleep(0.3)
        return common.lock_row(row_id)

    monkeypatch.setattr(stockrequest, "lock_row", slow)
    monkeypatch.setattr(stockout, "lock_row", slow)


def _fire_twice(clients, path):
    barrier = threading.Barrier(len(clients))
    codes = []

    def worker(client):
        barrier.wait()
        codes.append(api(client, "POST", path).status_code)

    threads = [threading.Thread(target=worker, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return sorted(codes)


def test_concurrent_arrive_adds_stock_once(file_app, monkeypatch):
    row_id = make_row(file_app, quantity=1)
    a, b = _admin(file_app), _admin(file_app)
    rid = api(a, "POST", "/api/stockrequest", row_id=row_id, site="A", quantity=2).get_json()["item"]["id"]
    assert api(a, "POST", f"/api/stockrequest/{rid}/approve").status_code == 200

    _slow_lock_row(monkeypatch)
    codes = _fire_twice([a, b], f"/api/stockrequest/{rid}/arrive")

    assert codes == [200, 400]
    with file_app.app_context():
        assert db.session.get(InventoryRow, row_id).quantity == 3
        assert StockIn.query.filter_by(source="auto_request").count() == 1


def test_concurrent_cancel_restores_stock_once(file_app, monkeypatch):
    row_id = make_row(file_app, quantity=3)
    a, b = _admin(file_app), _admin(file_app)
    out_id = api(a, "POST", "/api/stockout", row_id=row_id, site="A", quantity=2).get_json()["item"]["id"]

    _slow_lock_row(monkeypatch)
    codes = _fire_twice([a, b], f"/api/stockout/{out_id}/cancel")

    assert codes == [200, 400]
    with file_app.app_context():
        assert db.session.get(InventoryRow, row_id).quantity == 3
        assert StockIn.query.filter_by(source="cancel_out").count() == 1
