"""Shortlist flow: new application statuses, status history and notifications

Revision ID: e5b9c3a71f08
Revises: d4a8f1c62e07
Create Date: 2026-11-20 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5b9c3a71f08'
down_revision: Union[str, None] = 'd4a8f1c62e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_STATUSES = "status IN ('applied', 'shortlisted', 'accepted', 'declined_by_candidate', 'not_progressing')"
OLD_STATUSES = "status IN ('new', 'shortlisted', 'declined')"


def upgrade() -> None:
    op.drop_constraint(op.f('ck_applications_status'), 'applications', type_='check')
    op.alter_column('applications', 'status', type_=sa.String(length=30), existing_nullable=False)
    # new -> applied; an old employer "declined" is the new "not_progressing".
    op.execute("UPDATE applications SET status = 'applied' WHERE status = 'new'")
    op.execute("UPDATE applications SET status = 'not_progressing' WHERE status = 'declined'")
    op.alter_column('applications', 'status', server_default='applied')
    op.create_check_constraint(op.f('ck_applications_status'), 'applications', NEW_STATUSES)

    op.create_table(
        'application_status_history',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('application_id', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('employer_message', sa.Text(), nullable=True),
        sa.Column('candidate_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'],
                                name=op.f('fk_application_status_history_application_id_applications'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_application_status_history')),
    )
    op.create_index(op.f('ix_application_status_history_application_id'), 'application_status_history', ['application_id'])
    # One history row per existing application: its application date and current status.
    op.execute(
        "INSERT INTO application_status_history (id, application_id, status, created_at) "
        "SELECT 'hist-' || substr(md5(id), 1, 12), id, status, created_at FROM applications"
    )

    op.create_table(
        'notifications',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('user_id', sa.String(length=40), nullable=False),
        sa.Column('type', sa.String(length=30), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), server_default='', nullable=False),
        sa.Column('link', sa.String(length=200), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("type IN ('shortlisted', 'not_progressing', 'accepted', 'declined')", name=op.f('ck_notifications_type')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_application_status_history_application_id'), table_name='application_status_history')
    op.drop_table('application_status_history')

    op.drop_constraint(op.f('ck_applications_status'), 'applications', type_='check')
    op.execute("UPDATE applications SET status = 'new' WHERE status = 'applied'")
    op.execute("UPDATE applications SET status = 'shortlisted' WHERE status = 'accepted'")
    op.execute("UPDATE applications SET status = 'declined' WHERE status IN ('not_progressing', 'declined_by_candidate')")
    op.alter_column('applications', 'status', type_=sa.String(length=20), server_default='new', existing_nullable=False)
    op.create_check_constraint(op.f('ck_applications_status'), 'applications', OLD_STATUSES)
