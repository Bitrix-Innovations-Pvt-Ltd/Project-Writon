import os
import psycopg2
from dotenv import load_dotenv

# Load the root .env file
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path)

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set. Please check your .env file.")

def execute_safe(cursor, statement, description):
    print(f"{description}...")
    try:
        cursor.execute(statement)
        print("Success.")
    except Exception as e:
        print(f"Failed (continuing): {e}")

def init_db():
    print("Connecting to Neon PostgreSQL...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()

    try:
        execute_safe(cursor, "CREATE EXTENSION IF NOT EXISTS vector;", "Enabling pgvector extension")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                clerk_id TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                full_name TEXT,
                plan TEXT DEFAULT 'free',
                credits_remaining INT DEFAULT 5,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            );
        """, "Creating 'users' table")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                razorpay_sub_id TEXT UNIQUE,
                plan_name TEXT,
                status TEXT,
                starts_at TIMESTAMPTZ,
                ends_at TIMESTAMPTZ
            );
        """, "Creating 'subscriptions' table")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS payments (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID REFERENCES users(id),
                razorpay_order_id TEXT UNIQUE,
                razorpay_payment_id TEXT,
                amount_paise INT,
                currency TEXT DEFAULT 'INR',
                status TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """, "Creating 'payments' table")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS drafts (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                title TEXT,
                case_type TEXT,
                court TEXT,
                form_data JSONB,
                draft_html TEXT,
                draft_text TEXT,
                citation_ids BIGINT[],
                status TEXT DEFAULT 'draft',
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            );
        """, "Creating 'drafts' table")

        execute_safe(cursor, "CREATE INDEX IF NOT EXISTS idx_drafts_user ON drafts(user_id);", "Creating index idx_drafts_user")
        execute_safe(cursor, "CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);", "Creating index idx_drafts_status")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS uploaded_docs (
                id BIGSERIAL PRIMARY KEY,
                draft_id BIGINT REFERENCES drafts(id) ON DELETE CASCADE,
                user_id UUID REFERENCES users(id),
                original_filename TEXT,
                r2_key TEXT,
                doc_type TEXT,
                ocr_text TEXT,
                verify_status TEXT,
                verify_reason TEXT,
                uploaded_at TIMESTAMPTZ DEFAULT now()
            );
        """, "Creating 'uploaded_docs' table")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS judgments (
                id BIGSERIAL PRIMARY KEY,
                case_number TEXT,
                case_type TEXT,
                year INTEGER,
                judgment_date TEXT,
                bench TEXT[],
                petitioner TEXT,
                respondent TEXT,
                acts_cited TEXT[],
                cases_cited TEXT[],
                full_text TEXT,
                content_hash TEXT UNIQUE,
                pdf_s3_key TEXT,
                summary TEXT,
                holding TEXT,
                embedding VECTOR(1536)
            );
        """, "Creating 'judgments' table")
        
        execute_safe(cursor, """
            DO $$
            BEGIN
                BEGIN
                    ALTER TABLE judgments
                    ADD COLUMN search_vector TSVECTOR
                    GENERATED ALWAYS AS (
                        to_tsvector('english',
                            coalesce(title,'') || ' ' ||
                            coalesce(summary,'') || ' ' ||
                            coalesce(holding,'') || ' ' ||
                            coalesce(full_text,'')
                        )
                    ) STORED;
                EXCEPTION
                    WHEN duplicate_column THEN RAISE NOTICE 'column search_vector already exists';
                    WHEN undefined_column THEN
                        ALTER TABLE judgments
                        ADD COLUMN search_vector TSVECTOR
                        GENERATED ALWAYS AS (
                            to_tsvector('english',
                                coalesce(summary,'') || ' ' ||
                                coalesce(holding,'') || ' ' ||
                                coalesce(full_text,'')
                            )
                        ) STORED;
                END;
            END $$;
        """, "Adding 'search_vector' column to judgments")

        execute_safe(cursor, "CREATE INDEX IF NOT EXISTS idx_judgments_fts ON judgments USING GIN(search_vector);", "Creating GIN index on judgments")
        
        # Semantic embedding column for judgments is already included in the CREATE TABLE above if it didn't exist.
        # But if the table existed without it, we should add it:
        execute_safe(cursor, """
            ALTER TABLE judgments ADD COLUMN IF NOT EXISTS embedding VECTOR(1536);
        """, "Adding 'embedding' column to judgments")
        
        execute_safe(cursor, "CREATE INDEX IF NOT EXISTS idx_judgments_embedding ON judgments USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);", "Creating ivfflat index on judgments")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS judgment_chunks (
                id BIGSERIAL PRIMARY KEY,
                judgment_id BIGINT REFERENCES judgments(id) ON DELETE CASCADE,
                chunk_index INT,
                chunk_text TEXT,
                embedding VECTOR(1536),
                page_number INT
            );
        """, "Creating 'judgment_chunks' table")

        execute_safe(cursor, "CREATE INDEX IF NOT EXISTS idx_judgment_chunks_embedding ON judgment_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);", "Creating ivfflat index on judgment_chunks")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS search_logs (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID REFERENCES users(id),
                query TEXT,
                search_type TEXT,
                result_count INT,
                clicked_judgment_id BIGINT REFERENCES judgments(id),
                searched_at TIMESTAMPTZ DEFAULT now()
            );
        """, "Creating 'search_logs' table")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS legal_codes (
                id BIGSERIAL PRIMARY KEY,
                code_name TEXT NOT NULL,
                short_code TEXT NOT NULL,
                year_enacted INT,
                status TEXT DEFAULT 'active',
                replaced_by_id BIGINT REFERENCES legal_codes(id)
            );
        """, "Creating 'legal_codes' table")

        execute_safe(cursor, """
            CREATE TABLE IF NOT EXISTS legal_code_sections (
                id BIGSERIAL PRIMARY KEY,
                legal_code_id BIGINT REFERENCES legal_codes(id) ON DELETE CASCADE,
                section_number TEXT NOT NULL,
                title TEXT,
                section_text TEXT NOT NULL,
                embedding VECTOR(1536),
                corresponds_to TEXT,
                UNIQUE(legal_code_id, section_number)
            );
        """, "Creating 'legal_code_sections' table")

        execute_safe(cursor, "CREATE INDEX IF NOT EXISTS idx_lcs_embedding ON legal_code_sections USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);", "Creating ivfflat index on legal_code_sections")
        execute_safe(cursor, "CREATE INDEX IF NOT EXISTS idx_lcs_section_num ON legal_code_sections(section_number);", "Creating index on legal_code_sections")

        print("\nDatabase initialization script completed!")

    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    init_db()
