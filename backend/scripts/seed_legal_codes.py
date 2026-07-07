import asyncio
import os
import sys
from sqlalchemy import text

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine

legal_codes = [
    {
        "id": 1,
        "code_name": "Bharatiya Nyaya Sanhita",
        "short_code": "BNS",
        "year_enacted": 2023,
        "status": "active",
        "replaced_by_id": None
    },
    {
        "id": 2,
        "code_name": "Bharatiya Nagarik Suraksha Sanhita",
        "short_code": "BNSS",
        "year_enacted": 2023,
        "status": "active",
        "replaced_by_id": None
    },
    {
        "id": 3,
        "code_name": "Bharatiya Sakshya Adhiniyam",
        "short_code": "BSA",
        "year_enacted": 2023,
        "status": "active",
        "replaced_by_id": None
    },
    {
        "id": 4,
        "code_name": "Indian Penal Code",
        "short_code": "IPC",
        "year_enacted": 1860,
        "status": "repealed",
        "replaced_by_id": 1
    },
    {
        "id": 5,
        "code_name": "Code of Criminal Procedure",
        "short_code": "CrPC",
        "year_enacted": 1973,
        "status": "repealed",
        "replaced_by_id": 2
    },
    {
        "id": 6,
        "code_name": "Indian Evidence Act",
        "short_code": "IEA",
        "year_enacted": 1872,
        "status": "repealed",
        "replaced_by_id": 3
    },
    {
        "id": 7,
        "code_name": "Constitution of India",
        "short_code": "COI",
        "year_enacted": 1950,
        "status": "active",
        "replaced_by_id": None
    }
]

async def seed():
    async with engine.begin() as conn:
        print("Upserting legal codes...")
        
        # We run the inserts in order of ID to make sure foreign key constraints are not violated 
        # (e.g. ID 4 references ID 1, so ID 1 must exist first)
        for code in legal_codes:
            await conn.execute(
                text("""
                    INSERT INTO legal_codes 
                        (id, code_name, short_code, year_enacted, status, replaced_by_id)
                    VALUES 
                        (:id, :code_name, :short_code, :year_enacted, :status, :replaced_by_id)
                    ON CONFLICT (id) DO UPDATE SET
                        code_name = EXCLUDED.code_name,
                        short_code = EXCLUDED.short_code,
                        year_enacted = EXCLUDED.year_enacted,
                        status = EXCLUDED.status,
                        replaced_by_id = EXCLUDED.replaced_by_id;
                """),
                code
            )
            print(f"Upserted {code['short_code']} (ID: {code['id']})")
        
        # Reset the auto-increment sequence so that Postgres doesn't complain on future inserts
        seq_res = await conn.execute(text("SELECT pg_get_serial_sequence('legal_codes', 'id');"))
        seq_name = seq_res.scalar()
        if seq_name:
            await conn.execute(text(f"SELECT setval('{seq_name}', COALESCE((SELECT MAX(id) FROM legal_codes), 1), true);"))
            print(f"Reset sequence '{seq_name}' to max ID.")
        else:
            await conn.execute(text("SELECT setval('legal_codes_id_seq', COALESCE((SELECT MAX(id) FROM legal_codes), 1), true);"))
            print("Reset sequence 'legal_codes_id_seq' to max ID.")
            
        print("Seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
