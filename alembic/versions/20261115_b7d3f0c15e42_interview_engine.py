"""interview engine: session status, job link, evaluation tips/provider, follow-up fields

Revision ID: b7d3f0c15e42
Revises: a1c4e9d27b30
Create Date: 2026-11-15 14:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7d3f0c15e42'
down_revision: Union[str, None] = 'a1c4e9d27b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing sessions came from POST /sessions, so they are finished.
    op.add_column('interview_sessions', sa.Column('status', sa.String(length=20), server_default='completed', nullable=False))
    op.add_column('interview_sessions', sa.Column('job_id', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_interview_sessions_status'), 'interview_sessions', ['status'], unique=False)
    op.create_index(op.f('ix_interview_sessions_job_id'), 'interview_sessions', ['job_id'], unique=False)
    op.create_foreign_key(op.f('fk_interview_sessions_job_id_jobs'), 'interview_sessions', 'jobs', ['job_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint(op.f('ck_interview_sessions_status'), 'interview_sessions', "status IN ('in_progress', 'completed')")

    op.add_column('session_answers', sa.Column('keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('session_answers', sa.Column('tips', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('session_answers', sa.Column('provider', sa.String(length=20), nullable=True))
    op.add_column('session_answers', sa.Column('needs_follow_up', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('session_answers', sa.Column('follow_up_question', sa.Text(), nullable=True))
    op.add_column('session_answers', sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True))

    op.add_column('question_templates', sa.Column('source', sa.String(length=20), server_default='admin', nullable=False))


def downgrade() -> None:
    op.drop_column('question_templates', 'source')
    op.drop_column('session_answers', 'answered_at')
    op.drop_column('session_answers', 'follow_up_question')
    op.drop_column('session_answers', 'needs_follow_up')
    op.drop_column('session_answers', 'provider')
    op.drop_column('session_answers', 'tips')
    op.drop_column('session_answers', 'keywords')
    op.drop_constraint(op.f('ck_interview_sessions_status'), 'interview_sessions', type_='check')
    op.drop_constraint(op.f('fk_interview_sessions_job_id_jobs'), 'interview_sessions', type_='foreignkey')
    op.drop_index(op.f('ix_interview_sessions_job_id'), table_name='interview_sessions')
    op.drop_index(op.f('ix_interview_sessions_status'), table_name='interview_sessions')
    op.drop_column('interview_sessions', 'job_id')
    op.drop_column('interview_sessions', 'status')
