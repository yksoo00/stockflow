"""
공용 pytest fixture.

MySQL 없이 돌아가도록 SQLite 메모리 DB로 앱을 띄운다.
(MySQL 전용 문법을 쓰는 쿼리는 여기서 검증되지 않으므로 통합 테스트는 별도.)
"""

import os

import pytest
from werkzeug.security import generate_password_hash

# create_app() 이 import 시점에 .env 를 읽더라도 테스트 설정이 우선한다.
os.environ.setdefault("LOG_CONSOLE", "0")

from app import create_app, db, limiter  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture
def app(tmp_path):
    os.environ["LOG_DIR"] = str(tmp_path / "logs")
    os.environ["UPLOAD_DIR"] = str(tmp_path / "uploads")

    app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-0123456789abcdef",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            # CSRF 는 기본으로 켜둔 채 테스트한다. 끄고 싶은 테스트는 client_nocsrf 를 쓴다.
            "WTF_CSRF_ENABLED": True,
            "RATELIMIT_ENABLED": True,
        }
    )

    # limiter 는 모듈 전역이라 메모리 저장소가 테스트 간에 공유된다. 매 테스트 초기화.
    limiter.reset()

    # 주의: 앱 컨텍스트를 테스트 내내 열어둔 채 yield 하면 요청들이 그 컨텍스트(g)를 공유해
    # Flask-Login 의 current_user 캐시가 클라이언트 사이에 새어 나간다. 준비/정리만 감싼다.
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
        db.session.add(
            User(
                username="user1",
                name="사용자",
                role="user",
                password_hash=generate_password_hash("userpass123"),
            )
        )
        db.session.commit()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_row(app, identifier="ST4000NM0035", quantity=5, capacity="4TB", location=None, extra=None):
    """
    테스트용 재고 행 하나 (ExcelFile/ExcelSheet/InventoryGroup 포함) 를 만들고 row_id 를 돌려준다.
    data_json 에는 '수량' 컬럼이 들어가므로 set_row_quantity 의 data_json 동기화도 검증된다.
    """
    from app.models import ExcelFile, ExcelSheet, InventoryGroup, InventoryRow, SheetColumn

    with app.app_context():
        ef = ExcelFile.query.first()
        if ef is None:
            ef = ExcelFile(
                original_filename="test.xlsx",
                stored_filename="x_test.xlsx",
                file_path="/nonexistent/x_test.xlsx",
                file_hash="deadbeef",
                processing_status="completed",
            )
            db.session.add(ef)
            db.session.flush()
            sheet = ExcelSheet(excel_file_id=ef.id, sheet_name="Sheet1", sheet_order=0)
            db.session.add(sheet)
            db.session.flush()
            for i, name in enumerate(["Code", "품명", "용량", "수량", "위치"], 1):
                db.session.add(SheetColumn(sheet_id=sheet.id, column_index=i, original_name=name))
        else:
            sheet = ExcelSheet.query.filter_by(excel_file_id=ef.id).first()

        group = InventoryGroup(group_key=f"key-{identifier}-{capacity}", identifier=identifier, quantity=0)
        db.session.add(group)
        db.session.flush()

        data = {"Code": identifier, "품명": "디스크", "용량": capacity, "수량": quantity, "위치": location}
        if extra:
            data.update(extra)
        row = InventoryRow(
            excel_file_id=ef.id,
            sheet_id=sheet.id,
            row_number=2,
            data_json=data,
            identifier=identifier,
            item_name="디스크",
            capacity=capacity,
            quantity=quantity,
            location=location,
            inventory_group_id=group.id,
        )
        db.session.add(row)
        group.quantity = quantity
        db.session.commit()
        return row.id


def api(client, method, path, **payload):
    """CSRF 헤더를 붙여 JSON 요청. 로그인된 client(csrf 속성 있음) 전용."""
    return client.open(
        path,
        method=method,
        json=payload,
        headers={"X-CSRFToken": client.csrf},
    )


def csrf_token_from(client, path="/login"):
    """페이지를 GET 해서 <meta name="csrf-token"> 값을 꺼낸다."""
    html = client.get(path).get_data(as_text=True)
    marker = 'name="csrf-token" content="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


def login(client, username, password):
    token = csrf_token_from(client, "/login")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


@pytest.fixture
def admin_client(client):
    resp = login(client, "admin", "adminpass123")
    assert resp.status_code == 302
    client.csrf = csrf_token_from(client, "/")
    return client


@pytest.fixture
def user_client(client):
    resp = login(client, "user1", "userpass123")
    assert resp.status_code == 302
    client.csrf = csrf_token_from(client, "/")
    return client
