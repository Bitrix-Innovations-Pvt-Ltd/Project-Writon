"""
core/uploaded_docs.py — assembles the UPLOADED DOCUMENTS block of the drafting
prompt.

Used by both POST /drafts/generate and POST /drafts/suggest-citations so the two
see an identical view of the advocate's documents.

Why this exists rather than a bare string join:

  * LABELS. base_rules.txt instructs the model to build the ANNEXURES section
    from "documents that are explicitly provided in the UPLOADED DOCUMENTS
    block". Concatenated OCR text carries no document names, so the model could
    not comply — it had to infer annexure names from prose. Each document is now
    delimited and labelled with its checklist type and filename.

  * BUDGET. The block is interpolated ahead of RELEVANT STATUTES and RELEVANT
    PRECEDENTS in every template. Uncapped, a multi-document upload pushes the
    retrieved authorities far down the prompt. Documents are ordered by
    relevance and clipped head+tail so the operative ones survive intact.

  * ROBUSTNESS. Documents are looked up by draft_id OR upload_session_id, so
    they are still found if the back-link in /gapfill/start did not run.
"""

from typing import Optional

from sqlalchemy import text as sql_text

from app.core.extraction import (
    clip_head_tail,
    dedupe_docs,
    doc_priority,
    is_usable_ocr,
    looks_like_template,
    unique_labels,
)

# Generous but bounded: ~48k chars is ~12k tokens, leaving the 200k-context
# generation model plenty of room for the statutes, precedents and court-rules
# blocks that follow this one.
TOTAL_CHARS = 48000
MAX_DOCS = 8
MIN_DOC_CHARS = 50          # matches the previous inline `len(text) > 50` filter

# The per-document allowance is derived from how many documents there are, so a
# lone 200-page judgment gets the whole budget instead of a fixed slice of it.
# Floored so that a full checklist of uploads still gives each document enough
# to be recognisable.
MIN_PER_DOC_CHARS = 4000
HEAD_RATIO = 0.75           # front-load: the cause title and facts lead the doc

_TRUNC_MARKER = "\n[... truncated ...]"

# clip_head_tail() splices its own "middle omitted" notice between head and
# tail. That has to come out of the allowance, otherwise a document clipped to
# exactly its share overshoots the total and hits the hard truncate below —
# which would cut off the tail, i.e. the operative date and signature block
# that head+tail clipping exists to preserve.
_OMISSION_OVERHEAD = 64

_HEADER = (
    "\n\n--- UPLOADED DOCUMENTS ---\n"
    "The advocate uploaded the documents below. They are the factual record for "
    "this matter: rely on them for names, dates, figures and events, and prefer "
    "them over inference. Each document is delimited and labelled. In the "
    "ANNEXURES section, list exactly these documents by their label — no others.\n"
    "A document marked [translated from ...] is a machine translation of a "
    "non-English original. Rely on it for the facts, but do NOT present any "
    "sentence from it as a verbatim quotation of the record — describe its "
    "contents instead.\n"
)

# Translation states worth telling the drafting model about. 'not_needed' and
# 'disabled' mean the text is the original, so they carry no annotation.
_TRANSLATED_STATES = {"translated", "partial"}

_LANG_NAMES = {"hi": "Hindi", "mixed": "Hindi"}


def _translation_note(doc: dict) -> str:
    """" [translated from Hindi]" for a document that went through translation."""
    if (doc.get("translation_status") or "") not in _TRANSLATED_STATES:
        return ""
    language = _LANG_NAMES.get(doc.get("ocr_lang") or "", "another language")
    partly = " in part" if doc.get("translation_status") == "partial" else ""
    return f" [translated from {language}{partly}]"


