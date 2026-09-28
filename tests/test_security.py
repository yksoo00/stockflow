"""A단계(보안) 회귀 테스트: CSRF, open redirect, 역할 부여, 로그인 제한, SECRET_KEY 검사."""

import pytest

from app import _bootstrap_admin, create_app, db
from app.models import User
from werkzeug.security import check_password_hash

from .conftest import csrf_token_from, login

# ---------------------------------------------------------------------------
# SECRET_KEY
# ---------------------------------------------------------------------------


def test_placeholder_secret_key_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "CHANGE_ME")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


def test_missing_secret_key_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


def test_login_without_csrf_token_is_rejected(client):
    resp = client.post("/login", data={"username": "admin", "password": "adminpass123"})
    # CSRF 실패 → flash 후 referrer(없음)로 리다이렉트
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "_user_id" not in sess


def test_login_with_csrf_token_succeeds(client):
    resp = login(client, "admin", "adminpass123")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_bootstrap_admin_is_created_only_once(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "first-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "strong-password-123")
    monkeypatch.setenv("ADMIN_NAME", "초기 관리자")
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-0123456789abcdef",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )

    with app.app_context():
        admin = User.query.filter_by(username="first-admin").one()
        assert admin.role == "admin"
        assert admin.name == "초기 관리자"
        assert check_password_hash(admin.password_hash, "strong-password-123")

        monkeypatch.setenv("ADMIN_PASSWORD", "replacement-password-456")
        _bootstrap_admin()
        db.session.refresh(admin)
        assert check_password_hash(admin.password_hash, "strong-password-123")
        assert User.query.filter_by(role="admin").count() == 1


def test_json_api_without_csrf_header_is_rejected(user_client):
    resp = user_client.post("/api/stockout", json={"row_id": 1, "site": "A", "quantity": 1})
    assert resp.status_code == 400
    assert "요청 검증" in resp.get_json()["error"]


def test_json_api_with_csrf_header_passes_csrf(user_client):
    resp = user_client.post(
        "/api/stockout",
        json={"row_id": 999999, "site": "A", "quantity": 1},
        headers={"X-CSRFToken": user_client.csrf},
    )
    # CSRF 는 통과했고, 존재하지 않는 row 라서 404
    assert resp.status_code == 404


def test_text_plain_body_is_not_parsed_as_json(user_client):
    """예전 get_json(force=True) 는 text/plain 폼 전송도 JSON 으로 읽어 CSRF 우회가 가능했다."""
    resp = user_client.post(
        "/api/stockout",
        data='{"row_id": 1, "site": "A", "quantity": 1}',
        content_type="text/plain",
        headers={"X-CSRFToken": user_client.csrf},
    )
    # 본문이 무시되어 row_id 누락 → 400
    assert resp.status_code == 400
    assert "row_id" in resp.get_json()["error"]


def test_logout_requires_post(user_client):
    assert user_client.get("/logout").status_code == 405
    resp = user_client.post("/logout", data={"csrf_token": user_client.csrf})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


# ---------------------------------------------------------------------------
# Open redirect
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example.com/",
        "//evil.example.com/",
        "http://evil.example.com\\@localhost/",
        "javascript:alert(1)",
    ],
)
def test_login_ignores_external_next(client, target):
    token = csrf_token_from(client, "/login")
    resp = client.post(
        f"/login?next={target}",
        data={"username": "admin", "password": "adminpass123", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")


def test_login_honours_internal_next(client):
    token = csrf_token_from(client, "/login")
    resp = client.post(
        "/login?next=/files",
        data={"username": "admin", "password": "adminpass123", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/files")


# ---------------------------------------------------------------------------
# 사용자 추가 / 역할
# ---------------------------------------------------------------------------


def _register(client, **fields):
    data = {
        "username": "newuser",
        "password": "longenough1",
        "name": "신규",
        "position": "",
        "role": "user",
        "csrf_token": client.csrf,
    }
    data.update(fields)
    return client.post("/register", data=data, follow_redirects=True)


def test_register_requires_admin(user_client):
    resp = user_client.get("/register", follow_redirects=False)
    assert resp.status_code == 302  # 대시보드로 되돌려보냄


def test_username_containing_admin_does_not_grant_admin(admin_client, app):
    _register(admin_client, username="badminton", role="user")
    with app.app_context():
        u = User.query.filter_by(username="badminton").one()
        assert u.role == "user"


def test_explicit_admin_role_is_honoured(admin_client, app):
    _register(admin_client, username="second", role="admin")
    with app.app_context():
        assert User.query.filter_by(username="second").one().role == "admin"


def test_unknown_role_is_rejected(admin_client, app):
    _register(admin_client, username="weird", role="superuser")
    with app.app_context():
        assert User.query.filter_by(username="weird").first() is None


def test_short_password_is_rejected(admin_client, app):
    _register(admin_client, username="shortpw", password="1234")
    with app.app_context():
        assert User.query.filter_by(username="shortpw").first() is None


# ---------------------------------------------------------------------------
# 로그인 시도 제한
# ---------------------------------------------------------------------------


def test_login_is_rate_limited(client):
    token = csrf_token_from(client, "/login")
    statuses = []
    for _ in range(12):
        resp = client.post(
            "/login",
            data={"username": "admin", "password": "wrong", "csrf_token": token},
        )
        statuses.append(resp.status_code)
    # 처음 10회는 폼 재표시(200), 그 뒤는 429 핸들러가 flash 후 302
    assert statuses[:10] == [200] * 10
    assert statuses[10:] == [302, 302]


# ---------------------------------------------------------------------------
# 에러 응답에 내부 정보가 새지 않는지
# ---------------------------------------------------------------------------


def test_security_headers_present(client):
    resp = client.get("/login")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in resp.headers
