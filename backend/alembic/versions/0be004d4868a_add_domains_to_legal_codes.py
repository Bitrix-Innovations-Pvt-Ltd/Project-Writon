"""add_domains_to_legal_codes

Revision ID: 0be004d4868a
Revises: 3a8c2df2a950
Create Date: 2026-07-18 17:01:59.753319

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0be004d4868a'
down_revision: Union[str, None] = '3a8c2df2a950'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('legal_codes', sa.Column('domains', postgresql.ARRAY(sa.String()), nullable=True))


def downgrade() -> None:
    op.drop_column('legal_codes', 'domains')
