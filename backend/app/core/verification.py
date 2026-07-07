import os
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Try to load .env from root if backend doesn't have it
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env"))

openrouter_key = os.getenv("OPENROUTER_API_KEY")

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=openrouter_key or "DUMMY",
)

async def verify_document(doc_type: str, ocr_text: str) -> dict:
    """
    Sends the OCR text and expected document type to OpenRouter.
    Returns a dict with 'status' (verified/rejected) and 'reason'.
    """
    if not openrouter_key:
        return {
            "status": "pending",
            "reason": "OpenRouter API Key not configured. Skipping verification."
        }
        
    if len(ocr_text) < 10 or "OCR Failed" in ocr_text:
        return {
            "status": "pending",
            "reason": "OCR failed or document was empty. Could not verify."
        }

    # Truncate OCR text roughly to save tokens (~3000 chars is plenty for classification)
    truncated_text = ocr_text[:3000]

    system_prompt = """
    You are a strict Indian Legal Document Classifier.
    Your job is to read the OCR text extracted from an uploaded document, and verify if it matches the EXPECTED DOCUMENT TYPE.
    
    Output strictly in JSON format with exactly these two keys:
    {
      "status": "verified" or "rejected",
      "reason": "1-2 short sentences explaining why you verified or rejected it"
    }
    
    If it is clearly a completely unrelated document (e.g., a restaurant menu, a photo of a dog, a completely different legal form), reject it.
    If it plausibly looks like the expected document type (or a related annexure/supporting document), verify it.
    """

    user_prompt = f"""
    EXPECTED DOCUMENT TYPE: {doc_type}
    
    OCR TEXT (first few pages):
    {truncated_text}
    """

    try:
        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
        result_json = response.choices[0].message.content
        result = json.loads(result_json)
        
        # Ensure fallback
        status = result.get("status", "pending").lower()
        if status not in ["verified", "rejected"]:
            status = "pending"
            
        return {
            "status": status,
            "reason": result.get("reason", "Verification complete.")
        }
    except Exception as e:
        print(f"LLM Verification Failed: {str(e)}")
        return {
            "status": "pending",
            "reason": f"LLM Verification failed: {str(e)}"
        }
