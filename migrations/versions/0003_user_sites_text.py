"""담당 사이트 여러 개 — user.site 를 String(120) → Text

Revision ID: 0003_user_sites_text
Revises: 0002_accounts_units_tickets
Create Date: 2026-09-16

쉼표 구분 목록을 저장하므로 길이 제한을 없앤다. 기존 값(사이트 1개)은 그대로 유효하다.
Text 컬럼에는 (MySQL 에서) prefix 없는 인덱스를 만들 수 없어 ix_user_site 는 제거한다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_user_sites_text"
down_revision = "0002_accounts_units_tickets"
branch_labels = None
depends_on = None


def _has_index(table, name):
    return name in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    with op.batch_alter_table("user") as batch:
        if _has_index("user", "ix_user_site"):
            batch.drop_index("ix_user_site")
        batch.alter_column("site", existing_type=sa.String(120), type_=sa.Text(), existing_nullable=True)


def downgrade():
    with op.batch_alter_table("user") as batch:
        batch.alter_column("site", existing_type=sa.Text(), type_=sa.String(120), existing_nullable=True)
        batch.create_index("ix_user_site", ["site"])
