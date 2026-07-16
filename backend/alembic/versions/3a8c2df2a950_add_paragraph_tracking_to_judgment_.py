"""add paragraph tracking to judgment_chunks

Revision ID: 3a8c2df2a950
Revises: 717d20c72fc7
Create Date: 2026-07-15 17:35:32.079328

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3a8c2df2a950'
down_revision = '717d20c72fc7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('judgment_chunks', sa.Column('paragraph_number_start', sa.Integer(), nullable=True))
    op.add_column('judgment_chunks', sa.Column('paragraph_number_end', sa.Integer(), nullable=True))
    op.add_column('judgment_chunks', sa.Column('chunking_method', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('judgment_chunks', 'chunking_method')
    op.drop_column('judgment_chunks', 'paragraph_number_end')
    op.drop_column('judgment_chunks', 'paragraph_number_start')
