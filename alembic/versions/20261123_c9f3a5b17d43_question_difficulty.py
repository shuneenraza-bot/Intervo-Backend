"""Question template difficulty

Revision ID: c9f3a5b17d43
Revises: b8e2f4a06c32
Create Date: 2026-11-23 14:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9f3a5b17d43'
down_revision: Union[str, None] = 'b8e2f4a06c32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('question_templates', sa.Column('difficulty', sa.String(length=10), nullable=False, server_default='medium'))
    op.create_check_constraint(op.f('ck_question_templates_difficulty'), 'question_templates',
                               "difficulty IN ('easy', 'medium', 'hard')")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_question_templates_difficulty'), 'question_templates', type_='check')
    op.drop_column('question_templates', 'difficulty')
