import json
from app.core.rag import get_openrouter_client

CONTEXT_GAP_DETECTION_PROMPT = """You are an expert Indian appellate lawyer reviewing a partially completed case file for a {document_type}.
Your goal is to identify AT MOST 3 genuinely relevant additional facts or context pieces that are missing but necessary to draft a compelling document.

If the provided facts are extremely sparse or empty, DO NOT output an error. Instead, ask foundational questions (e.g., "What are the core events of the dispute?").

Respond ONLY with a JSON object containing a single key "gaps", which holds an array of objects.
Each object must have:
1. "question": The exact question to ask the user.
2. "why_relevant": A brief 1-sentence explanation of why this helps the legal draft.

Example format:
{{
  "gaps": [
    {{
      "question": "What was the date of the impugned order?",
      "why_relevant": "Needed to calculate limitation."
    }}
  ]
}}

Current Draft Information:
Facts: {facts_of_case}
Grounds: {grounds}
Relief: {relief_sought}
"""


async def detect_context_gaps(form_data: dict, document_type_key: str) -> list[dict]:
    prompt = CONTEXT_GAP_DETECTION_PROMPT.format(
        document_type=document_type_key,
        facts_of_case=form_data.get("facts_of_case", "Not provided"),
        grounds=form_data.get("grounds", "Not provided — AI will draft"),
        relief_sought=form_data.get("relief_sought", "Not provided"),
    )
    
    # Use better model as requested
    client = get_openrouter_client()
    response = await client.chat.completions.create(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.2,
        response_format={"type": "json_object"}
    )
    
    try:
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
            
        parsed = json.loads(content)
        
        # We asked for {"gaps": [...]}
        suggestions = parsed.get("gaps", [])
        
        if isinstance(suggestions, list):
            return suggestions[:3]  # hard cap enforced in code
        return []
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        print(f"Error parsing context gaps: {e}, Content: {response.choices[0].message.content}")
        return []  # fail safe
