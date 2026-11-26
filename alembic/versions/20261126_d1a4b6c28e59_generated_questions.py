"""Generated questions: template status and candidate, question origin on answers

Revision ID: d1a4b6c28e59
Revises: c9f3a5b17d43
Create Date: 2026-11-26 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd1a4b6c28e59'
down_revision: Union[str, None] = 'c9f3a5b17d43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('question_templates', sa.Column('status', sa.String(length=20), nullable=False, server_default='approved'))
    op.add_column('question_templates', sa.Column('candidate_id', sa.String(length=40), nullable=True))
    op.create_check_constraint(op.f('ck_question_templates_status'), 'question_templates',
                               "status IN ('approved', 'generated')")
    op.create_foreign_key(op.f('fk_question_templates_candidate_id_users'), 'question_templates', 'users',
                          ['candidate_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_question_templates_status'), 'question_templates', ['status'])
    op.create_index(op.f('ix_question_templates_candidate_id'), 'question_templates', ['candidate_id'])

    op.add_column('session_answers', sa.Column('question_origin', sa.String(length=10), nullable=False,
                                               server_default='template'))
    op.create_check_constraint(op.f('ck_session_answers_question_origin'), 'session_answers',
                               "question_origin IN ('generated', 'template')")

    # Questions generated before this change now wait for approval too. Each is linked to the first
    # candidate who was asked it, and those answers are marked as generated.
    op.execute("UPDATE question_templates SET status = 'generated' WHERE source = 'generated'")
    op.execute("""
        UPDATE question_templates SET candidate_id = (
            SELECT s.candidate_id FROM session_answers a JOIN interview_sessions s ON s.id = a.session_id
            WHERE a.question_id = question_templates.id ORDER BY s.date LIMIT 1
        ) WHERE source = 'generated'
    """)
    op.execute("""
        UPDATE session_answers SET question_origin = 'generated'
        WHERE question_id IN (SELECT id FROM question_templates WHERE source = 'generated')
    """)


def downgrade() -> None:
    op.drop_constraint(op.f('ck_session_answers_question_origin'), 'session_answers', type_='check')
    op.drop_column('session_answers', 'question_origin')
    op.drop_index(op.f('ix_question_templates_candidate_id'), table_name='question_templates')
    op.drop_index(op.f('ix_question_templates_status'), table_name='question_templates')
    op.drop_constraint(op.f('fk_question_templates_candidate_id_users'), 'question_templates', type_='foreignkey')
    op.drop_constraint(op.f('ck_question_templates_status'), 'question_templates', type_='check')
    op.drop_column('question_templates', 'candidate_id')
    op.drop_column('question_templates', 'status')
