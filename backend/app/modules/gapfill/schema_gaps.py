from typing import TypedDict

class SchemaGap(TypedDict):
    field: str
    field_label: str
    priority: str  # 'required' | 'high_value'
    reason: str


def _value_is_filled(value, min_length: int) -> bool:
    """
    Returns True if value is considered 'filled' with at least min_length characters.
    Handles strings, lists of strings, and lists of dicts (dates_and_events).
    """
    if value is None:
        return False
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and len(item.strip()) >= min_length:
                return True
            if isinstance(item, dict):
                combined = " ".join(str(v).strip() for v in item.values() if v)
                if len(combined) >= min_length:
                    return True
        return False
    if isinstance(value, str):
        return len(value.strip()) >= min_length
    # Fallback for other types (int, bool, etc.)
    return len(str(value).strip()) >= min_length


async def detect_schema_gaps(db_conn, form_data: dict, document_type_key: str) -> list[SchemaGap]:
    """
    Deterministic -- same input always produces the same gap list.
    Reads from document_field_requirements, NOT hardcoded per document type.
    """
    from app.models.gapfill import DocumentFieldRequirements
    from sqlalchemy.future import select

    result = await db_conn.execute(
        select(DocumentFieldRequirements).filter(
            DocumentFieldRequirements.document_type_key == document_type_key
        ).order_by(
            DocumentFieldRequirements.priority.desc(),  # 'required' > 'high_value'
            DocumentFieldRequirements.sort_order
        )
    )
    requirements = result.scalars().all()

    gaps = []
    for req in requirements:
        value = form_data.get(req.field_key, "")
        if not _value_is_filled(value, req.min_length):
            gaps.append({
                "field": req.field_key,
                "field_label": req.field_label,
                "priority": req.priority,
                "reason": req.reason,
            })
    return gaps
