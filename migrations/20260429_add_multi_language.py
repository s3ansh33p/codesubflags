"""Add multi-language support to codesubflag challenges

Revision ID: 20260429_add_multi_language
Revises: 20260420_add_history_size_column
Create Date: 2026-04-29 00:00:00.000000

"""
import sqlalchemy as sa

from CTFd.plugins.migrations import get_all_tables, get_columns_for_table

revision = "20260429_add_multi_language"
down_revision = "20260420_add_history_size_column"
branch_labels = None
depends_on = None


def upgrade(op=None):
    tables = get_all_tables(op=op)

    if "codesubflag_challenge_languages" not in tables:
        op.create_table(
            "codesubflag_challenge_languages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "challenge_id",
                sa.Integer(),
                sa.ForeignKey("challenges.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("language", sa.String(length=64), nullable=False),
            sa.Column("version", sa.String(length=32), nullable=False),
            sa.Column("run_file", sa.String(length=128), nullable=False),
            sa.Column("data_file", sa.String(length=128), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"),
            sa.Index("ix_csf_lang_challenge", "challenge_id"),
            sa.UniqueConstraint(
                "challenge_id", "language", "version",
                name="uq_csf_lang_challenge_lv",
            ),
        )

    attempt_columns = get_columns_for_table(
        op=op, table_name="codesubflag_attempt", names_only=True
    )
    if "language" not in attempt_columns:
        op.add_column(
            "codesubflag_attempt",
            sa.Column("language", sa.String(length=64), nullable=True),
        )
    if "version" not in attempt_columns:
        op.add_column(
            "codesubflag_attempt",
            sa.Column("version", sa.String(length=32), nullable=True),
        )

    # Backfill: every existing codesubflag challenge gets a single python/3.10.0
    # row mirroring its current run_file/data_file. Skip any challenge that
    # already has a language row (re-run safety).
    bind = op.get_bind()
    challenges = bind.execute(sa.text(
        "SELECT id, run_file, data_file FROM codesubflag_challenge"
    )).fetchall()
    for row in challenges:
        chal_id = row[0]
        run_file = row[1]
        data_file = row[2]
        existing = bind.execute(
            sa.text(
                "SELECT 1 FROM codesubflag_challenge_languages "
                "WHERE challenge_id = :cid LIMIT 1"
            ),
            {"cid": chal_id},
        ).first()
        if existing:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO codesubflag_challenge_languages "
                "(challenge_id, language, version, run_file, data_file, sort_order) "
                "VALUES (:cid, :lang, :ver, :rf, :df, 0)"
            ),
            {
                "cid": chal_id,
                "lang": "python",
                "ver": "3.10.0",
                "rf": run_file or "main.py",
                "df": data_file,
            },
        )


def downgrade(op=None):
    tables = get_all_tables(op=op)
    if "codesubflag_challenge_languages" in tables:
        op.drop_table("codesubflag_challenge_languages")

    attempt_columns = get_columns_for_table(
        op=op, table_name="codesubflag_attempt", names_only=True
    )
    if "version" in attempt_columns:
        op.drop_column("codesubflag_attempt", "version")
    if "language" in attempt_columns:
        op.drop_column("codesubflag_attempt", "language")
