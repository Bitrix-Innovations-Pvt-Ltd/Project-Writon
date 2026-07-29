import sys
import os
import json
import asyncio
from dotenv import load_dotenv

# Setup path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from app.core.database import AsyncSessionLocal
from app.models.hierarchy import HierarchyCategory, HierarchyCaseType, HierarchySubCategory, HierarchyDocumentRequirement
from sqlalchemy import text

async def populate():
    json_path = r"c:\Users\Shivam\Downloads\case-type-mapping.json"
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    court_level = "high"
    
    async with AsyncSessionLocal() as session:
        # Clear existing data
        await session.execute(text("DELETE FROM hierarchy_document_requirements"))
        await session.execute(text("DELETE FROM hierarchy_sub_categories"))
        await session.execute(text("DELETE FROM hierarchy_case_types"))
        await session.execute(text("DELETE FROM hierarchy_categories"))
        
        cat_order = 1
        case_type_order = 1
        sub_cat_order = 1
        req_order = 1
        
        for category in data.get("categories", []):
            cat_name = category.get("name") # e.g. "PETITION"
            cat_summary = category.get("summary") # e.g. "Writ & original"
            cat_desc = category.get("description")
            cat_code = category.get("code")
            
            # 1. Insert HierarchyCategory
            hc = HierarchyCategory(
                court_level=court_level,
                name=cat_name, 
                summary=cat_summary,
                description=cat_desc,
                code=cat_code,
                sort_order=cat_order
            )
            session.add(hc)
            await session.flush() # flush to get id
            cat_order += 1
            
            for case_type in category.get("caseTypes", []):
                case_type_name = case_type.get("name")
                case_type_code = case_type.get("code")
                is_defective = case_type.get("defective", False)
                
                # 2. Insert HierarchyCaseType
                hct = HierarchyCaseType(
                    category_id=hc.id,
                    name=case_type_name,
                    code=case_type_code,
                    defective=is_defective,
                    sort_order=case_type_order
                )
                session.add(hct)
                await session.flush() # flush to get id
                case_type_order += 1
                
                # 3. Insert SubCategories
                for sub in case_type.get("subCategories", []):
                    hsc = HierarchySubCategory(
                        case_type_id=hct.id,
                        name=sub,
                        sort_order=sub_cat_order
                    )
                    session.add(hsc)
                    sub_cat_order += 1
                    
                # 4. Insert Document Requirements
                for doc in case_type.get("fileWith", []):
                    req_type = "optional" if any(keyword in doc.lower() for keyword in ["if any", "if relevant", "if applicable", "if available"]) else "required"
                    req = HierarchyDocumentRequirement(
                        case_type_id=hct.id,
                        document_name=doc,
                        requirement_type=req_type,
                        sort_order=req_order
                    )
                    session.add(req)
                    req_order += 1
                            
        await session.commit()
        print("Data successfully populated into normalized hierarchy tables!")

if __name__ == "__main__":
    asyncio.run(populate())
