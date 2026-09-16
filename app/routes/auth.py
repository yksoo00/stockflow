import logging
from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db, limiter
from ..models import User
from .common import admin_required, log_action

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

ROLES = {"user", "admin"}
MIN_USERNAME_LEN = 3
MIN_PASSWORD_LEN = 8


def _is_safe_redirect(target):
    """
    로그인 후 되돌아갈 next 주소가 이 서비스 내부 경로인지 확인한다.
    외부 주소(//evil.com, https://evil.com 등)로 보내는 open redirect 를 막는다.
    """
    if not target:
        return False
    base = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in {"http", "https"} and candidate.netloc == base.netloc


@auth_bp.route("/login", methods=["GET", "POST"])
# 로그인 무차별 대입 방지. IP 기준 1분 10회 / 1시간 100회.
@limiter.limit("10 per minute; 100 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        u = User.query.filter_by(username=username).first() if username else None

        if u and check_password_hash(u.password_hash, password):
            if not u.active:
                logger.warning("Login refused (inactive) | user_id=%s", u.id)
                log_action("login_inactive", detail=f"{u.username} 비활성 계정 로그인 시도", target_type="user", target_id=u.id, user_id=u.id)
                db.session.commit()
                flash("비활성화된 계정입니다. 관리자에게 문의하세요.", "error")
                return render_template("pages/auth/login.html", register=False)

            login_user(u)
            logger.info("Login success | user_id=%s", u.id)
            log_action("login", detail=f"{u.username} 로그인", target_type="user", target_id=u.id)
            db.session.commit()

            if u.must_change_password:
                flash("임시 비밀번호로 로그인했습니다. 새 비밀번호를 설정하세요.", "error")
                return redirect(url_for("users.account"))

            next_url = request.args.get("next") or request.form.get("next")
            if _is_safe_redirect(next_url):
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))

        # 실패한 아이디는 남기지 않는다 — 아이디 칸에 비밀번호를 잘못 치는 경우가 잦고,
        # 존재하는 계정 목록을 로그로 유추할 수 있게 되기 때문. IP 만 기록한다.
        logger.warning("Login failed | remote=%s", request.remote_addr)
        flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")

    return render_template("pages/auth/login.html", register=False)


# 회원가입은 관리자만 가능하다 (공개 가입 없음 — 관리자가 직접 계정을 만들어 나눠준다).
@auth_bp.route("/register", methods=["GET", "POST"])
@admin_required
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        position = request.form.get("position", "").strip()
        email = request.form.get("email", "").strip() or None
        site = request.form.get("site", "").strip() or None
        # 역할은 폼에서 명시적으로 고른다. (예전의 "아이디에 admin 이 들어가면 관리자" 규칙 제거)
        role = request.form.get("role", "user").strip() or "user"

        if len(username) < MIN_USERNAME_LEN or len(pw) < MIN_PASSWORD_LEN:
            flash(
                f"아이디 {MIN_USERNAME_LEN}자 이상, 비밀번호 {MIN_PASSWORD_LEN}자 이상을 입력하세요.",
                "error",
            )

        elif not name:
            flash("이름을 입력하세요.", "error")

        elif role not in ROLES:
            flash("올바르지 않은 역할입니다.", "error")

        elif User.query.filter_by(username=username).first():
            flash("이미 사용 중인 아이디입니다.", "error")

        else:
            u = User(
                username=username,
                password_hash=generate_password_hash(pw),
                role=role,
                name=name,
                position=position or None,
                email=email,
                site=site,
            )

            db.session.add(u)
            db.session.flush()
            log_action(
                "user_create",
                detail=f"{u.name}({u.username}) 계정 생성 (role={u.role})",
                target_type="user",
                target_id=u.id,
            )
            db.session.commit()
            logger.info(
                "User created by admin | user_id=%s | role=%s | created_by=%s",
                u.id,
                u.role,
                current_user.id,
            )

            flash(f"{u.name}({u.username}) 계정이 생성되었습니다.", "success")

            return redirect(url_for("auth.register"))

    return render_template("pages/auth/login.html", register=True, roles=sorted(ROLES))


@auth_bp.post("/logout")
@login_required
def logout():
    logger.info("Logout | user_id=%s", current_user.id)
    log_action("logout", detail=f"{current_user.username} 로그아웃", target_type="user", target_id=current_user.id)
    db.session.commit()
    logout_user()

    return redirect(url_for("auth.login"))
