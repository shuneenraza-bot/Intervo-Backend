"""initial schema

Revision ID: 86feb2ccec1f
Revises: 
Create Date: 2026-11-12 11:47:57.940974
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '86feb2ccec1f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('domains',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_domains')),
    sa.UniqueConstraint('name', name=op.f('uq_domains_name'))
    )
    op.create_table('evaluation_criteria',
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('weight', sa.Integer(), server_default='1', nullable=False),
    sa.Column('applies_to', sa.String(length=20), server_default='all', nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("applies_to IN ('all', 'technical', 'behavioral')", name=op.f('ck_evaluation_criteria_applies_to')),
    sa.CheckConstraint('weight >= 0', name=op.f('ck_evaluation_criteria_weight')),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_evaluation_criteria'))
    )
    op.create_table('scoring_rules',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('id = 1', name=op.f('ck_scoring_rules_single_row')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scoring_rules'))
    )
    op.create_table('skills',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('aliases', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('related', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('tip', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_skills'))
    )
    op.create_index(op.f('ix_skills_name'), 'skills', ['name'], unique=True)
    op.create_table('users',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('company', sa.String(length=160), nullable=True),
    sa.Column('face_template', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('face_enrolled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_method', sa.String(length=20), nullable=True),
    sa.Column('failed_password_attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('failed_face_attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("last_login_method IS NULL OR last_login_method IN ('password', 'face', 'signup')", name=op.f('ck_users_last_login_method')),
    sa.CheckConstraint("role IN ('candidate', 'employer', 'admin')", name=op.f('ck_users_role')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_table('job_roles',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('domain_id', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], name=op.f('fk_job_roles_domain_id_domains'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_roles'))
    )
    op.create_index(op.f('ix_job_roles_domain_id'), 'job_roles', ['domain_id'], unique=False)
    op.create_table('question_templates',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('skill_id', sa.String(length=40), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('follow_up', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('technical', 'behavioral')", name=op.f('ck_question_templates_type')),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], name=op.f('fk_question_templates_skill_id_skills'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_question_templates'))
    )
    op.create_index(op.f('ix_question_templates_skill_id'), 'question_templates', ['skill_id'], unique=False)
    op.create_index(op.f('ix_question_templates_type'), 'question_templates', ['type'], unique=False)
    op.create_table('candidate_profiles',
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('skills', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('cv', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('target_role_id', sa.String(length=40), nullable=True),
    sa.Column('share_with_employers', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['target_role_id'], ['job_roles.id'], name=op.f('fk_candidate_profiles_target_role_id_job_roles'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_candidate_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_candidate_profiles'))
    )
    op.create_index(op.f('ix_candidate_profiles_target_role_id'), 'candidate_profiles', ['target_role_id'], unique=False)
    op.create_table('interview_sessions',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('candidate_id', sa.String(length=40), nullable=False),
    sa.Column('role_id', sa.String(length=40), nullable=True),
    sa.Column('mode', sa.String(length=20), server_default='text', nullable=False),
    sa.Column('score', sa.Integer(), server_default='0', nullable=False),
    sa.Column('date', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('text', 'voice', 'video')", name=op.f('ck_interview_sessions_mode')),
    sa.CheckConstraint('score BETWEEN 0 AND 100', name=op.f('ck_interview_sessions_score')),
    sa.ForeignKeyConstraint(['candidate_id'], ['users.id'], name=op.f('fk_interview_sessions_candidate_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['job_roles.id'], name=op.f('fk_interview_sessions_role_id_job_roles'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_sessions'))
    )
    op.create_index(op.f('ix_interview_sessions_candidate_id'), 'interview_sessions', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_interview_sessions_date'), 'interview_sessions', ['date'], unique=False)
    op.create_index(op.f('ix_interview_sessions_role_id'), 'interview_sessions', ['role_id'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('employer_id', sa.String(length=40), nullable=True),
    sa.Column('company', sa.String(length=160), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('role_id', sa.String(length=40), nullable=False),
    sa.Column('location', sa.String(length=120), server_default='', nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('level', sa.String(length=60), server_default='', nullable=False),
    sa.Column('type', sa.String(length=60), server_default='', nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
    sa.Column('min_score', sa.Integer(), server_default='0', nullable=False),
    sa.Column('min_match', sa.Integer(), server_default='0', nullable=False),
    sa.Column('success_notes', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('On-site', 'Hybrid', 'Remote')", name=op.f('ck_jobs_mode')),
    sa.CheckConstraint("status IN ('open', 'closed')", name=op.f('ck_jobs_status')),
    sa.CheckConstraint('min_match BETWEEN 0 AND 100', name=op.f('ck_jobs_min_match')),
    sa.CheckConstraint('min_score BETWEEN 0 AND 100', name=op.f('ck_jobs_min_score')),
    sa.ForeignKeyConstraint(['employer_id'], ['users.id'], name=op.f('fk_jobs_employer_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['role_id'], ['job_roles.id'], name=op.f('fk_jobs_role_id_job_roles'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs'))
    )
    op.create_index(op.f('ix_jobs_employer_id'), 'jobs', ['employer_id'], unique=False)
    op.create_index(op.f('ix_jobs_role_id'), 'jobs', ['role_id'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_table('role_skills',
    sa.Column('role_id', sa.String(length=40), nullable=False),
    sa.Column('skill_id', sa.String(length=40), nullable=False),
    sa.Column('weight', sa.Integer(), server_default='2', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('weight BETWEEN 1 AND 3', name=op.f('ck_role_skills_weight')),
    sa.ForeignKeyConstraint(['role_id'], ['job_roles.id'], name=op.f('fk_role_skills_role_id_job_roles'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], name=op.f('fk_role_skills_skill_id_skills'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'skill_id', name=op.f('pk_role_skills'))
    )
    op.create_index(op.f('ix_role_skills_skill_id'), 'role_skills', ['skill_id'], unique=False)
    op.create_table('applications',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('job_id', sa.String(length=40), nullable=False),
    sa.Column('candidate_id', sa.String(length=40), nullable=False),
    sa.Column('consent', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='new', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('new', 'shortlisted', 'declined')", name=op.f('ck_applications_status')),
    sa.ForeignKeyConstraint(['candidate_id'], ['users.id'], name=op.f('fk_applications_candidate_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_applications_job_id_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_applications')),
    sa.UniqueConstraint('job_id', 'candidate_id', name=op.f('uq_applications_job_id'))
    )
    op.create_index(op.f('ix_applications_candidate_id'), 'applications', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_applications_job_id'), 'applications', ['job_id'], unique=False)
    op.create_table('job_skills',
    sa.Column('job_id', sa.String(length=40), nullable=False),
    sa.Column('skill_id', sa.String(length=40), nullable=False),
    sa.Column('weight', sa.Integer(), server_default='2', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('weight BETWEEN 1 AND 3', name=op.f('ck_job_skills_weight')),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], name=op.f('fk_job_skills_job_id_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], name=op.f('fk_job_skills_skill_id_skills'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('job_id', 'skill_id', name=op.f('pk_job_skills'))
    )
    op.create_index(op.f('ix_job_skills_skill_id'), 'job_skills', ['skill_id'], unique=False)
    op.create_table('session_answers',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('session_id', sa.String(length=40), nullable=False),
    sa.Column('skill_id', sa.String(length=40), nullable=True),
    sa.Column('question_id', sa.String(length=40), nullable=True),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('answer', sa.Text(), server_default='', nullable=False),
    sa.Column('score', sa.Integer(), server_default='0', nullable=False),
    sa.Column('criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('indicators', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reason', sa.String(length=20), nullable=True),
    sa.Column('follow_up', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('technical', 'behavioral')", name=op.f('ck_session_answers_type')),
    sa.CheckConstraint('score BETWEEN 0 AND 100', name=op.f('ck_session_answers_score')),
    sa.ForeignKeyConstraint(['question_id'], ['question_templates.id'], name=op.f('fk_session_answers_question_id_question_templates'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_session_answers_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['skill_id'], ['skills.id'], name=op.f('fk_session_answers_skill_id_skills'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session_answers'))
    )
    op.create_index(op.f('ix_session_answers_question_id'), 'session_answers', ['question_id'], unique=False)
    op.create_index(op.f('ix_session_answers_session_id'), 'session_answers', ['session_id'], unique=False)
    op.create_index(op.f('ix_session_answers_skill_id'), 'session_answers', ['skill_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_session_answers_skill_id'), table_name='session_answers')
    op.drop_index(op.f('ix_session_answers_session_id'), table_name='session_answers')
    op.drop_index(op.f('ix_session_answers_question_id'), table_name='session_answers')
    op.drop_table('session_answers')
    op.drop_index(op.f('ix_job_skills_skill_id'), table_name='job_skills')
    op.drop_table('job_skills')
    op.drop_index(op.f('ix_applications_job_id'), table_name='applications')
    op.drop_index(op.f('ix_applications_candidate_id'), table_name='applications')
    op.drop_table('applications')
    op.drop_index(op.f('ix_role_skills_skill_id'), table_name='role_skills')
    op.drop_table('role_skills')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_role_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_employer_id'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_interview_sessions_role_id'), table_name='interview_sessions')
    op.drop_index(op.f('ix_interview_sessions_date'), table_name='interview_sessions')
    op.drop_index(op.f('ix_interview_sessions_candidate_id'), table_name='interview_sessions')
    op.drop_table('interview_sessions')
    op.drop_index(op.f('ix_candidate_profiles_target_role_id'), table_name='candidate_profiles')
    op.drop_table('candidate_profiles')
    op.drop_index(op.f('ix_question_templates_type'), table_name='question_templates')
    op.drop_index(op.f('ix_question_templates_skill_id'), table_name='question_templates')
    op.drop_table('question_templates')
    op.drop_index(op.f('ix_job_roles_domain_id'), table_name='job_roles')
    op.drop_table('job_roles')
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_skills_name'), table_name='skills')
    op.drop_table('skills')
    op.drop_table('scoring_rules')
    op.drop_table('evaluation_criteria')
    op.drop_table('domains')
