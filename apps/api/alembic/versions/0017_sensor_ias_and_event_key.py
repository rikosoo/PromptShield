"""painel de sensores: IAs escolhidas em cada máquina e o vínculo do evento com a chave (sensor) que o enviou

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("ias", sa.ARRAY(sa.String()), nullable=False, server_default="{}"))
    # qual chave (logo, qual sensor) enviou o evento: permite ver, por máquina, de quais IAs chegaram eventos de verdade
    op.add_column("events", sa.Column("api_key_id", sa.Uuid()))
    op.create_index("ix_events_api_key_time", "events", ["api_key_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_events_api_key_time", "events")
    op.drop_column("events", "api_key_id")
    op.drop_column("devices", "ias")
