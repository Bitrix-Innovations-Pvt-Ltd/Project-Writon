"""add_subject_matters

Revision ID: 2385b7c97f74
Revises: 68500f0fb3d2
Create Date: 2026-07-05 13:28:44.911145

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2385b7c97f74'
down_revision = '68500f0fb3d2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table('subject_matters',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('court_level', sa.String(), nullable=False),
    sa.Column('tribunal_name', sa.String(), nullable=True),
    sa.Column('matter_name', sa.String(), nullable=False),
    sa.Column('applicable_doc_types', postgresql.ARRAY(sa.String()), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    op.drop_table('subject_matters')
