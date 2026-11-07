"""Recognize databases stamped by the older alembic/ migration tree.

Revision ef30e62b36e8 was a no-op migration. Its tables were created by
application startup, so this bridge performs no DDL.
"""

revision = 'ef30e62b36e8'
down_revision = '20261103_120000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
