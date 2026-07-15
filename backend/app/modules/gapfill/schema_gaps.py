from typing import TypedDict

class SchemaGap(TypedDict):
    field: str
    field_label: str
    priority: str  # 'required' | 'high_value'
    reason: str


async def detect_schema_gaps(db_conn, form_data: dict, document_type_key: str) -> list[SchemaGap]:
    """
    Deterministic — same input always produces the same gap list.
    Reads from document_field_requirements, NOT hardcoded per document type.
    """
    from app.models.gapfill import DocumentFieldRequirements
    from sqlalchemy.future import select
    
    result = await db_conn.execute(
        select(DocumentFieldRequirements).filter(
            DocumentFieldRequirements.document_type_key == document_type_key
        ).order_by(
            DocumentFieldRequirements.priority.desc(), # 'required' > 'high_value'
            DocumentFieldRequirements.sort_order
        )
    )
    requirements = result.scalars().all()

    gaps = []
    for req in requirements:
        value = form_data.get(req.field_key, "")
        is_filled = value and len(str(value).strip()) >= req.min_length
        if not is_filled:
            gaps.append({
                "field": req.field_key,
                "field_label": req.field_label,
                "priority": req.priority,
                "reason": req.reason,
            })
    return gaps
