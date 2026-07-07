"""add_embedding_and_document_types

Revision ID: 68500f0fb3d2
Revises: 001
Create Date: 2026-07-05 12:44:06.997629

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '68500f0fb3d2'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create document_types table
    op.create_table('document_types',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('court_level', sa.String(), nullable=False),
        sa.Column('tribunal_name', sa.String(), nullable=True),
        sa.Column('doc_type_name', sa.String(), nullable=False),
        sa.Column('statutory_basis', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # 2. Add embedding column to judgment_chunks
    op.add_column('judgment_chunks', sa.Column('embedding', Vector(768), nullable=True))


def downgrade() -> None:
    op.drop_column('judgment_chunks', 'embedding')
    op.drop_table('document_types')
