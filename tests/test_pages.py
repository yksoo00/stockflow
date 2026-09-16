"""모든 HTML 페이지가 렌더링되는지(템플릿 오류 없는지) 확인하는 smoke test."""

import pytest

PAGES_ALL = [
    "/", "/files", "/stockout", "/stockin", "/requests", "/chat", "/ebay/ABC-123",
    "/account", "/units", "/sites/서울IDC",
]
PAGES_ADMIN = ["/upload", "/register", "/adminlog", "/users"]


@pytest.mark.parametrize("path", PAGES_ALL)
def test_pages_render_for_user(user_client, path):
    resp = user_client.get(path)
    assert resp.status_code == 200, path
    assert 'name="csrf-token"' in resp.get_data(as_text=True)


@pytest.mark.parametrize("path", PAGES_ALL + PAGES_ADMIN)
def test_pages_render_for_admin(admin_client, path):
    assert admin_client.get(path).status_code == 200, path


@pytest.mark.parametrize("path", PAGES_ADMIN)
def test_admin_pages_redirect_for_user(user_client, path):
    resp = user_client.get(path, follow_redirects=False)
    assert resp.status_code == 302, path


@pytest.mark.parametrize("path", PAGES_ALL + PAGES_ADMIN)
def test_pages_require_login(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_health_is_public(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_static_requests_are_not_logged(client, app, tmp_path):
    client.get("/static/js/app.js")
    client.get("/login")
    log = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "HTTP GET /login" in log
    assert "/static/js/app.js" not in log
