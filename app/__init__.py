import logging
import os
import time
import uuid

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.exceptions import HTTPException

from .logging_config import configure_logging

load_dotenv()
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
# 기본 저장소는 프로세스 메모리다. waitress 단일 프로세스에서는 충분하고,
# 멀티 프로세스/멀티 인스턴스로 가면 RATELIMIT_STORAGE_URI 를 redis 등으로 바꿔야 한다.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
)
logger = logging.getLogger(__name__)


def _require_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"환경변수 {name} 가 설정되지 않았습니다. .env 를 확인하세요 (.env.example 참고)."
        )
    return value


def _api_request():
    """JSON API 요청인지(페이지 요청이 아닌지) 판단한다. 에러 응답 형식을 고를 때 쓴다."""
    return request.path.startswith("/api/") or request.is_json


def create_app(test_config=None):
    app = Flask(__name__)
    configure_logging(app)

    if test_config is None:
        # 운영/개발 공통: 비밀키와 DB 주소는 반드시 명시해야 한다.
        # 예전처럼 "dev-secret" 같은 기본값으로 뜨면 세션 위조가 가능하므로 기동을 막는다.
        secret_key = _require_env("SECRET_KEY")
        if secret_key in {"CHANGE_ME", "dev-secret"} or len(secret_key) < 16:
            raise RuntimeError(
                "SECRET_KEY 가 예시값이거나 너무 짧습니다(16자 이상). "
                "예: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        app.config.update(
            SECRET_KEY=secret_key,
            SQLALCHEMY_DATABASE_URI=_require_env("DATABASE_URL"),
        )
    else:
        app.config.update(test_config)

    app.config.update(
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=int(os.getenv("UPLOAD_MAX_MB", "100")) * 1024 * 1024,
        # 세션 쿠키 보호. HTTPS 뒤에서 운영하면 SESSION_COOKIE_SECURE=1 로 켠다.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
        # CSRF 토큰은 세션 수명과 같이 간다(기본 1시간 만료 때문에 긴 편집 세션이 끊기는 것을 방지).
        WTF_CSRF_TIME_LIMIT=None,
        WTF_CSRF_HEADERS=["X-CSRFToken", "X-CSRF-Token"],
    )

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(app.root_path), "migrations"))
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"
    csrf.init_app(app)
    limiter.init_app(app)

    @app.before_request
    def _request_start():
        g.request_id = uuid.uuid4().hex[:12]
        g.request_started_at = time.perf_counter()

    @app.after_request
    def _request_end(response):
        elapsed_ms = (
            time.perf_counter() - getattr(g, "request_started_at", time.perf_counter())
        ) * 1000
        user = (
            getattr(current_user, "id", None) if current_user.is_authenticated else None
        )
        # 정적 파일 요청은 로그 노이즈만 만들므로 기록하지 않는다.
        if not request.path.startswith("/static/"):
            # Never log query/form bodies or credentials.
            logger.info(
                "HTTP %s %s -> %s %.1fms request_id=%s user_id=%s",
                request.method,
                request.path,
                response.status_code,
                elapsed_ms,
                getattr(g, "request_id", "-"),
                user if user is not None else "-",
            )
        response.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.errorhandler(CSRFError)
    def _csrf_error(exc):
        logger.warning(
            "CSRF validation failed | request_id=%s | path=%s | reason=%s",
            getattr(g, "request_id", "-"),
            request.path,
            exc.description,
        )
        if _api_request():
            return jsonify({"error": "요청 검증에 실패했습니다. 페이지를 새로 고친 뒤 다시 시도하세요."}), 400
        from flask import flash, redirect

        flash("요청 검증에 실패했습니다. 페이지를 새로 고친 뒤 다시 시도하세요.", "error")
        return redirect(request.referrer or "/")

    @app.errorhandler(429)
    def _rate_limited(exc):
        if _api_request():
            return jsonify({"error": "요청이 너무 많습니다. 잠시 후 다시 시도하세요."}), 429
        from flask import flash, redirect

        flash("시도가 너무 많습니다. 잠시 후 다시 시도하세요.", "error")
        return redirect(request.referrer or "/")

    @app.errorhandler(Exception)
    def _unhandled_error(exc):
        # Flask의 404, 405 등의 HTTP 예외는
        # 우리가 500으로 바꾸지 않고 원래대로 처리한다.
        if isinstance(exc, HTTPException):
            return exc

        # 그 외 실제 서버 오류만 로그에 traceback과 함께 기록한다.
        logger.exception(
            "Unhandled exception | request_id=%s | method=%s | path=%s",
            getattr(g, "request_id", "-"),
            request.method,
            request.path,
        )

        return jsonify(
            {
                "error": "서버 내부 오류가 발생했습니다.",
                "request_id": getattr(g, "request_id", "-"),
            }
        ), 500

    from .models import User
    from .utils.time import fmt as _fmt_local

    app.jinja_env.filters["localtime"] = lambda dt, pattern="%Y-%m-%d %H:%M": _fmt_local(dt, pattern) or ""

    @app.context_processor
    def _inject_globals():
        """
        - pending_request_count / pending_stale_count:
          사이드바 '입고 요청' 메뉴의 미승인 건수 배지. 승인은 관리자만 하므로 관리자에게만 계산.
        - user_site: 담당 사이트 (출고/입고/요청 목록의 기본 필터)
        """
        ctx = {"pending_request_count": 0, "pending_stale_count": 0, "user_site": None}
        if not current_user.is_authenticated:
            return ctx
        ctx["user_site"] = getattr(current_user, "site", None)
        if current_user.role != "admin":
            return ctx
        try:
            from .routes.stockrequest import pending_summary

            summary = pending_summary()
            ctx["pending_request_count"] = summary["count"]
            ctx["pending_stale_count"] = summary["stale"]
        except Exception:
            logger.exception("Pending stock-request count failed")
        return ctx

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            logger.warning("Invalid user session id received")
            return None

    from .routes import register_blueprints

    register_blueprints(app)

    # 스키마 (B-13): 운영/개발은 Alembic 마이그레이션으로만 바꾼다.
    #  - AUTO_MIGRATE=1 (기본) 이면 기동 시 `flask db upgrade` 와 같은 동작을 한다.
    #  - 테스트는 SQLite 메모리 DB 라 create_all 로 바로 만든다.
    if app.config.get("TESTING"):
        with app.app_context():
            db.create_all()
    elif os.getenv("AUTO_MIGRATE", "1") == "1":
        from flask_migrate import upgrade

        with app.app_context():
            upgrade()
        logger.info("Database migrations applied")

    logger.info("Flask application initialized")
    return app
