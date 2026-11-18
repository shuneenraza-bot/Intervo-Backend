"""Employers see only the CV match: drop jobs.min_score and the suitability weights

Revision ID: d4a8f1c62e07
Revises: c9e2a7b84d16
Create Date: 2026-11-18 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4a8f1c62e07'
down_revision: Union[str, None] = 'c9e2a7b84d16'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(op.f('ck_jobs_min_score'), 'jobs', type_='check')
    op.drop_column('jobs', 'min_score')
    # The suitability weights no longer exist; remove them from the single scoring_rules row.
    op.execute("UPDATE scoring_rules SET data = data - 'suitability' WHERE data ? 'suitability'")


def downgrade() -> None:
    op.add_column('jobs', sa.Column('min_score', sa.Integer(), server_default='0', nullable=False))
    op.create_check_constraint(op.f('ck_jobs_min_score'), 'jobs', 'min_score BETWEEN 0 AND 100')
    op.execute(
        "UPDATE scoring_rules SET data = data || '{\"suitability\": {\"cv\": 40, \"interview\": 45, \"consistency\": 15}}'::jsonb"
    )
