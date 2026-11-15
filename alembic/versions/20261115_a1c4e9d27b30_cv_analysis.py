"""cv analysis columns on candidate_profiles

Revision ID: a1c4e9d27b30
Revises: 86feb2ccec1f
Create Date: 2026-11-15 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1c4e9d27b30'
down_revision: Union[str, None] = '86feb2ccec1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidate_profiles', sa.Column('parsed_cv', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('candidate_profiles', sa.Column('cv_text', sa.Text(), nullable=True))
    op.add_column('candidate_profiles', sa.Column('cv_file_name', sa.String(length=255), nullable=True))
    op.add_column('candidate_profiles', sa.Column('cv_provider', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('candidate_profiles', 'cv_provider')
    op.drop_column('candidate_profiles', 'cv_file_name')
    op.drop_column('candidate_profiles', 'cv_text')
    op.drop_column('candidate_profiles', 'parsed_cv')
