"""atualizacoes assistidas (aviso de versao, download aprovado) e pacotes de regras de deteccao (recebidos, modo sombra, ativos)

Revision ID: 0024
Revises: 0023

Tabelas do SERVIDOR inteiro (como license_state): sem tenant e sem RLS. Só o administrador altera, pela API (com auditoria).
"""
import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

APP_ROLE = "promptshield_app"


def upgrade() -> None:
    op.create_table(
        "update_state",
        sa.Column("kind", sa.String(8), primary_key=True),
        sa.Column("notice", sa.Text(), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("security", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("file", sa.String(120), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="available"),
        sa.Column("error", sa.String(300)),
        sa.Column("approved_by", sa.String(320)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('app','rules')", name="ck_update_state_kind"),
        sa.CheckConstraint("status IN ('available','approved','ready','staged','failed')", name="ck_update_state_status"),
    )
    op.create_table(
        "rule_packs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version", sa.String(40), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(10), nullable=False, server_default="staged"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_by", sa.String(320)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('staged','shadow','active','retired')", name="ck_rule_packs_status"),
    )
    op.execute("CREATE UNIQUE INDEX uq_rule_packs_one_live ON rule_packs ((1)) WHERE status IN ('shadow','active')")      # no máximo UM pacote vale por vez
    op.create_table(
        "rule_pack_hits",
        sa.Column("pack_id", sa.Uuid(), sa.ForeignKey("rule_packs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("rule_id", sa.String(64), primary_key=True),
        sa.Column("mode", sa.String(10), primary_key=True),
        sa.Column("hits", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON update_state, rule_packs, rule_pack_hits TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("rule_pack_hits")
    op.execute("DROP INDEX IF EXISTS uq_rule_packs_one_live")
    op.drop_table("rule_packs")
    op.drop_table("update_state")