async def fetch_uploaded_docs(
    conn,
    draft_id: Optional[int] = None,
    upload_session_id: Optional[str] = None,
    include_doc_ids: Optional[list[int]] = None,
) -> list[dict]:
    """Return this draft's usable uploaded documents, oldest first.

    Matches on draft_id OR upload_session_id: uploads happen at Step 4, before
    the draft row exists, and are only back-linked when /gapfill/start runs.
    Rejected documents are excluded — uploads.py commits ocr_text before raising
    its 400, so rejected rows persist as an audit trail.

    `include_doc_ids` restricts the result to the matter the advocate is actually
    drafting. Auto-populate works out which documents belong to that matter; if a
    wrong file was uploaded to a slot, this keeps the unrelated case out of the
    generated narrative and the ANNEXURES list. Omit it to take everything.
    """
    if not draft_id and not upload_session_id:
        return []

    res = await conn.execute(
        sql_text("""
            SELECT id, doc_type, original_filename, ocr_text,
                   ocr_lang, translation_status
              FROM uploaded_docs
             -- Both sides are NULL-safe: `col = NULL` yields NULL, never true,
             -- so an absent parameter simply contributes no matches. The casts
             -- are required because asyncpg cannot infer a bare NULL's type.
             --
             -- The session branch requires draft_id IS NULL: an upload session
             -- is only a temporary holder for documents that have no draft yet.
             -- Once /gapfill/start back-links them to a draft they belong to
             -- THAT draft alone. Without this, a second draft started in the
             -- same browser tab inherited the first draft's documents, because
             -- the session id is stored under a key containing the literal
             -- "new" and is therefore shared by every new draft in that tab.
             WHERE (draft_id = CAST(:did AS BIGINT)
                    OR (upload_session_id = CAST(:sid AS TEXT)
                        AND draft_id IS NULL))
               AND ocr_text IS NOT NULL
               AND COALESCE(verify_status, '') <> 'rejected'
             ORDER BY uploaded_at ASC
        """),
        {"did": draft_id, "sid": upload_session_id},
    )
    docs = [dict(r) for r in res.mappings().all()]

    if include_doc_ids:
        wanted = set(include_doc_ids)
        filtered = [d for d in docs if d["id"] in wanted]
        # Ignore a stale filter rather than silently sending nothing — a draft
        # re-opened after new uploads would otherwise lose all its documents.
        if filtered:
            docs = filtered

    return docs


