"""Encrypt stored face templates; one response per shortlist

Revision ID: a7d1e3f95b21
Revises: f6c0d4b82a19
Create Date: 2026-11-22 10:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a7d1e3f95b21'
down_revision: Union[str, None] = 'f6c0d4b82a19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TERMINAL = "status IN ('accepted', 'declined_by_candidate')"


def _rewrite_faces(convert) -> None:
    from sqlalchemy.dialects.postgresql import JSONB

    bind = op.get_bind()
    users = sa.table('users', sa.column('id', sa.String), sa.column('face_template', JSONB))
    for user_id, template in bind.execute(sa.select(users.c.id, users.c.face_template)).all():
        if template is None:
            continue
        new = convert(template)
        if new != template:
            bind.execute(users.update().where(users.c.id == user_id).values(face_template=new))


def upgrade() -> None:
    # 1. Face templates become ciphertext in the database.
    from app.services.face_crypto import encrypt_template

    _rewrite_faces(encrypt_template)

    # 2. At most one accepted / declined row per application. Keep the first answer if a duplicate exists.
    op.execute(
        "DELETE FROM application_status_history h USING application_status_history k "
        f"WHERE h.application_id = k.application_id AND h.{TERMINAL} AND k.{TERMINAL} "
        "AND (h.created_at, h.id) > (k.created_at, k.id)"
    )
    op.create_index(
        'uq_application_one_response', 'application_status_history', ['application_id'],
        unique=True, postgresql_where=sa.text(TERMINAL),
    )


def downgrade() -> None:
    op.drop_index('uq_application_one_response', table_name='application_status_history')
    from app.services.face_crypto import decrypt_template

    _rewrite_faces(decrypt_template)
