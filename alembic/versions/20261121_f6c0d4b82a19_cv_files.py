"""Original CV files and the CV snapshot kept on each application

Revision ID: f6c0d4b82a19
Revises: e5b9c3a71f08
Create Date: 2026-11-21 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f6c0d4b82a19'
down_revision: Union[str, None] = 'e5b9c3a71f08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cv_files',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('user_id', sa.String(length=40), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('storage_name', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_cv_files_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cv_files')),
        sa.UniqueConstraint('storage_name', name=op.f('uq_cv_files_storage_name')),
    )
    op.create_index(op.f('ix_cv_files_user_id'), 'cv_files', ['user_id'])

    op.add_column('candidate_profiles', sa.Column('cv_file_id', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_candidate_profiles_cv_file_id'), 'candidate_profiles', ['cv_file_id'])
    op.create_foreign_key(op.f('fk_candidate_profiles_cv_file_id_cv_files'), 'candidate_profiles', 'cv_files',
                          ['cv_file_id'], ['id'], ondelete='SET NULL')

    op.add_column('applications', sa.Column('cv_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('applications', sa.Column('cv_file_id', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_applications_cv_file_id'), 'applications', ['cv_file_id'])
    op.create_foreign_key(op.f('fk_applications_cv_file_id_cv_files'), 'applications', 'cv_files',
                          ['cv_file_id'], ['id'], ondelete='SET NULL')

    # Applications made before this change get a snapshot of the candidate's current CV
    # (parsed data only: files uploaded earlier were never stored).
    op.execute(
        "UPDATE applications a SET cv_snapshot = jsonb_build_object("
        "'parsed', p.parsed_cv, 'summary', p.cv, 'skills', to_jsonb(p.skills), 'fileName', p.cv_file_name) "
        "FROM candidate_profiles p WHERE p.user_id = a.candidate_id AND p.parsed_cv IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint(op.f('fk_applications_cv_file_id_cv_files'), 'applications', type_='foreignkey')
    op.drop_index(op.f('ix_applications_cv_file_id'), table_name='applications')
    op.drop_column('applications', 'cv_file_id')
    op.drop_column('applications', 'cv_snapshot')
    op.drop_constraint(op.f('fk_candidate_profiles_cv_file_id_cv_files'), 'candidate_profiles', type_='foreignkey')
    op.drop_index(op.f('ix_candidate_profiles_cv_file_id'), table_name='candidate_profiles')
    op.drop_column('candidate_profiles', 'cv_file_id')
    op.drop_index(op.f('ix_cv_files_user_id'), table_name='cv_files')
    op.drop_table('cv_files')
