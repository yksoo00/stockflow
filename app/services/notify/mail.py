"""
이메일 알림 (Gmail SMTP).

설정 (.env):
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=you@gmail.com
    SMTP_PASSWORD=<Google 계정 → 보안 → 앱 비밀번호 16자리>   ← 일반 비밀번호 아님
    MAIL_FROM=StockFlow <you@gmail.com>
    NOTIFY_ADMIN_EMAILS=a@x.com,b@x.com   (User.email 이 있는 관리자에게도 자동 발송)
    NOTIFY_ENABLED=1

발송은 백그라운드 스레드에서 하므로 요청 응답을 막지 않는다.
SMTP 설정이 비어 있으면 조용히 건너뛴다(로그만 남김).
"""

import logging
import os
import smtplib
import threading
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

logger = logging.getLogger(__name__)


def _settings():
    return {
        "enabled": os.getenv("NOTIFY_ENABLED", "1") == "1",
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "sender": os.getenv("MAIL_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
        "admin_emails": [
            e.strip() for e in os.getenv("NOTIFY_ADMIN_EMAILS", "").split(",") if e.strip()
        ],
        "base_url": os.getenv("APP_BASE_URL", "").rstrip("/"),
    }


def is_configured():
    s = _settings()
    return bool(s["enabled"] and s["host"] and s["user"] and s["password"])


def _deliver(subject, body, recipients, settings):
    msg = EmailMessage()
    msg["Subject"] = subject
    name, addr = parseaddr(settings["sender"])
    msg["From"] = formataddr((name or "StockFlow", addr or settings["user"]))
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings["host"], settings["port"], timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings["user"], settings["password"])
            smtp.send_message(msg)
        logger.info("Mail sent | subject=%s | to=%s", subject, len(recipients))
    except Exception:
        # 받는 사람 주소는 개인정보라 개수만 남긴다.
        logger.exception("Mail send failed | subject=%s | to=%s", subject, len(recipients))


def send_mail(subject, body, recipients, *, async_send=True):
    """
    recipients: 이메일 문자열 리스트. 비어 있거나 SMTP 미설정이면 False.
    """
    settings = _settings()
    recipients = list(dict.fromkeys(r for r in recipients if r))

    if not recipients:
        return False
    if not is_configured():
        logger.info("Mail skipped (SMTP not configured) | subject=%s", subject)
        return False

    if settings["base_url"]:
        body = f"{body}\n\n— StockFlow {settings['base_url']}"

    if async_send:
        threading.Thread(
            target=_deliver, args=(subject, body, recipients, settings), daemon=True
        ).start()
    else:
        _deliver(subject, body, recipients, settings)
    return True


def admin_recipients():
    """User.email 이 있는 활성 관리자 + NOTIFY_ADMIN_EMAILS."""
    from ...models import User

    emails = [
        u.email
        for u in User.query.filter(
            User.role == "admin", User.active == True, User.email.isnot(None)  # noqa: E712
        ).all()
        if u.email
    ]
    return list(dict.fromkeys(emails + _settings()["admin_emails"]))


# ---------------------------------------------------------------------------
# 이벤트별 템플릿
# ---------------------------------------------------------------------------


def _item_label(identifier, item_name):
    return identifier or item_name or "(품목 미상)"


def notify_stock_request_created(req, requester):
    """입고요청 생성(수동/자동) → 관리자."""
    kind = "자동 생성" if req.source == "auto" else "요청"
    subject = f"[StockFlow] 입고요청 {kind}: {_item_label(req.identifier, req.item_name)} {req.quantity:g}개"
    body = (
        f"입고요청이 {kind}되었습니다. 승인이 필요합니다.\n\n"
        f"품목   : {_item_label(req.identifier, req.item_name)}\n"
        f"수량   : {req.quantity:g}\n"
        f"사이트 : {req.site or '-'}\n"
        f"사유   : {req.reason or '-'}\n"
        f"요청자 : {requester.name or requester.username if requester else '-'}\n"
        f"요청번호: #{req.id}"
    )
    return send_mail(subject, body, admin_recipients())


def notify_low_stock(row, new_qty, site):
    """출고 후 저재고 진입 → 관리자."""
    label = _item_label(row.identifier, row.item_name)
    subject = f"[StockFlow] 저재고: {label} 잔여 {new_qty:g}개"
    body = (
        f"출고 후 재고가 임계값 이하로 떨어졌습니다.\n\n"
        f"품목   : {label}\n"
        f"잔여   : {new_qty:g}\n"
        f"출고지 : {site or '-'}\n"
        f"용량   : {row.capacity or '-'}\n"
        f"위치   : {row.location or '-'}"
    )
    return send_mail(subject, body, admin_recipients())


def notify_stock_request_status(req, actor):
    """승인/도착 → 요청자."""
    requester = req.requested_by
    if not requester or not requester.email:
        return False

    label = _item_label(req.identifier, req.item_name)
    if req.status == "approved":
        title, line = "승인", "입고요청이 승인되었습니다. 물품 도착 후 관리자가 입고 처리합니다."
    elif req.status == "arrived":
        title, line = "입고 완료", "요청하신 물품이 도착해 재고에 반영되었습니다."
    else:
        return False

    subject = f"[StockFlow] 입고요청 {title}: {label} {req.quantity:g}개"
    body = (
        f"{line}\n\n"
        f"품목   : {label}\n"
        f"수량   : {req.quantity:g}\n"
        f"사이트 : {req.site or '-'}\n"
        f"처리자 : {actor.name or actor.username if actor else '-'}\n"
        f"요청번호: #{req.id}"
    )
    return send_mail(subject, body, [requester.email])
