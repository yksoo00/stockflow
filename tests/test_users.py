"""계정: 비밀번호 변경/초기화, 비활성화, 역할 변경, 담당 사이트."""

from werkzeug.security import check_password_hash

from app.models import User

from .conftest import api, csrf_token_from, login


def _user(app, username):
    with app.app_context():
        return User.query.filter_by(username=username).one()


def test_change_password_and_relogin(user_client, app, client):
    resp = user_client.post(
        "/account",
        data={
            "form": "password",
            "current_password": "userpass123",
            "new_password": "newpass12345",
            "confirm_password": "newpass12345",
            "csrf_token": user_client.csrf,
        },
    )
    assert resp.status_code == 302
    assert check_password_hash(_user(app, "user1").password_hash, "newpass12345")

    user_client.post("/logout", data={"csrf_token": user_client.csrf})
    assert login(client, "user1", "userpass123").status_code == 200  # 옛 비번 실패 → 폼 재표시
    assert login(client, "user1", "newpass12345").status_code == 302


def test_change_password_wrong_current(user_client, app):
    user_client.post(
        "/account",
        data={"form": "password", "current_password": "nope", "new_password": "newpass12345",
              "confirm_password": "newpass12345", "csrf_token": user_client.csrf},
    )
    assert check_password_hash(_user(app, "user1").password_hash, "userpass123")


def test_profile_update_sets_site_filter_default(user_client, app):
    user_client.post(
        "/account",
        data={"form": "profile", "email": "u1@example.com", "site": "서울IDC", "csrf_token": user_client.csrf},
    )
    u = _user(app, "user1")
    assert u.email == "u1@example.com" and u.site == "서울IDC"

    html = user_client.get("/stockout").get_data(as_text=True)
    assert 'id="stockoutSite" class="search" style="max-width:220px" placeholder="사이트 필터" value="서울IDC"' in html
    assert 'window.USER_SITE = "\\uc11c\\uc6b8IDC"' in html or "서울IDC" in html


def test_admin_reset_password_forces_change(admin_client, app):
    uid = _user(app, "user1").id
    resp = api(admin_client, "POST", f"/api/users/{uid}/reset-password")
    assert resp.status_code == 200
    temp = resp.get_json()["temp_password"]
    assert len(temp) >= 8
    assert _user(app, "user1").must_change_password is True

    # 별도 세션(새 클라이언트)으로 임시 비번 로그인 → /account 로 강제 이동
    other = app.test_client()
    resp = login(other, "user1", temp)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/account")


def test_deactivated_user_cannot_login(admin_client, app):
    uid = _user(app, "user1").id
    resp = api(admin_client, "PATCH", f"/api/users/{uid}", active=False)
    assert resp.status_code == 200 and resp.get_json()["item"]["active"] is False

    other = app.test_client()
    resp = login(other, "user1", "userpass123")
    assert resp.status_code == 200  # 로그인 폼으로 되돌아옴
    with other.session_transaction() as sess:
        assert "_user_id" not in sess


def test_admin_cannot_deactivate_or_demote_self(admin_client, app):
    uid = _user(app, "admin").id
    assert api(admin_client, "PATCH", f"/api/users/{uid}", active=False).status_code == 400
    assert api(admin_client, "PATCH", f"/api/users/{uid}", role="user").status_code == 400


def test_role_change_and_bad_role(admin_client, app):
    uid = _user(app, "user1").id
    assert api(admin_client, "PATCH", f"/api/users/{uid}", role="admin").get_json()["item"]["role"] == "admin"
    assert api(admin_client, "PATCH", f"/api/users/{uid}", role="root").status_code == 400


def test_user_management_is_admin_only(user_client):
    assert user_client.get("/api/users").status_code == 403
    assert user_client.get("/users", follow_redirects=False).status_code == 302


def test_register_with_email_and_site(admin_client, app):
    admin_client.post(
        "/register",
        data={"username": "newbie", "password": "longenough1", "name": "신규", "position": "",
              "role": "user", "email": "n@example.com", "site": "부산DC", "csrf_token": admin_client.csrf},
    )
    u = _user(app, "newbie")
    assert u.email == "n@example.com" and u.site == "부산DC" and u.active is True


def test_login_logout_are_logged(client, app):
    login(client, "admin", "adminpass123")
    token = csrf_token_from(client, "/")
    client.post("/logout", data={"csrf_token": token})
    with app.app_context():
        from app.models import AdminLog

        actions = [a.action for a in AdminLog.query.all()]
    assert "login" in actions and "logout" in actions
