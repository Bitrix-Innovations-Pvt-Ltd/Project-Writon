import sys
import os
import json
import asyncio
from dotenv import load_dotenv

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from app.core.database import AsyncSessionLocal
from app.models.document_type import DocumentType
from app.models.subject_matter import SubjectMatter
from app.models.document_requirement import DocumentRequirement
from sqlalchemy import text

async def populate():
    json_path = r"c:\Users\Shivam\Downloads\case-type-mapping.json"
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    court_level = "high"
    tribunal_name = data.get("court", "High Court of Judicature at Allahabad")
    
    async with AsyncSessionLocal() as session:
        # Clear existing data for this tribunal to prevent duplicates
        await session.execute(text("DELETE FROM document_requirements WHERE court_level = 'high'"))
        await session.execute(text("DELETE FROM subject_matters WHERE court_level = 'high'"))
        await session.execute(text("DELETE FROM document_types WHERE court_level = 'high'"))
        
        common_docs = data.get("documentsCommonToEveryFiling", [])
        
        doc_type_order = 1
        matter_order = 1
        req_order = 1
        
        for category in data.get("categories", []):
            cat_name = category.get("name") # e.g. "PETITION"
            cat_summary = category.get("summary") # e.g. "Writ & original"
            
            # 1. Insert DocumentType (The 5 categories)
            dt = DocumentType(
                court_level=court_level,
                tribunal_name=tribunal_name,
                doc_type_name=cat_name, 
                category=cat_summary,
                sort_order=doc_type_order
            )
            session.add(dt)
            doc_type_order += 1
            
            for case_type in category.get("caseTypes", []):
                case_type_name = case_type.get("name")
                sub_categories = case_type.get("subCategories", [])
                file_with = case_type.get("fileWith", [])
                all_docs = common_docs + file_with
                
                # If there are subcategories, we map each one as a distinct SubjectMatter 
                # (e.g. "Criminal Misc. Writ Petition - Stay of arrest")
                # If there are none, we just use the case_type_name (e.g. "Company Petition")
                matters_to_create = []
                if sub_categories:
                    for sub in sub_categories:
                        matters_to_create.append(f"{case_type_name} — {sub}")
                else:
                    matters_to_create.append(case_type_name)
                    
                for matter_name in matters_to_create:
                    # 2. Insert SubjectMatter
                    sm = SubjectMatter(
                        court_level=court_level,
                        tribunal_name=tribunal_name,
                        matter_name=matter_name,
                        applicable_doc_types=[cat_name],
                        sort_order=matter_order
                    )
                    session.add(sm)
                    matter_order += 1
                    
                    # 3. Insert DocumentRequirements for this Subject Matter
                    for doc in all_docs:
                        req = DocumentRequirement(
                            court_level=court_level,
                            subject_matter=matter_name,
                            document_name=doc,
                            requirement_type="required",
                            sort_order=req_order
                        )
                        session.add(req)
                        req_order += 1
                            
        await session.commit()
        print("Data successfully repopulated with sub-categories!")

if __name__ == "__main__":
    asyncio.run(populate())
