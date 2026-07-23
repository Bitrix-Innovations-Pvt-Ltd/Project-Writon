"""
Seed script for document_field_requirements table.
This drives the schema gap detection: if a required field is empty,
the Legal Assistant bot will ask the user to fill it.

Run from backend/ directory:
  python -m scripts.seed_field_requirements
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine

# Format: (document_type_key, field_key, field_label, priority, min_length, reason, sort_order)
# priority: 'required' | 'high_value'
FIELD_REQUIREMENTS = [
    # ── Writ Petition (Civil) ─────────────────────────────────────────────
    ("writ_petition_civil", "petitioners",        "Petitioner Name(s)",           "required", 3,  "Identifies who is filing the petition.",                              1),
    ("writ_petition_civil", "respondents",        "Respondent Name(s)",           "required", 3,  "Identifies the opposite party.",                                      2),
    ("writ_petition_civil", "facts_of_case",      "Facts of the Case",            "required", 50, "The factual narrative is the foundation of any legal pleading.",       3),
    ("writ_petition_civil", "grounds",            "Grounds for the Petition",     "required", 30, "Legal grounds justify the court's jurisdiction and the relief.",       4),
    ("writ_petition_civil", "relief_sought",      "Relief Sought",                "required", 10, "Specifies what the court is being asked to do.",                       5),
    ("writ_petition_civil", "advocate_name",      "Advocate Name",                "required", 3,  "Required for the counsel block in the petition.",                      6),
    ("writ_petition_civil", "jurisdiction_basis", "Jurisdiction Basis",           "high_value", 10, "Explains why this court has authority to hear the matter.",          7),
    ("writ_petition_civil", "impugned_order_date","Date of Impugned Order",       "high_value", 5,  "Critical for calculating limitation period.",                        8),
    ("writ_petition_civil", "interim_relief_sought", "Interim Relief Sought",     "high_value", 10, "Required if urgent relief like stay is needed.",                    9),

    # ── Writ Petition (Criminal) ──────────────────────────────────────────
    ("writ_petition_criminal", "petitioners",     "Petitioner Name(s)",           "required", 3,  "Identifies who is filing the petition.",                              1),
    ("writ_petition_criminal", "respondents",     "Respondent Name(s)",           "required", 3,  "Identifies the opposite party.",                                      2),
    ("writ_petition_criminal", "facts_of_case",   "Facts of the Case",            "required", 50, "The factual narrative is the foundation of any legal pleading.",       3),
    ("writ_petition_criminal", "grounds",         "Grounds for the Petition",     "required", 30, "Legal grounds justify the court's jurisdiction and the relief.",       4),
    ("writ_petition_criminal", "relief_sought",   "Relief Sought",                "required", 10, "Specifies what the court is being asked to do.",                       5),
    ("writ_petition_criminal", "advocate_name",   "Advocate Name",                "required", 3,  "Required for the counsel block in the petition.",                      6),
    ("writ_petition_criminal", "impugned_order_date", "Date of Impugned Order",   "high_value", 5,  "Critical for calculating limitation period.",                       7),

    # ── Bail Application ──────────────────────────────────────────────────
    ("bail_application", "petitioners",           "Accused / Applicant Name",     "required", 3,  "Name of the person seeking bail.",                                    1),
    ("bail_application", "respondents",           "State / Complainant",          "required", 3,  "Identifies the opposing party.",                                      2),
    ("bail_application", "facts_of_case",         "Facts of the Case / Arrest",   "required", 50, "Describes the circumstances of arrest and the alleged offence.",       3),
    ("bail_application", "grounds",               "Grounds for Bail",             "required", 30, "Legal arguments why bail should be granted.",                          4),
    ("bail_application", "relief_sought",         "Relief Sought",                "required", 10, "Specifies the exact bail relief requested.",                           5),
    ("bail_application", "advocate_name",         "Advocate Name",                "required", 3,  "Required for the counsel block.",                                      6),

    # ── Anticipatory Bail ─────────────────────────────────────────────────
    ("anticipatory_bail", "petitioners",          "Applicant Name",               "required", 3,  "Name of the person apprehending arrest.",                             1),
    ("anticipatory_bail", "respondents",          "State / Complainant",          "required", 3,  "Identifies the opposing party.",                                      2),
    ("anticipatory_bail", "facts_of_case",        "Facts / Apprehension of Arrest","required", 50, "Describes why arrest is apprehended.",                              3),
    ("anticipatory_bail", "grounds",              "Grounds for Anticipatory Bail","required", 30, "Legal arguments for pre-arrest bail.",                                4),
    ("anticipatory_bail", "relief_sought",        "Relief Sought",                "required", 10, "Specifies the anticipatory bail relief.",                              5),
    ("anticipatory_bail", "advocate_name",        "Advocate Name",                "required", 3,  "Required for the counsel block.",                                      6),

    # ── Civil Appeal ──────────────────────────────────────────────────────
    ("civil_appeal", "petitioners",               "Appellant Name(s)",            "required", 3,  "Name of the party filing the appeal.",                                1),
    ("civil_appeal", "respondents",               "Respondent Name(s)",           "required", 3,  "Name of the opposite party.",                                         2),
    ("civil_appeal", "facts_of_case",             "Facts of the Case",            "required", 50, "The factual background including lower court proceedings.",             3),
    ("civil_appeal", "grounds",                   "Grounds of Appeal",            "required", 30, "Legal errors in the lower court's decision.",                          4),
    ("civil_appeal", "relief_sought",             "Relief Sought",                "required", 10, "What the appellant wants the appellate court to do.",                  5),
    ("civil_appeal", "advocate_name",             "Advocate Name",                "required", 3,  "Required for the counsel block.",                                      6),
    ("civil_appeal", "impugned_order_date",       "Date of Impugned Order",       "high_value", 5,  "Required to check limitation for filing appeal.",                  7),

    # ── Criminal Appeal ───────────────────────────────────────────────────
    ("criminal_appeal", "petitioners",            "Appellant Name(s)",            "required", 3,  "Name of the party filing the appeal.",                                1),
    ("criminal_appeal", "respondents",            "Respondent / State",           "required", 3,  "Name of the opposite party.",                                         2),
    ("criminal_appeal", "facts_of_case",          "Facts of the Case",            "required", 50, "The factual background including trial court proceedings.",             3),
    ("criminal_appeal", "grounds",                "Grounds of Appeal",            "required", 30, "Legal errors in the trial/lower court's judgment.",                    4),
    ("criminal_appeal", "relief_sought",          "Relief Sought",                "required", 10, "What the appellant wants the appellate court to order.",               5),
    ("criminal_appeal", "advocate_name",          "Advocate Name",                "required", 3,  "Required for the counsel block.",                                      6),
]


async def seed():
    async with engine.begin() as conn:
        print("Clearing existing document_field_requirements...")
        await conn.execute(text("DELETE FROM document_field_requirements;"))
        print("Cleared.")

        count = 0
        for (doc_type_key, field_key, field_label, priority, min_length, reason, sort_order) in FIELD_REQUIREMENTS:
            await conn.execute(
                text("""
                    INSERT INTO document_field_requirements
                        (document_type_key, field_key, field_label, priority, min_length, reason, sort_order)
                    VALUES
                        (:doc_type_key, :field_key, :field_label, :priority, :min_length, :reason, :sort_order)
                    ON CONFLICT (document_type_key, field_key) DO UPDATE SET
                        field_label = EXCLUDED.field_label,
                        priority    = EXCLUDED.priority,
                        min_length  = EXCLUDED.min_length,
                        reason      = EXCLUDED.reason,
                        sort_order  = EXCLUDED.sort_order;
                """),
                {
                    "doc_type_key": doc_type_key,
                    "field_key":    field_key,
                    "field_label":  field_label,
                    "priority":     priority,
                    "min_length":   min_length,
                    "reason":       reason,
                    "sort_order":   sort_order,
                }
            )
            count += 1

        print(f"Seeded {count} field requirements successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
