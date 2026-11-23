"""Job role responsibilities and an active flag

Revision ID: b8e2f4a06c32
Revises: a7d1e3f95b21
Create Date: 2026-11-23 09:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b8e2f4a06c32'
down_revision: Union[str, None] = 'a7d1e3f95b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_roles', sa.Column(
        'responsibilities', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('job_roles', sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column('job_roles', 'active')
    op.drop_column('job_roles', 'responsibilities')
