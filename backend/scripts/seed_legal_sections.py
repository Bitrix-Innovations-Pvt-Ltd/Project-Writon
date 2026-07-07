import asyncio
import json
import os
import sys
from sqlalchemy import text

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine

JSON_PATH = r"c:\Users\Shivam\AppData\Local\Packages\5319275A.WhatsAppDesktop_cv1g1gvanyjgm\LocalState\sessions\4CF60147493A794E110D82926FE4701E9376D4FB\transfers\2026-27\legal_sections (1).json"

async def seed():
    if not os.path.exists(JSON_PATH):
        print(f"Error: JSON file not found at {JSON_PATH}")
        return

    print(f"Loading legal sections from {JSON_PATH}...")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    print(f"Loaded {len(data)} sections. Preparing to upsert...")

    # Filter and format records
    records = []
    for item in data:
        # Check if required fields are present
        legal_code_id = item.get("legal_code_id")
        section_number = item.get("section_number")
        section_text = item.get("section_text")

        if legal_code_id is None or section_number is None or section_text is None:
            continue

        records.append({
            "id": item.get("id"),
            "legal_code_id": int(legal_code_id),
            "section_number": str(section_number).strip(),
            "title": item.get("title"),
            "section_text": str(section_text),
            "embedding": item.get("embedding"),
            "corresponds_to": item.get("corresponds_to")
        })

    print(f"Prepared {len(records)} valid records for insertion.")

    async with engine.begin() as conn:
        # Upsert in chunks to prevent memory/parameter limits
        chunk_size = 500
        total_inserted = 0
        
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            
            # Since ON CONFLICT can be tricky if the IDs are already present but don't match,
            # we specify:
            # - If (legal_code_id, section_number) conflicts, update the section fields.
            # - If we want to preserve ids from the JSON, we can do it.
            # We use a parameterized query for bulk insert.
            await conn.execute(
                text("""
                    INSERT INTO legal_code_sections 
                        (id, legal_code_id, section_number, title, section_text, embedding, corresponds_to)
                    VALUES 
                        (:id, :legal_code_id, :section_number, :title, :section_text, :embedding, :corresponds_to)
                    ON CONFLICT (legal_code_id, section_number) DO UPDATE SET
                        title = EXCLUDED.title,
                        section_text = EXCLUDED.section_text,
                        embedding = EXCLUDED.embedding,
                        corresponds_to = EXCLUDED.corresponds_to;
                """),
                chunk
            )
            total_inserted += len(chunk)
            print(f"Upserted chunk {i//chunk_size + 1}: {total_inserted}/{len(records)} sections")

        # Reset sequence for legal_code_sections table
        seq_res = await conn.execute(text("SELECT pg_get_serial_sequence('legal_code_sections', 'id');"))
        seq_name = seq_res.scalar()
        if seq_name:
            await conn.execute(text(f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM legal_code_sections), 1), true);"))
            print(f"Reset sequence '{seq_name}' to max ID.")
        else:
            await conn.execute(text("SELECT setval('legal_code_sections_id_seq', COALESCE((SELECT MAX(id) FROM legal_code_sections), 1), true);"))
            print("Reset sequence 'legal_code_sections_id_seq' to max ID.")

        print("All sections seeded successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
