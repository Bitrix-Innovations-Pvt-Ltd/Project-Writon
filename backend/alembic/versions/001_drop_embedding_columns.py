"""drop embedding columns from judgments and judgment_chunks

Revision ID: 001
Revises:
Create Date: 2026-07-03

Embeddings are now stored entirely in Pinecone (hybrid search).
This migration removes the pgvector columns from the DB to reclaim space
on the Neon free tier.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the embedding column from judgments table
    op.drop_column('judgments', 'embedding')
    # Drop the embedding column from judgment_chunks table
    op.drop_column('judgment_chunks', 'embedding')


def downgrade() -> None:
    # Re-add embedding columns (requires pgvector extension to be enabled)
    op.add_column(
        'judgments',
        sa.Column('embedding', sa.TEXT(), nullable=True)  # placeholder; restore Vector(1536) manually if needed
    )
    op.add_column(
        'judgment_chunks',
        sa.Column('embedding', sa.TEXT(), nullable=True)
    )
