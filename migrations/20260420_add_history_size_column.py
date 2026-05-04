"""Add history_size column to codesubflag_challenge

Revision ID: 20260420_add_history_size_column
Revises:
Create Date: 2026-04-20 00:00:00.000000

"""
import sqlalchemy as sa

from CTFd.plugins.migrations import get_all_tables, get_columns_for_table

revision = "20260420_add_history_size_column"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(op=None):
    # Fresh install: tables don't exist yet — create_all() runs after upgrade()
    # and will build them at the current schema, so nothing to migrate.
    if "codesubflag_challenge" not in get_all_tables(op=op):
        return
    columns = get_columns_for_table(
        op=op, table_name="codesubflag_challenge", names_only=True
    )
    if "history_size" not in columns:
        # server_default lets the DB backfill existing rows on ADD COLUMN; we
        # drop it afterwards so new rows follow the Python-side default instead.
        op.add_column(
            "codesubflag_challenge",
            sa.Column(
                "history_size",
                sa.Integer(),
                nullable=True,
                server_default="10",
            ),
        )
        with op.batch_alter_table("codesubflag_challenge") as batch:
            batch.alter_column("history_size", server_default=None)


def downgrade(op=None):
    if "codesubflag_challenge" not in get_all_tables(op=op):
        return
    columns = get_columns_for_table(
        op=op, table_name="codesubflag_challenge", names_only=True
    )
    if "history_size" in columns:
        op.drop_column("codesubflag_challenge", "history_size")
