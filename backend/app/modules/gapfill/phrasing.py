import json
from app.core.rag import get_openrouter_client
from app.modules.gapfill.schema_gaps import SchemaGap

SCHEMA_GAP_PHRASING_PROMPT = """You are a helpful legal drafting assistant asking 
the user ONE brief, friendly question to collect a missing detail.

Field needed: {field_label}
Why it's needed: {reason}
Document type: {document_type}

Rules:
- Ask about ONLY this field, nothing else.
- Keep it to one sentence, conversational tone.
- If this is a "high_value" (optional but recommended) field, make clear the 
  user CAN skip it, e.g. "...or let AI draft it if you'd prefer."
- Do not explain legal concepts at length — just ask.

Respond with ONLY the question text, nothing else."""


async def phrase_schema_gap_question(gap: SchemaGap, document_type: str) -> str:
    prompt = SCHEMA_GAP_PHRASING_PROMPT.format(
        field_label=gap["field_label"],
        reason=gap["reason"],
        document_type=document_type,
    )
    client = get_openrouter_client()
    response = await client.chat.completions.create(
        model="openai/gpt-4o",
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=60,
        temperature=0.3
    )
    return response.choices[0].message.content.strip()
