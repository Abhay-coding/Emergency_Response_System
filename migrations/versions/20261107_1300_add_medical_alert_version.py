"""Add optimistic-lock version to medical alerts."""
from alembic import op
import sqlalchemy as sa

revision = "20261107_1300"
down_revision = "20261107_1200"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("medical_alerts")}
    if "version" not in columns:
        op.add_column("medical_alerts", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

def downgrade():
    pass
