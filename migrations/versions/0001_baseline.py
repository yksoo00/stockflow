"""baseline — 기존 운영 DB 스키마 (마이그레이션 도입 이전 상태)

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-16

이 마이그레이션은 **이미 존재하는 테이블은 건드리지 않는다.**
db.create_all() 로 만들어진 운영 DB 에도 그대로 `flask db upgrade` 를 실행할 수 있게 하기 위해서다.
(별도의 `flask db stamp` 없이도 동작한다.)

User 테이블의 name/position/role 컬럼은 예전 migrate_user_columns.py 로 추가되었을 수도,
아닐 수도 있으므로 여기서 없으면 추가한다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _has_column(table, column):
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _add_column_if_missing(table, column):
    if not _has_column(table, column.name):
        op.add_column(table, column)


def upgrade():
    if not _has_table("user"):
        op.create_table(
            "user",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(80), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(30)),
            sa.Column("name", sa.String(80)),
            sa.Column("position", sa.String(80)),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_user_username", "user", ["username"], unique=True)
    else:
        _add_column_if_missing("user", sa.Column("name", sa.String(80)))
        _add_column_if_missing("user", sa.Column("position", sa.String(80)))
        _add_column_if_missing("user", sa.Column("role", sa.String(30)))

    if not _has_table("excel_file"):
        op.create_table(
            "excel_file",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("stored_filename", sa.String(255), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=False),
            sa.Column("file_hash", sa.String(64)),
            sa.Column("file_size", sa.BigInteger()),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("processing_status", sa.String(30)),
            sa.Column("error_message", sa.Text()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
        op.create_index("ix_excel_file_file_hash", "excel_file", ["file_hash"])

    if not _has_table("excel_sheet"):
        op.create_table(
            "excel_sheet",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("excel_file_id", sa.Integer(), sa.ForeignKey("excel_file.id"), nullable=False),
            sa.Column("sheet_name", sa.String(255), nullable=False),
            sa.Column("sheet_order", sa.Integer()),
            sa.Column("sheet_type", sa.String(30)),
            sa.Column("row_count", sa.Integer()),
            sa.Column("column_count", sa.Integer()),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_excel_sheet_excel_file_id", "excel_sheet", ["excel_file_id"])

    if not _has_table("detected_table"):
        op.create_table(
            "detected_table",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("excel_sheet.id"), nullable=False),
            sa.Column("title", sa.String(255)),
            sa.Column("header_row", sa.Integer()),
            sa.Column("start_row", sa.Integer()),
            sa.Column("end_row", sa.Integer()),
            sa.Column("start_col", sa.Integer()),
            sa.Column("end_col", sa.Integer()),
            sa.Column("table_type", sa.String(30)),
            sa.Column("created_at", sa.DateTime()),
        )

    if not _has_table("sheet_column"):
        op.create_table(
            "sheet_column",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("excel_sheet.id"), nullable=False),
            sa.Column("table_id", sa.Integer(), sa.ForeignKey("detected_table.id")),
            sa.Column("column_index", sa.Integer()),
            sa.Column("original_name", sa.String(255)),
            sa.Column("normalized_name", sa.String(255)),
            sa.Column("data_type", sa.String(30)),
            sa.Column("is_searchable", sa.Boolean()),
            sa.Column("is_filterable", sa.Boolean()),
            sa.Column("filter_type", sa.String(30)),
        )
        op.create_index("ix_sheet_column_sheet_id", "sheet_column", ["sheet_id"])

    if not _has_table("inventory_group"):
        op.create_table(
            "inventory_group",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("group_key", sa.String(512)),
            sa.Column("identifier", sa.String(255)),
            sa.Column("item_name", sa.String(255)),
            sa.Column("manufacturer", sa.String(255)),
            sa.Column("model", sa.String(255)),
            sa.Column("capacity", sa.String(100)),
            sa.Column("quantity", sa.Float()),
            sa.Column("updated_at", sa.DateTime()),
        )
        op.create_index("ix_inventory_group_group_key", "inventory_group", ["group_key"], unique=True)
        for col in ("identifier", "item_name", "manufacturer", "model", "capacity"):
            op.create_index(f"ix_inventory_group_{col}", "inventory_group", [col])

    if not _has_table("inventory_row"):
        op.create_table(
            "inventory_row",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("excel_file_id", sa.Integer(), sa.ForeignKey("excel_file.id"), nullable=False),
            sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("excel_sheet.id"), nullable=False),
            sa.Column("table_id", sa.Integer(), sa.ForeignKey("detected_table.id")),
            sa.Column("row_number", sa.Integer()),
            sa.Column("data_json", sa.JSON(), nullable=False),
            sa.Column("identifier", sa.String(255)),
            sa.Column("item_name", sa.String(255)),
            sa.Column("manufacturer", sa.String(255)),
            sa.Column("model", sa.String(255)),
            sa.Column("capacity", sa.String(100)),
            sa.Column("quantity", sa.Float()),
            sa.Column("location", sa.String(255)),
            sa.Column("status", sa.String(100)),
            sa.Column("inventory_group_id", sa.Integer(), sa.ForeignKey("inventory_group.id")),
            sa.Column("is_deleted", sa.Boolean()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
        for col in (
            "excel_file_id",
            "sheet_id",
            "identifier",
            "item_name",
            "manufacturer",
            "model",
            "capacity",
            "quantity",
            "location",
            "status",
            "inventory_group_id",
        ):
            op.create_index(f"ix_inventory_row_{col}", "inventory_row", [col])

    if not _has_table("inventory_change"):
        op.create_table(
            "inventory_change",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("inventory_row_id", sa.Integer(), sa.ForeignKey("inventory_row.id")),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("change_type", sa.String(40)),
            sa.Column("field_name", sa.String(255)),
            sa.Column("old_value", sa.Text()),
            sa.Column("new_value", sa.Text()),
            sa.Column("reason", sa.Text()),
            sa.Column("source", sa.String(30)),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_inventory_change_inventory_row_id", "inventory_change", ["inventory_row_id"])

    if not _has_table("stock_out"):
        op.create_table(
            "stock_out",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("inventory_row_id", sa.Integer(), sa.ForeignKey("inventory_row.id")),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("identifier", sa.String(255)),
            sa.Column("item_name", sa.String(255)),
            sa.Column("site", sa.String(120)),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("reason", sa.String(255)),
            sa.Column("created_at", sa.DateTime()),
        )
        for col in ("inventory_row_id", "user_id", "identifier", "site", "created_at"):
            op.create_index(f"ix_stock_out_{col}", "stock_out", [col])

    if not _has_table("stock_request"):
        op.create_table(
            "stock_request",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("inventory_row_id", sa.Integer(), sa.ForeignKey("inventory_row.id")),
            sa.Column("identifier", sa.String(255)),
            sa.Column("item_name", sa.String(255)),
            sa.Column("site", sa.String(120)),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("reason", sa.String(255)),
            sa.Column("source", sa.String(20)),
            sa.Column("status", sa.String(20)),
            sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("approved_at", sa.DateTime()),
            sa.Column("arrived_by_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("arrived_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime()),
        )
        for col in ("inventory_row_id", "identifier", "site", "source", "status", "created_at"):
            op.create_index(f"ix_stock_request_{col}", "stock_request", [col])

    if not _has_table("stock_in"):
        op.create_table(
            "stock_in",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("inventory_row_id", sa.Integer(), sa.ForeignKey("inventory_row.id")),
            sa.Column("stock_request_id", sa.Integer(), sa.ForeignKey("stock_request.id")),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("identifier", sa.String(255)),
            sa.Column("item_name", sa.String(255)),
            sa.Column("site", sa.String(120)),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("reason", sa.String(255)),
            sa.Column("source", sa.String(20)),
            sa.Column("created_at", sa.DateTime()),
        )
        for col in ("inventory_row_id", "stock_request_id", "user_id", "identifier", "site", "source", "created_at"):
            op.create_index(f"ix_stock_in_{col}", "stock_in", [col])

    if not _has_table("chat_session"):
        op.create_table(
            "chat_session",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("title", sa.String(255)),
            sa.Column("excel_file_id", sa.Integer(), sa.ForeignKey("excel_file.id")),
            sa.Column("sheet_id", sa.Integer(), sa.ForeignKey("excel_sheet.id")),
            sa.Column("created_at", sa.DateTime()),
        )

    if not _has_table("chat_message"):
        op.create_table(
            "chat_message",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_session.id")),
            sa.Column("role", sa.String(20)),
            sa.Column("content", sa.Text()),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_chat_message_session_id", "chat_message", ["session_id"])

    if not _has_table("admin_log"):
        op.create_table(
            "admin_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id")),
            sa.Column("action", sa.String(60)),
            sa.Column("target_type", sa.String(40)),
            sa.Column("target_id", sa.Integer()),
            sa.Column("detail", sa.Text()),
            sa.Column("created_at", sa.DateTime()),
        )
        for col in ("user_id", "action", "created_at"):
            op.create_index(f"ix_admin_log_{col}", "admin_log", [col])


def downgrade():
    # 베이스라인은 되돌리지 않는다 (운영 데이터 보호).
    pass