def build_uploaded_docs_context(docs: list[dict]) -> tuple[str, list[dict]]:
    """Render the labelled, budgeted UPLOADED DOCUMENTS block.

    Returns (block, docs_used). The block is "" when nothing is usable, which
    keeps the templates' existing `{{ uploaded_docs_context }}` behaviour and
    the ANNEXURES fallback in base_rules.txt intact.
    """
    # Re-uploads of the same content are collapsed first: they would otherwise
    # each consume a share of the budget and each appear as a separate entry in
    # the ANNEXURES list the model builds from this block.
    deduped = dedupe_docs(docs or [])

    # Filed vs narrated are different questions, and conflating them lost
    # documents. ANNEXURES is a record of what was FILED: a document belongs
    # there even if its text never reaches the model because the character budget
    # ran out, because it lost the MAX_DOCS cut, or because its OCR came back too
    # thin to narrate from. Only a blank template is genuinely not an annexure.
    annexable = [
        d for d in deduped
        # Blank pleading templates are excluded: they read as real documents but
        # their parties are placeholders, and the draft LLM would copy them.
        if not looks_like_template(d.get("ocr_text") or "")
    ]
    if not annexable:
        return "", []

    usable = [d for d in annexable if is_usable_ocr(d.get("ocr_text"), MIN_DOC_CHARS)]

    # Most probative documents first, so a total-cap overflow drops annexures
    # rather than the impugned order.
    annexable.sort(key=doc_priority)
    usable.sort(key=doc_priority)
    narrated = usable[:MAX_DOCS]

    dropped = [d for d in annexable if d not in narrated]
    if dropped:
        # Named, not silent: a document vanishing from the draft with no
        # explanation is exactly the bug this reporting exists to surface.
        print("[uploaded_docs] annexed but not narrated: " + "; ".join(
            f"{(d.get('original_filename') or 'unknown')} "
            f"({'thin OCR' if not is_usable_ocr(d.get('ocr_text'), MIN_DOC_CHARS) else 'over cap/budget'})"
            for d in dropped
        ))

    # Nothing narratable at all means there is nothing to tell the model about,
    # and the templates' ANNEXURES fallback covers the empty case.
    if not narrated:
        return "", []
    usable = narrated

    # Share the budget across however many documents there are: one long
    # judgment gets all 48k rather than a fixed slice, while a full checklist
    # still leaves each document a usable allowance.
    per_doc = max(MIN_PER_DOC_CHARS, TOTAL_CHARS // len(usable) - _OMISSION_OVERHEAD)
    head_chars = int(per_doc * HEAD_RATIO)
    tail_chars = per_doc - head_chars

    # Two files uploaded under one checklist type would otherwise carry the same
    # label, making the ANNEXURES list ambiguous about which file is which.
    labels = unique_labels(usable)

    blocks: list[str] = []
    used: list[dict] = []
    total = 0

    for i, doc in enumerate(usable, start=1):
        body = clip_head_tail(doc["ocr_text"], head_chars, tail_chars)
        if total + len(body) > TOTAL_CHARS:
            remaining = TOTAL_CHARS - total
            if remaining < MIN_DOC_CHARS:
                break
            # Reserve room for the marker, so the running total cannot exceed
            # TOTAL_CHARS once it is appended.
            body = body[:max(0, remaining - len(_TRUNC_MARKER))] + _TRUNC_MARKER
        total += len(body)

        label = labels[i - 1]
        filename = (doc.get("original_filename") or "unknown").strip()
        blocks.append(
            f'=== DOCUMENT {i}: "{label}" (file: {filename})'
            f"{_translation_note(doc)} ===\n"
            f"{body}\n"
            f"=== END DOCUMENT {i} ==="
        )
        used.append({
            "id": doc.get("id"),
            "label": label,
            "filename": filename,
            "chars_used": len(body),
        })

    # The exact annexure list, precomputed. We already know which documents were
    # filed and what each is called, so the model is asked to reproduce a list
    # rather than compose one — the same treatment DATES AND EVENTS already gets
    # in the templates. Instructing it to "list every uploaded document" left it
    # free to fall back on a generic "certified copy of the impugned order" line.
    #
    # The date is left as a blank for the advocate: a document's own date is not
    # reliably recoverable from OCR, and a wrong date on an annexure is worse
    # than a blank one.
    # Built from every filed document, not just the ones whose text fitted the
    # budget. An annexure list that omits a document the advocate actually filed
    # is wrong on the record, and the omission is invisible in the finished draft.
    chars_by_id = {u["id"]: u["chars_used"] for u in used}
    annexure_labels = unique_labels(annexable)
    annexure_entries = [
        {"id": d.get("id"),
         "label": annexure_labels[i],
         "filename": (d.get("original_filename") or "unknown").strip(),
         # 0 means the document is annexed but its text never reached the model
         # (thin OCR, or the character budget ran out before it).
         "chars_used": chars_by_id.get(d.get("id"), 0),
         "narrated": d.get("id") in chars_by_id}
        for i, d in enumerate(annexable)
    ]

    annexures = "\n".join(
        f"**Annexure No. {i}** — The photo/type copy of {a['label']} dated __/__/____"
        for i, a in enumerate(annexure_entries, start=1)
    )
    annexure_block = (
        "\n\n--- ANNEXURE LIST (reproduce EXACTLY as the ANNEXURES section, "
        "in this order, adding nothing) ---\n" + annexures
    )

    return _HEADER + "\n\n".join(blocks) + annexure_block, annexure_entries
