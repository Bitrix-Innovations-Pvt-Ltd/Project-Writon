import asyncio
import os
import time
import sys

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env variables — use absolute path so it works from any CWD
_root_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env')
from dotenv import load_dotenv
load_dotenv(_root_env)

# Initialize Pinecone
from pinecone import Pinecone, ServerlessSpec

pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY"))
index_name = "writon-judgments"

# Auto-create the index if it doesn't exist
existing = [idx.name for idx in pc.list_indexes()]
if index_name not in existing:
    print(f"Index '{index_name}' not found. Creating it now...")
    pc.create_index(
        name=index_name,
        dimension=768,           # Legal-BERT output size
        metric="dotproduct",     # Required for native hybrid search
        spec=ServerlessSpec(cloud="aws", region="us-east-1")  # Only free-tier region on Pinecone
    )
    print(f"Index '{index_name}' created. Waiting for it to be ready...")
    time.sleep(10)
else:
    print(f"Index '{index_name}' already exists. Skipping creation.")

index = pc.Index(index_name)

# Database setup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
if "?" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split("?")[0]

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": True})
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

from app.models.judgment import Judgment


async def fetch_and_index():
    # Load pre-trained BM25
    from pinecone_text.sparse import BM25Encoder
    print("Loading BM25 from saved model...")
    bm25 = BM25Encoder()
    bm25_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bm25_model.json")
    bm25.load(bm25_path)
    print("BM25 loaded.")

    # Load Legal-BERT
    from sentence_transformers import SentenceTransformer
    print("Loading Legal-BERT model...")
    model = SentenceTransformer('nlpaueb/legal-bert-base-uncased')
    print("Legal-BERT loaded.")

    batch_size = 50
    offset = 0
    total_processed = 0

    while True:
        print(f"Fetching batch (offset={offset})...")
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    Judgment.id, Judgment.petitioner, Judgment.respondent, 
                    Judgment.summary, Judgment.holding, Judgment.year, 
                    Judgment.case_type, Judgment.acts_cited, Judgment.full_text
                ).order_by(Judgment.id).limit(batch_size).offset(offset)
            )
            batch = result.all()

        if not batch:
            break
            
        print(f"Processing batch of {len(batch)} judgments...")
        
        # 0. Check if batch already exists
        batch_ids = [str(j.id) for j in batch]
        try:
            fetched = index.fetch(ids=batch_ids)
            existing_ids = set(fetched.get('vectors', {}).keys())
        except Exception:
            existing_ids = set()

        missing_batch = [j for j in batch if str(j.id) not in existing_ids]

        if not missing_batch:
            print(f"[{total_processed // batch_size + 1}] Skipped {len(batch)} vectors (already exist)")
            offset += batch_size
            total_processed += len(batch)
            continue

        # Split texts for different models
        dense_texts = []
        sparse_texts = []
        for j in missing_batch:
            # AI Dense Search: Summary
            d_text = f"{j.petitioner or ''} v. {j.respondent or ''}. {j.summary or ''} {j.holding or ''}"
            dense_texts.append(d_text.strip() or ".")
            
            # Keyword Sparse Search: Full Text
            s_text = f"{j.petitioner or ''} v. {j.respondent or ''}. {j.summary or ''} {j.full_text or ''}"
            sparse_texts.append(s_text.strip() or ".")

        # 1. Generate Dense Vectors for missing ones only
        dense_vectors = model.encode(dense_texts, show_progress_bar=False).tolist()

        # 2. Generate Sparse Vectors
        sparse_vectors_raw = bm25.encode_documents(sparse_texts)
        sparse_vectors = []
        for sv in sparse_vectors_raw:
            if isinstance(sv, dict) and 'indices' in sv and len(sv['indices']) > 2048:
                # Truncate to top 2048 elements by weight to avoid Pinecone size limits
                items = list(zip(sv['indices'], sv['values']))
                items.sort(key=lambda x: x[1], reverse=True)
                items = items[:2048]
                sv['indices'] = [x[0] for x in items]
                sv['values'] = [x[1] for x in items]
            sparse_vectors.append(sv)

        # 3. Construct Payload
        upsert_payload = []
        for idx, j in enumerate(missing_batch):
            metadata = {
                "year": j.year if j.year else 0,
                "category": j.case_type if j.case_type else "General",
                "case_type": j.case_type if j.case_type else "General",
                "acts_cited": j.acts_cited if j.acts_cited else [],
                "title": f"{j.petitioner or 'Unknown'} v. {j.respondent or 'Unknown'}"
            }
            upsert_payload.append({
                "id": str(j.id),
                "values": dense_vectors[idx],
                "sparse_values": sparse_vectors[idx],
                "metadata": metadata
            })

        # Upsert batch to Pinecone
        try:
            index.upsert(vectors=upsert_payload)
            print(f"[{total_processed // batch_size + 1}] Upserted {len(batch)} vectors (total so far: {total_processed + len(batch)})")
        except Exception as e:
            print(f"Error upserting batch {total_processed // batch_size + 1}: {e}")

        offset += batch_size
        total_processed += len(batch)
        time.sleep(0.3)

    print("\nIndexing complete!")
    stats = index.describe_index_stats()
    print(f"Total vectors in Pinecone: {stats.total_vector_count}")


if __name__ == "__main__":
    asyncio.run(fetch_and_index())
