"""계정 확장(이메일/사이트/비활성화), 출고 티켓·담당자·취소, 시리얼 추적(DiskUnit)

Revision ID: 0002_accounts_units_tickets
Revises: 0001_baseline
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_accounts_units_tickets"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name):
    return name in _inspector().get_table_names()


def _has_column(table, column):
    return column in {c["name"] for c in _inspector().get_columns(table)}


def _has_index(table, name):
    return name in {i["name"] for i in _inspector().get_indexes(table)}


def _add_column(table, column):
    if not _has_column(table, column.name):
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def _add_index(table, name, columns, unique=False):
    if not _has_index(table, name):
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    # ---- user ------------------------------------------------------------
    _add_column("user", sa.Column("email", sa.String(255)))
    _add_column("user", sa.Column("site", sa.String(120)))
    _add_column("user", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    _add_column(
        "user",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_index("user", "ix_user_site", ["site"])

    # ---- stock_out -------------------------------------------------------
    _add_column("stock_out", sa.Column("ticket_no", sa.String(80)))
    _add_column("stock_out", sa.Column("handler", sa.String(80)))
    _add_column("stock_out", sa.Column("serials", sa.Text()))
    _add_column("stock_out", sa.Column("cancelled_at", sa.DateTime()))
    _add_column(
        "stock_out",
        sa.Column(
            "cancelled_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_stock_out_cancelled_by_id_user"),
        ),
    )
    _add_column("stock_out", sa.Column("cancel_reason", sa.String(255)))
    _add_index("stock_out", "ix_stock_out_ticket_no", ["ticket_no"])
    _add_index("stock_out", "ix_stock_out_cancelled_at", ["cancelled_at"])

    # ---- stock_in --------------------------------------------------------
    _add_column("stock_in", sa.Column("serials", sa.Text()))

    # ---- disk_unit -------------------------------------------------------
    if not _has_table("disk_unit"):
        op.create_table(
            "disk_unit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("serial", sa.String(120), nullable=False),
            sa.Column("identifier", sa.String(255)),
            sa.Column("item_name", sa.String(255)),
            sa.Column("inventory_row_id", sa.Integer(), sa.ForeignKey("inventory_row.id")),
            sa.Column("status", sa.String(20), nullable=False, server_default="in_stock"),
            sa.Column("site", sa.String(120)),
            sa.Column("stock_in_id", sa.Integer(), sa.ForeignKey("stock_in.id")),
            sa.Column("stock_out_id", sa.Integer(), sa.ForeignKey("stock_out.id")),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
        op.create_index("ix_disk_unit_serial", "disk_unit", ["serial"], unique=True)
        for col in ("identifier", "inventory_row_id", "status", "site"):
            op.create_index(f"ix_disk_unit_{col}", "disk_unit", [col])


def downgrade():
    if _has_table("disk_unit"):
        op.drop_table("disk_unit")

    with op.batch_alter_table("stock_in") as batch:
        if _has_column("stock_in", "serials"):
            batch.drop_column("serials")

    with op.batch_alter_table("stock_out") as batch:
        for col in ("cancel_reason", "cancelled_by_id", "cancelled_at", "serials", "handler", "ticket_no"):
            if _has_column("stock_out", col):
                batch.drop_column(col)

    with op.batch_alter_table("user") as batch:
        for col in ("must_change_password", "active", "site", "email"):
            if _has_column("user", col):
                batch.drop_column(col)
