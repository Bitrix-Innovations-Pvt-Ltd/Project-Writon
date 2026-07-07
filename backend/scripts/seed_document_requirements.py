import asyncio
import os
import sys
from sqlalchemy import text

# Add backend directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import engine

data = [
    # Supreme Court
    ("supreme", "Constitutional / Fundamental Rights", [
        ("Impugned order (if any)", "", "required"),
        ("Copy of relevant statute/rule", "", "required"),
        ("Proof of standing/locus", "", "required"),
        ("Prior representations made", "", "optional"),
        ("Media reports (if public interest)", "", "optional"),
    ]),
    ("supreme", "Special Leave (Criminal)", [
        ("Certified copy of HC judgment", "", "required"),
        ("Trial court judgment", "", "required"),
        ("Bail order (if any)", "", "required"),
        ("Charge sheet", "", "optional"),
        ("Witness statements", "", "optional"),
    ]),
    ("supreme", "Special Leave (Civil)", [
        ("Certified copy of HC judgment", "", "required"),
        ("Lower court judgments", "", "required"),
        ("Limitation calculation", "", "required"),
        ("Settlement correspondence", "", "optional"),
    ]),
    ("supreme", "Tax (Direct/Indirect)", [
        ("ITAT/HC order", "", "required"),
        ("Assessment order", "", "required"),
        ("Show cause notice", "", "required"),
        ("Returns filed", "", "optional"),
        ("Audit report", "", "optional"),
    ]),
    ("supreme", "Service Law", [
        ("Impugned order", "", "required"),
        ("Service record", "", "required"),
        ("Rules under which action taken", "", "required"),
        ("Previous representations", "", "optional"),
    ]),
    ("supreme", "Contempt of Court", [
        ("Original order allegedly violated", "", "required"),
        ("Proof of non-compliance", "", "required"),
        ("Correspondence with contemnor", "", "optional"),
    ]),
    # High Court
    ("high", "Writ / Fundamental Rights", [
        ("Impugned order/action", "", "required"),
        ("Relevant statute", "", "required"),
        ("Representation made to authority", "", "required"),
        ("RTI response (if applicable)", "", "optional"),
    ]),
    ("high", "Property / Land Dispute", [
        ("Sale deed/title document", "", "required"),
        ("Revenue records", "", "required"),
        ("Site plan", "", "required"),
        ("Photographs", "", "optional"),
        ("Prior litigation history", "", "optional"),
    ]),
    ("high", "Criminal Matter", [
        ("Trial court judgment", "", "required"),
        ("FIR copy", "", "required"),
        ("Charge sheet", "", "required"),
        ("Bail orders", "", "optional"),
        ("Medical reports", "", "optional"),
    ]),
    ("high", "Bail / Anticipatory Bail", [
        ("FIR copy", "", "required"),
        ("Remand order", "", "required"),
        ("Lower court bail rejection order", "", "required"),
        ("Medical certificates", "", "optional"),
        ("Surety documents", "", "optional"),
    ]),
    ("high", "Income Tax / GST", [
        ("Assessment Order", "", "required"),
        ("Show Cause Notice", "", "required"),
        ("First Appeal Order (CIT-A/GST Appellate)", "", "required"),
        ("IT/GST Returns", "", "required"),
        ("Reply to SCN", "", "optional"),
        ("Books of Accounts", "", "optional"),
        ("Challan of tax deposited", "", "optional"),
    ]),
    ("high", "Matrimonial / Family", [
        ("Marriage certificate", "", "required"),
        ("Lower court order", "", "required"),
        ("Children's documents (if custody)", "", "required"),
        ("Financial affidavits", "", "optional"),
    ]),
    # District / Sessions Court
    ("district", "Property / Land Dispute", [
        ("Sale deed/title", "", "required"),
        ("Mutation records", "", "required"),
        ("Encumbrance certificate", "", "required"),
        ("Survey/site plan", "", "optional"),
        ("Photographs", "", "optional"),
    ]),
    ("district", "Cheque Dishonour (NI Act)", [
        ("Original cheque", "", "required"),
        ("Bank return memo", "", "required"),
        ("Statutory notice + proof of service", "", "required"),
        ("Loan agreement (if any)", "", "optional"),
    ]),
    ("district", "Matrimonial / Family", [
        ("Marriage certificate", "", "required"),
        ("Income proof", "", "required"),
        ("Address proof", "", "required"),
        ("Domestic violence complaint (if any)", "", "optional"),
    ]),
    ("district", "Bail / Anticipatory Bail", [
        ("FIR copy", "", "required"),
        ("Remand order", "", "required"),
        ("Medical certificate", "", "optional"),
        ("Character certificate", "", "optional"),
    ]),
    ("district", "Money Recovery", [
        ("Loan agreement/invoice", "", "required"),
        ("Demand notice", "", "required"),
        ("Payment records", "", "required"),
        ("Bank statements", "", "optional"),
    ]),
    ("district", "Criminal Matter", [
        ("FIR copy", "", "required"),
        ("Charge sheet", "", "required"),
        ("Witness list", "", "optional"),
        ("Bail order", "", "optional"),
    ]),
    # Tribunal
    ("tribunal", "Company / Insolvency", [
        ("Loan/financial agreement", "", "required"),
        ("Default proof", "", "required"),
        ("Board resolution", "", "required"),
        ("Statement of accounts", "", "optional"),
        ("Demand notice", "", "optional"),
    ]),
    ("tribunal", "Environmental", [
        ("Environmental clearance copy", "", "required"),
        ("Pollution report/data", "", "required"),
        ("Photographs", "", "optional"),
        ("Expert reports", "", "optional"),
    ]),
    ("tribunal", "Income Tax / GST", [
        ("Assessment order", "", "required"),
        ("First appeal order (CIT-A)", "", "required"),
        ("Returns", "", "optional"),
        ("Audit report", "", "optional"),
    ]),
    ("tribunal", "Motor Accident", [
        ("FIR copy", "", "required"),
        ("Medical records", "", "required"),
        ("Income proof of victim", "", "required"),
        ("Post-mortem report", "", "optional"),
        ("Disability certificate", "", "optional"),
    ]),
    ("tribunal", "Real Estate / Builder Dispute", [
        ("Builder-buyer agreement", "", "required"),
        ("Payment receipts", "", "required"),
        ("Possession letter (if any)", "", "required"),
        ("Project registration details", "", "optional"),
    ]),
    ("tribunal", "Matrimonial / Family", [
        ("Marriage certificate", "", "required"),
        ("Income proof", "", "required"),
        ("Custody-related school/medical records", "", "optional"),
    ]),
    # Special Court
    ("special_court", "POCSO / Child Protection", [
        ("FIR copy", "", "required"),
        ("Medical examination report", "", "required"),
        ("Age proof of victim", "", "required"),
        ("Counselling reports", "", "optional"),
    ]),
    ("special_court", "Narcotics (NDPS)", [
        ("FIR copy", "", "required"),
        ("Seizure memo", "", "required"),
        ("Chemical analysis report", "", "required"),
        ("Prior conviction record", "", "optional"),
    ]),
    ("special_court", "Money Laundering (PMLA)", [
        ("ECIR copy", "", "required"),
        ("Provisional attachment order (if any)", "", "required"),
        ("Bank statements", "", "optional"),
    ]),
    ("special_court", "CBI Case", [
        ("FIR/RC copy", "", "required"),
        ("Charge sheet", "", "required"),
        ("Sanction for prosecution", "", "optional"),
    ]),
    # The Generic Fallback for ANY "Other"
    ("supreme", "Other", [
        ("Relevant Case Documents", "Any order, notice, or agreement central to your case", "required"),
        ("Identity/Address Proof of Petitioner", "Aadhaar, PAN, or other valid ID proof", "required"),
        ("Prior Correspondence", "Any legal notice, representation, or communication sent/received", "optional"),
        ("Any Other Supporting Records", "Photographs, statements, or additional evidence", "optional"),
    ]),
    ("high", "Other", [
        ("Relevant Case Documents", "Any order, notice, or agreement central to your case", "required"),
        ("Identity/Address Proof of Petitioner", "Aadhaar, PAN, or other valid ID proof", "required"),
        ("Prior Correspondence", "Any legal notice, representation, or communication sent/received", "optional"),
        ("Any Other Supporting Records", "Photographs, statements, or additional evidence", "optional"),
    ]),
    ("district", "Other", [
        ("Relevant Case Documents", "Any order, notice, or agreement central to your case", "required"),
        ("Identity/Address Proof of Petitioner", "Aadhaar, PAN, or other valid ID proof", "required"),
        ("Prior Correspondence", "Any legal notice, representation, or communication sent/received", "optional"),
        ("Any Other Supporting Records", "Photographs, statements, or additional evidence", "optional"),
    ]),
    ("tribunal", "Other", [
        ("Relevant Case Documents", "Any order, notice, or agreement central to your case", "required"),
        ("Identity/Address Proof of Petitioner", "Aadhaar, PAN, or other valid ID proof", "required"),
        ("Prior Correspondence", "Any legal notice, representation, or communication sent/received", "optional"),
        ("Any Other Supporting Records", "Photographs, statements, or additional evidence", "optional"),
    ]),
    ("special_court", "Other", [
        ("Relevant Case Documents", "Any order, notice, or agreement central to your case", "required"),
        ("Identity/Address Proof of Petitioner", "Aadhaar, PAN, or other valid ID proof", "required"),
        ("Prior Correspondence", "Any legal notice, representation, or communication sent/received", "optional"),
        ("Any Other Supporting Records", "Photographs, statements, or additional evidence", "optional"),
    ]),
]

async def seed():
    async with engine.begin() as conn:
        print("Clearing old document requirements...")
        await conn.execute(text("DELETE FROM document_requirements;"))
        
        count = 0
        for court_level, subject_matter, docs in data:
            sort_order = 1
            for doc_name, desc, req_type in docs:
                await conn.execute(
                    text("""
                        INSERT INTO document_requirements 
                            (court_level, subject_matter, document_name, description, requirement_type, sort_order)
                        VALUES (:court_level, :subject_matter, :document_name, :description, :requirement_type, :sort_order)
                    """),
                    {
                        "court_level": court_level,
                        "subject_matter": subject_matter,
                        "document_name": doc_name,
                        "description": desc if desc else None,
                        "requirement_type": req_type,
                        "sort_order": sort_order
                    }
                )
                sort_order += 1
                count += 1
                
        print(f"Seeding completed successfully! Inserted {count} records.")

if __name__ == "__main__":
    asyncio.run(seed())
