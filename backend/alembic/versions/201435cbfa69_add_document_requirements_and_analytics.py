"""add_document_requirements_and_analytics

Revision ID: 201435cbfa69
Revises: 2385b7c97f74
Create Date: 2026-07-05 13:52:12.728612

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '201435cbfa69'
down_revision = '2385b7c97f74'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table('document_requirements',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('court_level', sa.String(), nullable=False),
    sa.Column('subject_matter', sa.String(), nullable=False),
    sa.Column('document_name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('requirement_type', sa.String(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('subject_matter_analytics',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('court_level', sa.String(), nullable=True),
    sa.Column('selected_other', sa.Boolean(), nullable=True),
    sa.Column('case_description_snippet', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    op.drop_table('subject_matter_analytics')
    op.drop_table('document_requirements')
