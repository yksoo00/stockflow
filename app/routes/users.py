"""
계정 관리.

- /account          : 본인 비밀번호 변경, 이메일/담당 사이트 수정
- /users (관리자)   : 사용자 목록, 역할 변경, 비밀번호 초기화, 비활성화/활성화, 이메일·사이트 편집
"""

import logging
import secrets

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db
from ..models import User
from ..models.user import parse_site_list
from ..utils.time import fmt
from .auth import MIN_PASSWORD_LEN, ROLES
from .common import admin_required, admin_required_api, log_action

users_bp = Blueprint("users", __name__)
logger = logging.getLogger(__name__)


def _serialize(u):
    return {
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "position": u.position,
        "role": u.role,
        "email": u.email,
        "site": u.site,
        "sites": u.site_list,
        "active": bool(u.active),
        "must_change_password": bool(u.must_change_password),
        "created_at": fmt(u.created_at),
    }


# =========================================================
# 내 계정
# =========================================================
@users_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        form = request.form.get("form", "")

        if form == "profile":
            email = request.form.get("email", "").strip() or None
            sites = parse_site_list(request.form.get("site", ""))
            if email and "@" not in email:
                flash("이메일 형식이 올바르지 않습니다.", "error")
                return redirect(url_for("users.account"))
            changed = []
            if email != current_user.email:
                changed.append("이메일")
                current_user.email = email
            if sites != current_user.site_list:
                changed.append(f"담당 사이트 → {', '.join(sites) or '-'}")
                current_user.site_list = sites
            if changed:
                log_action(
                    "profile_update",
                    detail=f"{current_user.username} {', '.join(changed)} 변경",
                    target_type="user",
                    target_id=current_user.id,
                )
                db.session.commit()
                flash("저장되었습니다.", "success")
            return redirect(url_for("users.account"))

        if form == "password":
            current = request.form.get("current_password", "")
            new = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")

            if not check_password_hash(current_user.password_hash, current):
                flash("현재 비밀번호가 올바르지 않습니다.", "error")
            elif len(new) < MIN_PASSWORD_LEN:
                flash(f"새 비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다.", "error")
            elif new != confirm:
                flash("새 비밀번호 확인이 일치하지 않습니다.", "error")
            elif new == current:
                flash("현재 비밀번호와 다른 비밀번호를 입력하세요.", "error")
            else:
                current_user.password_hash = generate_password_hash(new)
                current_user.must_change_password = False
                log_action(
                    "password_change",
                    detail=f"{current_user.username} 비밀번호 변경",
                    target_type="user",
                    target_id=current_user.id,
                )
                db.session.commit()
                logger.info("Password changed | user_id=%s", current_user.id)
                flash("비밀번호가 변경되었습니다.", "success")
                return redirect(url_for("main.dashboard"))

            return redirect(url_for("users.account"))

    return render_template("pages/account/index.html")


# =========================================================
# 사용자 관리 (관리자)
# =========================================================
@users_bp.get("/users")
@admin_required
def users_page():
    return render_template("pages/users/list.html", roles=sorted(ROLES))


@users_bp.get("/api/users")
@admin_required_api
def list_users():
    q = request.args.get("q", "").strip()
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                User.username.ilike(like),
                User.name.ilike(like),
                User.email.ilike(like),
                User.site.ilike(like),
            )
        )
    users = query.order_by(User.active.desc(), User.role.desc(), User.username).all()
    return jsonify({"items": [_serialize(u) for u in users]})


@users_bp.patch("/api/users/<int:user_id>")
@admin_required_api
def update_user(user_id):
    u = db.get_or_404(User, user_id)
    payload = request.get_json(silent=True) or {}
    changes = []

    if "role" in payload:
        role = str(payload["role"]).strip()
        if role not in ROLES:
            return jsonify({"error": "올바르지 않은 역할입니다."}), 400
        if u.id == current_user.id and role != "admin":
            return jsonify({"error": "자기 자신의 관리자 권한은 내릴 수 없습니다."}), 400
        if role != u.role:
            changes.append(f"role {u.role}→{role}")
            u.role = role

    if "email" in payload:
        email = str(payload["email"] or "").strip() or None
        if email and "@" not in email:
            return jsonify({"error": "이메일 형식이 올바르지 않습니다."}), 400
        if email != u.email:
            changes.append("이메일")
            u.email = email

    if "site" in payload:
        sites = parse_site_list(payload["site"])
        if sites != u.site_list:
            changes.append(f"담당사이트 {u.site or '-'}→{', '.join(sites) or '-'}")
            u.site_list = sites

    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if name and name != u.name:
            changes.append("이름")
            u.name = name

    if "position" in payload:
        position = str(payload["position"] or "").strip() or None
        if position != u.position:
            changes.append("직책")
            u.position = position

    if "active" in payload:
        active = bool(payload["active"])
        if u.id == current_user.id and not active:
            return jsonify({"error": "자기 자신을 비활성화할 수 없습니다."}), 400
        if active != bool(u.active):
            changes.append("활성화" if active else "비활성화")
            u.active = active

    if changes:
        log_action(
            "user_update",
            detail=f"{u.name or u.username}({u.username}) " + ", ".join(changes),
            target_type="user",
            target_id=u.id,
        )
        db.session.commit()
        logger.info("User updated | user_id=%s | by=%s | changes=%s", u.id, current_user.id, changes)

    return jsonify({"ok": True, "item": _serialize(u)})


@users_bp.post("/api/users/<int:user_id>/reset-password")
@admin_required_api
def reset_password(user_id):
    """
    임시 비밀번호를 만들어 돌려준다(한 번만 표시). 사용자는 다음 로그인 때 변경을 강제당한다.
    """
    u = db.get_or_404(User, user_id)
    temp = secrets.token_urlsafe(9)  # 12자 내외
    u.password_hash = generate_password_hash(temp)
    u.must_change_password = True
    log_action(
        "password_reset",
        detail=f"{u.name or u.username}({u.username}) 비밀번호 초기화",
        target_type="user",
        target_id=u.id,
    )
    db.session.commit()
    logger.info("Password reset | user_id=%s | by=%s", u.id, current_user.id)
    return jsonify({"ok": True, "temp_password": temp, "item": _serialize(u)})
