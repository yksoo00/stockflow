"""Gmail SMTP 알림 — smtplib 를 mock 해서 누구에게 무엇이 가는지 검증."""

from unittest.mock import MagicMock, patch

from app import db
from app.models import User
from app.services.notify import mail

from .conftest import api, make_row


def _configure(monkeypatch, admin_emails=""):
    monkeypatch.setenv("NOTIFY_ENABLED", "1")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bot@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("MAIL_FROM", "StockFlow <bot@gmail.com>")
    monkeypatch.setenv("NOTIFY_ADMIN_EMAILS", admin_emails)


def test_send_mail_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert mail.is_configured() is False
    assert mail.send_mail("s", "b", ["a@b.c"]) is False


def test_send_mail_uses_starttls_and_login(monkeypatch):
    _configure(monkeypatch)
    smtp = MagicMock()
    with patch("smtplib.SMTP") as SMTP:
        SMTP.return_value.__enter__.return_value = smtp
        assert mail.send_mail("제목", "본문", ["a@x.com", "a@x.com", "b@x.com"], async_send=False) is True
        SMTP.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("bot@gmail.com", "app-password")
    msg = smtp.send_message.call_args[0][0]
    assert msg["Subject"] == "제목"
    assert msg["To"] == "a@x.com, b@x.com"  # 중복 제거
    assert "StockFlow" in msg["From"]


def test_auto_request_notifies_admins(monkeypatch, user_client, app):
    _configure(monkeypatch, admin_emails="ops@example.com")
    with app.app_context():
        admin = User.query.filter_by(username="admin").one()
        admin.email = "admin@example.com"
        db.session.commit()

    row_id = make_row(app, quantity=1)
    with patch.object(mail, "send_mail", return_value=True) as send:
        resp = api(user_client, "POST", "/api/stockout", row_id=row_id, site="서울IDC", quantity=1)
        assert resp.status_code == 200

    subjects = [c.args[0] for c in send.call_args_list]
    assert any("입고요청 자동 생성" in s for s in subjects)
    assert any("저재고" in s for s in subjects)
    recipients = send.call_args_list[0].args[2]
    assert set(recipients) == {"admin@example.com", "ops@example.com"}


def test_approve_notifies_requester_only_if_email(monkeypatch, admin_client, app):
    _configure(monkeypatch)
    row_id = make_row(app, quantity=1)
    rid = api(admin_client, "POST", "/api/stockrequest", row_id=row_id, site="A", quantity=1).get_json()["item"]["id"]

    # 요청자(admin)에 이메일 없음 → 발송 안 함
    with patch.object(mail, "send_mail", return_value=True) as send:
        api(admin_client, "POST", f"/api/stockrequest/{rid}/approve")
    assert not any("승인" in c.args[0] for c in send.call_args_list)

    with app.app_context():
        User.query.filter_by(username="admin").one().email = "admin@example.com"
        db.session.commit()

    with patch.object(mail, "send_mail", return_value=True) as send:
        api(admin_client, "POST", f"/api/stockrequest/{rid}/arrive")
    assert any("입고 완료" in c.args[0] for c in send.call_args_list)
    assert send.call_args_list[-1].args[2] == ["admin@example.com"]


def test_mail_failure_does_not_break_request(monkeypatch, user_client, app):
    _configure(monkeypatch)
    row_id = make_row(app, quantity=1)
    with patch.object(mail, "send_mail", side_effect=RuntimeError("smtp down")):
        resp = api(user_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1)
    assert resp.status_code == 200
