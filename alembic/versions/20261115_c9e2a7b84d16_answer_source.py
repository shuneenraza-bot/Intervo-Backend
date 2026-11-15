"""session_answers.answer_source: how an answer was given (text, voice or video)

Revision ID: c9e2a7b84d16
Revises: b7d3f0c15e42
Create Date: 2026-11-15 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c9e2a7b84d16'
down_revision: Union[str, None] = 'b7d3f0c15e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('session_answers', sa.Column('answer_source', sa.String(length=10), server_default='text', nullable=False))
    # Earlier answers that carry video indicators were video-mode answers.
    op.execute("UPDATE session_answers SET answer_source = 'video' WHERE indicators IS NOT NULL")
    op.create_check_constraint(op.f('ck_session_answers_answer_source'), 'session_answers', "answer_source IN ('text', 'voice', 'video')")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_session_answers_answer_source'), 'session_answers', type_='check')
    op.drop_column('session_answers', 'answer_source')
