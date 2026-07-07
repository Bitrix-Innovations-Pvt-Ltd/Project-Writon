import asyncio
import os
import sys
from sqlalchemy import text

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine
from app.models.document_type import DocumentType

seeds = [
    # --- 1. Supreme Court of India ---
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Writ Petition (Art. 32)", "statutory_basis": "Art. 32", "category": "Constitutional", "sort_order": 1},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Special Leave Petition (SLP)", "statutory_basis": "Art. 136", "category": "Constitutional", "sort_order": 2},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Transfer Petition", "statutory_basis": "Art. 139A", "category": "Constitutional", "sort_order": 3},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Review Petition", "statutory_basis": "Art. 137", "category": "Constitutional", "sort_order": 4},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Curative Petition", "statutory_basis": "Rupa Ashok Hurra guidelines", "category": "Constitutional", "sort_order": 5},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Original Suit", "statutory_basis": "Art. 131 (Centre-State/State-State disputes)", "category": "Civil", "sort_order": 6},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Contempt Petition", "statutory_basis": "Contempt of Courts Act, 1971", "category": "Civil/Criminal", "sort_order": 7},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Civil Appeal", "statutory_basis": "Art. 133", "category": "Civil", "sort_order": 8},
    {"court_level": "supreme", "tribunal_name": None, "doc_type_name": "Criminal Appeal", "statutory_basis": "Art. 134", "category": "Criminal", "sort_order": 9},

    # --- 2. High Court ---
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Writ Petition (Civil)", "statutory_basis": "Art. 226", "category": "Constitutional/Civil", "sort_order": 1},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Writ Petition (Criminal)", "statutory_basis": "Art. 226", "category": "Constitutional/Criminal", "sort_order": 2},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Public Interest Litigation (PIL)", "statutory_basis": "Art. 226", "category": "Constitutional", "sort_order": 3},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Criminal Appeal", "statutory_basis": "CrPC/BNSS", "category": "Criminal", "sort_order": 4},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Civil Appeal", "statutory_basis": "CPC", "category": "Civil", "sort_order": 5},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Criminal Revision", "statutory_basis": "Sec. 397 CrPC / Sec. 438 BNSS", "category": "Criminal", "sort_order": 6},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Civil Revision", "statutory_basis": "Sec. 115 CPC", "category": "Civil", "sort_order": 7},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Bail Application", "statutory_basis": "Sec. 439 CrPC / Sec. 483 BNSS", "category": "Criminal", "sort_order": 8},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Anticipatory Bail Application", "statutory_basis": "Sec. 438 CrPC / Sec. 482 BNSS", "category": "Criminal", "sort_order": 9},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Quashing Petition (482 CrPC/528 BNSS)", "statutory_basis": "Inherent powers", "category": "Criminal", "sort_order": 10},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Second Appeal", "statutory_basis": "Sec. 100 CPC", "category": "Civil", "sort_order": 11},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Letters Patent Appeal (LPA)", "statutory_basis": "High Court-specific", "category": "Civil", "sort_order": 12},
    {"court_level": "high", "tribunal_name": None, "doc_type_name": "Contempt Petition", "statutory_basis": "Contempt of Courts Act", "category": "Civil/Criminal", "sort_order": 13},

    # --- 3. District / Sessions Court ---
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Civil Suit (Money Recovery)", "statutory_basis": "CPC", "category": "Civil", "sort_order": 1},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Civil Suit (Specific Performance)", "statutory_basis": "Specific Relief Act", "category": "Civil", "sort_order": 2},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Civil Suit (Partition)", "statutory_basis": "CPC", "category": "Civil", "sort_order": 3},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Civil Suit (Injunction)", "statutory_basis": "Order 39 CPC", "category": "Civil", "sort_order": 4},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Written Statement / Reply", "statutory_basis": "CPC", "category": "Civil", "sort_order": 5},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Criminal Complaint (Sec. 200 CrPC / 223 BNSS)", "statutory_basis": "Private complaint", "category": "Criminal", "sort_order": 6},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Bail Application (Sessions)", "statutory_basis": "Sec. 439 CrPC / Sec. 483 BNSS", "category": "Criminal", "sort_order": 7},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Charge Sheet Reply / Discharge Application", "statutory_basis": "Sec. 227 CrPC / Sec. 250 BNSS", "category": "Criminal", "sort_order": 8},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Execution Petition", "statutory_basis": "Order 21 CPC", "category": "Civil", "sort_order": 9},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Cheque Bounce Complaint", "statutory_basis": "Sec. 138 NI Act", "category": "Criminal/Financial", "sort_order": 10},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Domestic Violence Application", "statutory_basis": "Protection of Women from DV Act", "category": "Civil/Criminal", "sort_order": 11},
    {"court_level": "district", "tribunal_name": None, "doc_type_name": "Maintenance Application", "statutory_basis": "Sec. 125 CrPC / Sec. 144 BNSS", "category": "Civil/Family", "sort_order": 12},

    # --- 4. Tribunals ---
    # NCLT
    {"court_level": "tribunal", "tribunal_name": "National Company Law Tribunal (NCLT)", "doc_type_name": "Insolvency Application (Sec. 7/9/10 IBC)", "statutory_basis": "Sec. 7/9/10 IBC", "category": "Insolvency", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "National Company Law Tribunal (NCLT)", "doc_type_name": "Company Petition", "statutory_basis": "Companies Act, 2013", "category": "Corporate", "sort_order": 2},
    {"court_level": "tribunal", "tribunal_name": "National Company Law Tribunal (NCLT)", "doc_type_name": "Winding-up Petition", "statutory_basis": "Companies Act, 2013", "category": "Corporate", "sort_order": 3},
    
    # NCLAT
    {"court_level": "tribunal", "tribunal_name": "National Company Law Appellate Tribunal (NCLAT)", "doc_type_name": "Company Appeal", "statutory_basis": "Companies Act / IBC", "category": "Corporate", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "National Company Law Appellate Tribunal (NCLAT)", "doc_type_name": "Competition Appeal", "statutory_basis": "Competition Act, 2002", "category": "Regulatory", "sort_order": 2},
    
    # NGT
    {"court_level": "tribunal", "tribunal_name": "National Green Tribunal (NGT)", "doc_type_name": "Environmental Compensation Application", "statutory_basis": "NGT Act, 2010", "category": "Environmental", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "National Green Tribunal (NGT)", "doc_type_name": "Appeal against Environmental Clearance", "statutory_basis": "NGT Act, 2010", "category": "Environmental", "sort_order": 2},
    
    # ITAT
    {"court_level": "tribunal", "tribunal_name": "Income Tax Appellate Tribunal (ITAT)", "doc_type_name": "Tax Appeal", "statutory_basis": "Income Tax Act, 1961", "category": "Taxation", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "Income Tax Appellate Tribunal (ITAT)", "doc_type_name": "Rectification Application", "statutory_basis": "Income Tax Act, 1961", "category": "Taxation", "sort_order": 2},
    
    # CAT
    {"court_level": "tribunal", "tribunal_name": "Central Administrative Tribunal (CAT)", "doc_type_name": "Service Matter Original Application", "statutory_basis": "Administrative Tribunals Act, 1985", "category": "Service", "sort_order": 1},
    
    # CESTAT
    {"court_level": "tribunal", "tribunal_name": "Customs, Excise & Service Tax Appellate Tribunal (CESTAT)", "doc_type_name": "Indirect Tax Appeal", "statutory_basis": "Customs/Excise/GST Acts", "category": "Taxation", "sort_order": 1},
    
    # DRT
    {"court_level": "tribunal", "tribunal_name": "Debts Recovery Tribunal (DRT) / DRAT", "doc_type_name": "Recovery Application under SARFAESI/RDBA", "statutory_basis": "SARFAESI/RDBA Act", "category": "Financial", "sort_order": 1},
    
    # NCDRC
    {"court_level": "tribunal", "tribunal_name": "National Consumer Disputes Redressal Commission (NCDRC)", "doc_type_name": "Consumer Complaint (Consumer Protection Act)", "statutory_basis": "Consumer Protection Act, 2019", "category": "Consumer", "sort_order": 1},
    
    # RERA
    {"court_level": "tribunal", "tribunal_name": "Real Estate Regulatory Authority (RERA) / Appellate Tribunal", "doc_type_name": "Complaint against Builder/Developer", "statutory_basis": "RERA Act, 2016", "category": "Real Estate", "sort_order": 1},
    
    # Defaults/Fallbacks for other tribunals
    {"court_level": "tribunal", "tribunal_name": "Securities Appellate Tribunal (SAT)", "doc_type_name": "Appellate Petition", "statutory_basis": "SEBI/PFRDA/IRDAI", "category": "Corporate", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "Telecom Disputes Settlement & Appellate Tribunal (TDSAT)", "doc_type_name": "Telecom Dispute Petition", "statutory_basis": "TRAI Act", "category": "Telecom", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "Armed Forces Tribunal (AFT)", "doc_type_name": "Service Application", "statutory_basis": "AFT Act, 2007", "category": "Service", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "Appellate Tribunal for Electricity (APTEL)", "doc_type_name": "Electricity Appeal", "statutory_basis": "Electricity Act, 2003", "category": "Energy", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "Central Government Industrial Tribunal (CGIT)", "doc_type_name": "Industrial Dispute Reference", "statutory_basis": "Industrial Disputes Act, 1947", "category": "Labour", "sort_order": 1},
    {"court_level": "tribunal", "tribunal_name": "Competition Commission of India (CCI)", "doc_type_name": "Information on Anti-Competitive Agreement", "statutory_basis": "Competition Act, 2002", "category": "Regulatory", "sort_order": 1},

    # --- 5. Special Courts (represented under court_level = 'special_court') ---
    # Family Courts
    {"court_level": "special_court", "tribunal_name": "Family Courts", "doc_type_name": "Divorce Petition", "statutory_basis": "Family Courts Act, 1984", "category": "Family", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "Family Courts", "doc_type_name": "Custody Petition", "statutory_basis": "Family Courts Act, 1984", "category": "Family", "sort_order": 2},
    {"court_level": "special_court", "tribunal_name": "Family Courts", "doc_type_name": "Maintenance Petition", "statutory_basis": "Family Courts Act, 1984", "category": "Family", "sort_order": 3},
    
    # POCSO Courts
    {"court_level": "special_court", "tribunal_name": "POCSO Courts", "doc_type_name": "Charge framing application", "statutory_basis": "POCSO Act, 2012", "category": "Criminal", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "POCSO Courts", "doc_type_name": "Bail Application (POCSO-specific)", "statutory_basis": "POCSO Act, 2012", "category": "Criminal", "sort_order": 2},
    
    # NDPS Special Courts
    {"court_level": "special_court", "tribunal_name": "NDPS Special Courts", "doc_type_name": "Bail Application (Sec. 37 NDPS)", "statutory_basis": "NDPS Act, 1985", "category": "Criminal", "sort_order": 1},
    
    # PMLA Special Courts
    {"court_level": "special_court", "tribunal_name": "Prevention of Money Laundering Act (PMLA) Special Courts", "doc_type_name": "Bail Application (Sec. 45 PMLA)", "statutory_basis": "PMLA, 2002", "category": "Criminal", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "Prevention of Money Laundering Act (PMLA) Special Courts", "doc_type_name": "ECIR Quashing", "statutory_basis": "PMLA, 2002", "category": "Criminal", "sort_order": 2},
    
    # CBI Courts
    {"court_level": "special_court", "tribunal_name": "CBI Courts (Special Courts)", "doc_type_name": "Discharge Application", "statutory_basis": "CBI / CrPC", "category": "Criminal", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "CBI Courts (Special Courts)", "doc_type_name": "Bail Application", "statutory_basis": "CBI / CrPC", "category": "Criminal", "sort_order": 2},
    
    # Fast Track Courts
    {"court_level": "special_court", "tribunal_name": "Fast Track Courts / Fast Track Special Courts (FTSC)", "doc_type_name": "Expedited Trial Application", "statutory_basis": "State Scheme", "category": "Criminal", "sort_order": 1},
    
    # Commercial Courts
    {"court_level": "special_court", "tribunal_name": "Commercial Courts", "doc_type_name": "Commercial Suit (Commercial Courts Act)", "statutory_basis": "Commercial Courts Act, 2015", "category": "Commercial", "sort_order": 1},

    # Labour Courts (State)
    {"court_level": "special_court", "tribunal_name": "Labour Courts / Industrial Tribunals (State)", "doc_type_name": "Industrial Dispute Reference", "statutory_basis": "Industrial Disputes Act, 1947", "category": "Labour", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "Labour Courts / Industrial Tribunals (State)", "doc_type_name": "Reinstatement Application", "statutory_basis": "Industrial Disputes Act, 1947", "category": "Labour", "sort_order": 2},

    # Motor Accidents Claims Tribunal (MACT)
    {"court_level": "special_court", "tribunal_name": "Motor Accidents Claims Tribunal (MACT)", "doc_type_name": "Motor Accident Claim Petition", "statutory_basis": "Motor Vehicles Act, 1988", "category": "Civil", "sort_order": 1},

    # Defaults for other Special Courts
    {"court_level": "special_court", "tribunal_name": "NIA Special Courts", "doc_type_name": "Discharge / Bail Petition", "statutory_basis": "NIA Act, 2008", "category": "Criminal", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "Special Courts for MPs/MLAs", "doc_type_name": "Discharge / Bail Petition", "statutory_basis": "Supreme Court Directions", "category": "Criminal", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "Anti-Corruption / Vigilance Courts", "doc_type_name": "Discharge / Bail Petition", "statutory_basis": "Prevention of Corruption Act, 1988", "category": "Criminal", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "Juvenile Justice Boards", "doc_type_name": "Bail / Inquiry Petition", "statutory_basis": "Juvenile Justice Act, 2015", "category": "Juvenile", "sort_order": 1},
    {"court_level": "special_court", "tribunal_name": "Lok Adalats / Gram Nyayalayas", "doc_type_name": "Dispute Resolution Settlement", "statutory_basis": "Legal Services Authorities Act", "category": "ADR", "sort_order": 1}
]

async def seed():
    async with engine.begin() as conn:
        print("Clearing old document types...")
        await conn.execute(text("DELETE FROM document_types;"))
        
        print(f"Inserting {len(seeds)} document types...")
        for s in seeds:
            await conn.execute(
                text("""
                    INSERT INTO document_types (court_level, tribunal_name, doc_type_name, statutory_basis, category, sort_order)
                    VALUES (:court_level, :tribunal_name, :doc_type_name, :statutory_basis, :category, :sort_order)
                """),
                s
            )
        print("Seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
