import asyncio
import os
import sys
from sqlalchemy import text

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine

data = {
  "supreme": {
    "subject_matters": [
      {
        "matter_name": "Constitutional / Fundamental Rights",
        "applicable_doc_types": ["Writ Petition (Art. 32)"]
      },
      {
        "matter_name": "Special Leave (Criminal)",
        "applicable_doc_types": ["Special Leave Petition", "Criminal Appeal"]
      },
      {
        "matter_name": "Special Leave (Civil)",
        "applicable_doc_types": ["Special Leave Petition", "Civil Appeal"]
      },
      {
        "matter_name": "Centre-State / Inter-State Dispute",
        "applicable_doc_types": ["Original Suit (Art. 131)"]
      },
      {
        "matter_name": "Service Law",
        "applicable_doc_types": ["Special Leave Petition", "Writ Petition (Art. 32)"]
      },
      {
        "matter_name": "Environmental",
        "applicable_doc_types": ["Special Leave Petition", "Writ Petition (Art. 32)"]
      },
      {
        "matter_name": "Tax (Direct/Indirect)",
        "applicable_doc_types": ["Special Leave Petition"]
      },
      {
        "matter_name": "Election Dispute",
        "applicable_doc_types": ["Writ Petition (Art. 32)"]
      },
      {
        "matter_name": "Contempt of Court",
        "applicable_doc_types": ["Contempt Petition"]
      },
      {
        "matter_name": "Case Transfer",
        "applicable_doc_types": ["Transfer Petition"]
      },
      {
        "matter_name": "Review of Judgment",
        "applicable_doc_types": ["Review Petition"]
      },
      {
        "matter_name": "Post-Review Relief",
        "applicable_doc_types": ["Curative Petition"]
      },
      {
        "matter_name": "Other",
        "applicable_doc_types": ["Writ Petition (Art. 32)", "Special Leave Petition"]
      }
    ]
  },

  "high": {
    "subject_matters": [
      {
        "matter_name": "Writ / Fundamental Rights",
        "applicable_doc_types": ["Writ Petition (Civil)", "Writ Petition (Criminal)"]
      },
      {
        "matter_name": "Public Interest Litigation",
        "applicable_doc_types": ["Public Interest Litigation (PIL)"]
      },
      {
        "matter_name": "Property / Land Dispute",
        "applicable_doc_types": ["Civil Revision", "Civil Appeal", "Second Appeal"]
      },
      {
        "matter_name": "Service / Employment",
        "applicable_doc_types": ["Writ Petition (Civil)", "Civil Appeal"]
      },
      {
        "matter_name": "Matrimonial / Family",
        "applicable_doc_types": ["Civil Appeal", "Letters Patent Appeal (LPA)"]
      },
      {
        "matter_name": "Criminal Matter",
        "applicable_doc_types": ["Criminal Appeal", "Criminal Revision", "Quashing Petition (482 CrPC/528 BNSS)"]
      },
      {
        "matter_name": "Bail / Anticipatory Bail",
        "applicable_doc_types": ["Bail Application", "Anticipatory Bail Application"]
      },
      {
        "matter_name": "Company / NCLT Appeal",
        "applicable_doc_types": ["Civil Appeal"]
      },
      {
        "matter_name": "Income Tax / GST",
        "applicable_doc_types": ["Civil Appeal", "Writ Petition (Civil)"]
      },
      {
        "matter_name": "Consumer Complaint",
        "applicable_doc_types": ["Civil Appeal"]
      },
      {
        "matter_name": "Environmental",
        "applicable_doc_types": ["Writ Petition (Civil)", "Public Interest Litigation (PIL)"]
      },
      {
        "matter_name": "Motor Accident",
        "applicable_doc_types": ["Civil Appeal"]
      },
      {
        "matter_name": "Contempt of Court",
        "applicable_doc_types": ["Contempt Petition"]
      },
      {
        "matter_name": "Other",
        "applicable_doc_types": ["Writ Petition (Civil)", "Civil Appeal"]
      }
    ]
  },

  "district": {
    "subject_matters": [
      {
        "matter_name": "Property / Land Dispute",
        "applicable_doc_types": ["Civil Suit (Partition)", "Civil Suit (Specific Performance)", "Civil Suit (Injunction)"]
      },
      {
        "matter_name": "Consumer Complaint",
        "applicable_doc_types": ["Civil Suit (Money Recovery)"]
      },
      {
        "matter_name": "Cheque Dishonour (NI Act)",
        "applicable_doc_types": ["Cheque Bounce Complaint"]
      },
      {
        "matter_name": "Matrimonial / Family",
        "applicable_doc_types": ["Maintenance Application", "Domestic Violence Application"]
      },
      {
        "matter_name": "Motor Accident",
        "applicable_doc_types": ["Civil Suit (Money Recovery)"],
        "note": "Only if no separate MACT constituted in the district; otherwise route to Tribunal"
      },
      {
        "matter_name": "Bail / Anticipatory Bail",
        "applicable_doc_types": ["Bail Application (Sessions)"]
      },
      {
        "matter_name": "Criminal Matter",
        "applicable_doc_types": ["Criminal Complaint (Sec. 200 CrPC/223 BNSS)", "Discharge Application", "Charge Sheet Reply"]
      },
      {
        "matter_name": "Money Recovery",
        "applicable_doc_types": ["Civil Suit (Money Recovery)", "Execution Petition"]
      },
      {
        "matter_name": "Other",
        "applicable_doc_types": ["Civil Suit (Money Recovery)"]
      }
    ]
  },

  "tribunal": {
    "subject_matters": [
      {
        "matter_name": "Company / Insolvency",
        "tribunal_name": "National Company Law Tribunal (NCLT)",
        "applicable_doc_types": ["Insolvency Application (Sec. 7/9/10 IBC)", "Company Petition", "Winding-up Petition"]
      },
      {
        "matter_name": "Environmental",
        "tribunal_name": "National Green Tribunal (NGT)",
        "applicable_doc_types": ["Environmental Compensation Application", "Appeal against Environmental Clearance"]
      },
      {
        "matter_name": "Income Tax / GST",
        "tribunal_name": "Income Tax Appellate Tribunal (ITAT)",
        "applicable_doc_types": ["Tax Appeal", "Rectification Application"]
      },
      {
        "matter_name": "Service (Central Govt)",
        "tribunal_name": "Central Administrative Tribunal (CAT)",
        "applicable_doc_types": ["Service Matter Original Application"]
      },
      {
        "matter_name": "Consumer Complaint",
        "tribunal_name": "National Consumer Disputes Redressal Commission (NCDRC)",
        "applicable_doc_types": ["Consumer Complaint (Consumer Protection Act)"]
      },
      {
        "matter_name": "Motor Accident",
        "tribunal_name": "Motor Accidents Claims Tribunal (MACT)",
        "applicable_doc_types": ["Motor Accident Claim Petition"]
      },
      {
        "matter_name": "Real Estate / Builder Dispute",
        "tribunal_name": "Real Estate Regulatory Authority (RERA) / Appellate Tribunal",
        "applicable_doc_types": ["Complaint against Builder/Developer"]
      },
      {
        "matter_name": "Debt Recovery / SARFAESI",
        "tribunal_name": "Debts Recovery Tribunal (DRT) / DRAT",
        "applicable_doc_types": ["Recovery Application under SARFAESI/RDBA"]
      },
      {
        "matter_name": "Matrimonial / Family",
        "tribunal_name": "Family Courts",
        "applicable_doc_types": ["Divorce Petition", "Custody Petition", "Maintenance Petition"]
      },
      {
        "matter_name": "Industrial Dispute",
        "tribunal_name": "Labour Courts / Industrial Tribunals (State)",
        "applicable_doc_types": ["Industrial Dispute Reference", "Reinstatement Application"]
      },
      {
        "matter_name": "Other",
        "tribunal_name": None,
        "applicable_doc_types": []
      }
    ]
  },

  "special_court": {
    "subject_matters": [
      {
        "matter_name": "POCSO / Child Protection",
        "special_court_name": "POCSO Courts",
        "applicable_doc_types": ["Charge framing application", "Bail Application (POCSO-specific)"]
      },
      {
        "matter_name": "Narcotics (NDPS)",
        "special_court_name": "NDPS Special Courts",
        "applicable_doc_types": ["Bail Application (Sec. 37 NDPS)"]
      },
      {
        "matter_name": "Money Laundering (PMLA)",
        "special_court_name": "Prevention of Money Laundering Act (PMLA) Special Courts",
        "applicable_doc_types": ["Bail Application (Sec. 45 PMLA)", "ECIR Quashing"]
      },
      {
        "matter_name": "CBI Case",
        "special_court_name": "CBI Courts (Special Courts)",
        "applicable_doc_types": ["Discharge Application", "Bail Application"]
      },
      {
        "matter_name": "Commercial Dispute",
        "special_court_name": "Commercial Courts",
        "applicable_doc_types": ["Commercial Suit (Commercial Courts Act)"]
      },
      {
        "matter_name": "Fast Track (Rape/Sensitive)",
        "special_court_name": "Fast Track Courts / Fast Track Special Courts (FTSC)",
        "applicable_doc_types": []
      },
      {
        "matter_name": "Other",
        "special_court_name": None,
        "applicable_doc_types": []
      }
    ]
  }
}

async def seed():
    async with engine.begin() as conn:
        print("Clearing old subject matters...")
        await conn.execute(text("DELETE FROM subject_matters;"))
        
        sort_order = 1
        count = 0
        for court_level, court_data in data.items():
            for matter in court_data["subject_matters"]:
                await conn.execute(
                    text("""
                        INSERT INTO subject_matters 
                            (court_level, matter_name, applicable_doc_types, tribunal_name, sort_order)
                        VALUES (:court_level, :matter_name, :applicable_doc_types, :tribunal_name, :sort_order)
                    """),
                    {
                        "court_level": court_level,
                        "matter_name": matter["matter_name"],
                        "applicable_doc_types": matter.get("applicable_doc_types", []),
                        "tribunal_name": matter.get("tribunal_name") or matter.get("special_court_name"),
                        "sort_order": sort_order
                    }
                )
                sort_order += 1
                count += 1
                
        print(f"Seeding completed successfully! Inserted {count} records.")

if __name__ == "__main__":
    asyncio.run(seed())
