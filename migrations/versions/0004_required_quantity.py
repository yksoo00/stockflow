"""품목별 필수수량 — inventory_row.required_quantity + 기존 시트에 '필수수량' 열 채우기

Revision ID: 0004_required_quantity
Revises: 0003_user_sites_text
Create Date: 2026-10-02

출고 후 재고가 필수수량보다 적어지면 모자란 만큼 입고요청을 자동 생성한다 (예전엔 전 품목 2개 고정).
이미 올라와 있는 시트도 화면에서 바로 고칠 수 있도록:
  - 엑셀에 '필수수량' 열이 있으면 그 값을 required_quantity 로 옮기고
  - 없으면 시트 맨 끝에 '필수수량' 열을 만들고
  - 빈 칸은 기본값(LOW_STOCK_THRESHOLD + 1, 기본 2 — 예전 동작과 같은 값)으로 채운다.
"""

import os

import sqlalchemy as sa
from alembic import op

from app.services.inventory.normalize import REQUIRED_QUANTITY_COLUMN, infer_field, to_number

revision = "0004_required_quantity"
down_revision = "0003_user_sites_text"
branch_labels = None
depends_on = None


sheet_column = sa.table(
    "sheet_column",
    sa.column("id", sa.Integer),
    sa.column("sheet_id", sa.Integer),
    sa.column("table_id", sa.Integer),
    sa.column("column_index", sa.Integer),
    sa.column("original_name", sa.String),
    sa.column("normalized_name", sa.String),
    sa.column("data_type", sa.String),
    sa.column("is_searchable", sa.Boolean),
    sa.column("is_filterable", sa.Boolean),
    sa.column("filter_type", sa.String),
)

inventory_row = sa.table(
    "inventory_row",
    sa.column("id", sa.Integer),
    sa.column("sheet_id", sa.Integer),
    sa.column("table_id", sa.Integer),
    sa.column("data_json", sa.JSON),
    sa.column("required_quantity", sa.Float),
    sa.column("is_deleted", sa.Boolean),
)


def _has_column(table, column):
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _default_required():
    try:
        return float(os.getenv("LOW_STOCK_THRESHOLD", "1")) + 1
    except ValueError:
        return 2.0


def upgrade():
    if not _has_column("inventory_row", "required_quantity"):
        with op.batch_alter_table("inventory_row") as batch:
            batch.add_column(sa.Column("required_quantity", sa.Float()))

    conn = op.get_bind()
    default = _default_required()
    default_cell = int(default) if default.is_integer() else default

    sheet_ids = [
        sid
        for (sid,) in conn.execute(
            sa.select(inventory_row.c.sheet_id)
            .where(sa.or_(inventory_row.c.is_deleted.is_(None), inventory_row.c.is_deleted == sa.false()))
            .distinct()
        )
    ]

    for sheet_id in sheet_ids:
        columns = conn.execute(
            sa.select(
                sheet_column.c.original_name, sheet_column.c.table_id, sheet_column.c.column_index
            ).where(sheet_column.c.sheet_id == sheet_id)
        ).fetchall()

        name = next(
            (c.original_name for c in columns if infer_field(c.original_name or "") == "required_quantity"),
            None,
        )
        rows = conn.execute(
            sa.select(inventory_row.c.id, inventory_row.c.table_id, inventory_row.c.data_json).where(
                inventory_row.c.sheet_id == sheet_id,
                sa.or_(inventory_row.c.is_deleted.is_(None), inventory_row.c.is_deleted == sa.false()),
            )
        ).fetchall()

        if name is None:
            name = REQUIRED_QUANTITY_COLUMN
            table_ids = [c.table_id for c in columns if c.table_id]
            conn.execute(
                sheet_column.insert().values(
                    sheet_id=sheet_id,
                    table_id=min(table_ids) if table_ids else rows[0].table_id,
                    column_index=max([c.column_index or 0 for c in columns] or [0]) + 1,
                    original_name=name,
                    normalized_name="required_quantity",
                    data_type="number",
                    is_searchable=True,
                    is_filterable=True,
                    filter_type="range",
                )
            )

        for row in rows:
            data = dict(row.data_json or {})
            value = to_number(data.get(name))
            values = {"required_quantity": value}
            if value is None:
                data[name] = default_cell
                values = {"required_quantity": default, "data_json": data}
            conn.execute(inventory_row.update().where(inventory_row.c.id == row.id).values(**values))


def downgrade():
    # 추가한 '필수수량' 열/값은 사용자 데이터가 됐을 수 있어 남겨두고, 정규화 컬럼만 지운다.
    with op.batch_alter_table("inventory_row") as batch:
        batch.drop_column("required_quantity")
