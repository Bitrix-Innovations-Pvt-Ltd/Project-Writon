import os
import sys
import time
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv('../.env')

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

# Use standard synchronous psycopg2 adapter
if "asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

print(f"Connecting to DB using sync driver...")
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)

from app.models.judgment import Judgment
from sentence_transformers import SentenceTransformer

def populate():
    print("Loading Legal-BERT model...")
    model = SentenceTransformer('nlpaueb/legal-bert-base-uncased')
    
    print("Fetching judgment IDs...")
    with SessionLocal() as session:
        result = session.execute(select(Judgment.id).where(Judgment.embedding == None).order_by(Judgment.id))
        judgment_ids = result.scalars().all()
        
    total = len(judgment_ids)
    print(f"Need to embed {total} judgments.")
    
    batch_size = 50
    for i in range(0, total, batch_size):
        batch_ids = judgment_ids[i:i+batch_size]
        
        with SessionLocal() as session:
            # Fetch the actual judgments for this batch
            res = session.execute(select(Judgment).where(Judgment.id.in_(batch_ids)))
            batch = res.scalars().all()
            
            texts_to_embed = []
            for j in batch:
                if j.summary or j.holding:
                    text_str = f"{j.petitioner or ''} v. {j.respondent or ''}. {j.summary or ''} {j.holding or ''}"
                else:
                    fallback_text = (j.full_text or '')[:2500]
                    text_str = f"{j.petitioner or ''} v. {j.respondent or ''}. {fallback_text}"
                texts_to_embed.append(text_str)
                
            # Generate dense vectors
            dense_vectors = model.encode(texts_to_embed).tolist()
            
            # Update embedding
            for idx, j in enumerate(batch):
                session.execute(
                    text("UPDATE judgments SET embedding = :emb WHERE id = :id"),
                    {"emb": str(dense_vectors[idx]), "id": j.id}
                )
            session.commit()
            
        print(f"Embedded batch {i//batch_size + 1}/{(total + batch_size - 1)//batch_size}", flush=True)
        
    print("Populating TSVECTOR search_vector for all rows (including full_text)...")
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE judgments 
            SET search_vector = to_tsvector('english', 
                coalesce(petitioner, '') || ' ' || 
                coalesce(respondent, '') || ' ' || 
                coalesce(summary, '') || ' ' || 
                coalesce(holding, '') || ' ' ||
                coalesce(full_text, '')
            )
        """))
    print("Indexing complete!")

if __name__ == "__main__":
    populate()
