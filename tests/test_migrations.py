"""
Alembic 마이그레이션이 두 상황 모두에서 동작하는지:
  1) 완전히 빈 DB → upgrade → 최신 스키마
  2) 예전 db.create_all() 로 만들어진 DB(0001 이전 스키마) → upgrade → 컬럼/테이블 추가만
MySQL 없이 파일 SQLite 로 검증한다. (MySQL 전용 문법은 여기서 못 잡는다)
"""

import sqlalchemy as sa
from flask_migrate import upgrade

from app import create_app


def _make_app(tmp_path, name):
    return create_app(
        test_config={
            "TESTING": False,  # create_all 을 타지 않도록
            "SECRET_KEY": "x" * 32,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / name}",
            "WTF_CSRF_ENABLED": False,
        }
    )


def _columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_upgrade_on_empty_database(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_MIGRATE", "0")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    app = _make_app(tmp_path, "fresh.db")
    with app.app_context():
        upgrade()
        from app import db

        tables = set(sa.inspect(db.engine).get_table_names())
        assert {"user", "stock_out", "disk_unit", "admin_log", "alembic_version"} <= tables
        assert {"email", "site", "active", "must_change_password"} <= _columns(db.engine, "user")
        assert {"ticket_no", "handler", "serials", "cancelled_at"} <= _columns(db.engine, "stock_out")


def test_upgrade_on_legacy_database(tmp_path, monkeypatch):
    """운영 DB 처럼 이미 옛 테이블이 있는 상태에서 stamp 없이 upgrade."""
    monkeypatch.setenv("AUTO_MIGRATE", "0")
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    path = tmp_path / "legacy.db"

    # 옛 스키마를 직접 만든다 (user 에 name/position/role 조차 없는 가장 오래된 형태)
    engine = sa.create_engine(f"sqlite:///{path}")
    meta = sa.MetaData()
    sa.Table(
        "user", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime),
    )
    sa.Table(
        "stock_out", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("inventory_row_id", sa.Integer),
        sa.Column("user_id", sa.Integer),
        sa.Column("identifier", sa.String(255)),
        sa.Column("item_name", sa.String(255)),
        sa.Column("site", sa.String(120)),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("reason", sa.String(255)),
        sa.Column("created_at", sa.DateTime),
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO user (username, password_hash) VALUES ('old', 'x')"))
        conn.execute(sa.text("INSERT INTO stock_out (identifier, quantity) VALUES ('C1', 2)"))
    engine.dispose()

    app = _make_app(tmp_path, "legacy.db")
    with app.app_context():
        upgrade()
        from app import db

        # 기존 데이터 보존 + 새 컬럼 추가
        with db.engine.connect() as conn:
            assert conn.execute(sa.text("SELECT username, active FROM user")).fetchall() == [("old", 1)]
            assert conn.execute(sa.text("SELECT identifier, cancelled_at FROM stock_out")).fetchall() == [("C1", None)]
        assert {"name", "position", "role", "email", "site"} <= _columns(db.engine, "user")
        assert "disk_unit" in sa.inspect(db.engine).get_table_names()
        assert "excel_file" in sa.inspect(db.engine).get_table_names()  # 없던 테이블은 생성

        # 두 번 실행해도 안전 (idempotent)
        upgrade()
