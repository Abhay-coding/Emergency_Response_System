"""Add password security fields missing from older user tables.

Revision ID: 20261107_1200
Revises: 38bb7c6c8cb8
"""

from alembic import op
import sqlalchemy as sa


revision = "20261107_1200"
down_revision = "38bb7c6c8cb8"
branch_labels = None
depends_on = None


def _has_column(name: str) -> bool:
    return name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("users")}


def upgrade() -> None:
    if not _has_column("password_hash_version"):
        op.add_column(
            "users",
            sa.Column("password_hash_version", sa.Integer(), nullable=False, server_default="2"),
        )
    if not _has_column("must_reset_password"):
        op.add_column(
            "users",
            sa.Column("must_reset_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    # SQLite requires a table rebuild to drop columns. Keeping these security
    # fields during downgrade avoids destructive rewrites of user records.
    pass
