import asyncio
import os
import sys
from sqlalchemy import text

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine

DOMAIN_MAP = {
    # Core Procedural & Substantive Criminal
    "CrPC": ["criminal", "procedure"],
    "BNSS": ["criminal", "procedure"],
    "IPC": ["criminal", "substantive"],
    "BNS": ["criminal", "substantive"],
    "BSA": ["civil", "criminal", "evidence"],
    "IEA": ["civil", "criminal", "evidence"],
    
    # Core Procedural & Substantive Civil
    "CPC": ["civil", "procedure"],
    "SRA": ["civil", "substantive"],
    "COI": ["constitutional"],
    
    # Newly seeded acts
    "CONTRACT": ["civil", "corporate"],
    "SALE": ["civil", "corporate"],
    "PARTNERSHIP": ["civil", "corporate"],
    "LLP": ["civil", "corporate"],
    "COMPANIES": ["civil", "corporate"],
    "IBC": ["civil", "corporate"],
    "NI": ["civil", "criminal", "corporate"],
    "TPA": ["civil", "property"],
    "REGISTRATION": ["civil", "property"],
    "EASEMENTS": ["civil", "property"],
    "HMA": ["civil", "family"],
    "HSA": ["civil", "family"],
    "MUSLIM": ["civil", "family"],
    
    # Labour
    "WAGES": ["civil", "labour"],
    "IR": ["civil", "labour"],
    "OSH": ["civil", "labour"],
    
    # Tax
    "CGST": ["civil", "tax"],
    "IGST": ["civil", "tax"],
    "ITAX": ["civil", "tax"],
    
    # Others Civil
    "COMPETITION": ["civil", "corporate"],
    "ARBITRATION": ["civil", "corporate"],
    "SARFAESI": ["civil", "corporate", "banking"],
    "RDB": ["civil", "corporate", "banking"],
    "CPA": ["civil", "consumer"],
    "WATER": ["civil", "environment"],
    "AIR": ["civil", "environment"],
    "EPA": ["civil", "environment"],
    "IT": ["civil", "criminal", "cyber"],
    "RTI": ["civil"],
    "LARR": ["civil", "property"],
    
    # Criminal
    "PC": ["criminal", "corruption"],
    "PMLA": ["criminal", "money_laundering"],
    "JJ": ["criminal", "juvenile"],
    "POCSO": ["criminal", "special"],
    "DV": ["civil", "criminal", "family", "special"],
    "POSH": ["civil", "criminal", "special"]
}

async def run():
    async with engine.begin() as conn:
        for short_code, domains in DOMAIN_MAP.items():
            await conn.execute(
                text("UPDATE legal_codes SET domains = :domains WHERE short_code = :code"),
                {"domains": domains, "code": short_code}
            )
            print(f"Updated {short_code} with domains {domains}")
            
if __name__ == "__main__":
    asyncio.run(run())
