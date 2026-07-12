-- =====================================================================
-- Writon — Allahabad High Court Rule Book Integration
-- Source: hcrulespartIchItoVIII.pdf ("Rules of the Court, 1952",
--         Allahabad High Court — Chapters I to XLI, Parts I-VIII)
--
-- Run this file against the Neon DB AFTER running SQLAlchemy
-- model creation (alembic upgrade head or equivalent).
-- Tables created here must match the ORM models in court_rules.py.
-- =====================================================================


-- =====================================================================
-- SECTION 1: court_identities + court_benches
-- Specific court identity — separate from the generic court_level
-- =====================================================================
CREATE TABLE IF NOT EXISTS court_identities (
  id                   BIGSERIAL PRIMARY KEY,
  court_level          TEXT NOT NULL,
  court_name           TEXT NOT NULL UNIQUE,
  short_code           TEXT NOT NULL UNIQUE,
  state                TEXT,
  has_benches          BOOLEAN DEFAULT false,
  rule_book_title      TEXT,
  rule_book_source_url TEXT
);

CREATE TABLE IF NOT EXISTS court_benches (
  id                BIGSERIAL PRIMARY KEY,
  court_identity_id BIGINT NOT NULL REFERENCES court_identities(id) ON DELETE CASCADE,
  bench_name        TEXT NOT NULL,
  UNIQUE(court_identity_id, bench_name)
);

INSERT INTO court_identities (court_level, court_name, short_code, state, has_benches, rule_book_title)
VALUES ('high_court', 'Allahabad High Court', 'AHC', 'Uttar Pradesh', true, 'Rules of the Court, 1952')
ON CONFLICT (short_code) DO NOTHING;

INSERT INTO court_benches (court_identity_id, bench_name)
VALUES
  ((SELECT id FROM court_identities WHERE short_code = 'AHC'), 'Allahabad (Principal Seat)'),
  ((SELECT id FROM court_identities WHERE short_code = 'AHC'), 'Lucknow Bench')
ON CONFLICT (court_identity_id, bench_name) DO NOTHING;


-- =====================================================================
-- SECTION 2: court_rule_sections — vectorized rulebook corpus
-- Internal RAG only. Same pattern as legal_code_sections.
-- =====================================================================
CREATE TABLE IF NOT EXISTS court_rule_sections (
  id                 BIGSERIAL PRIMARY KEY,
  court_identity_id  BIGINT NOT NULL REFERENCES court_identities(id) ON DELETE CASCADE,
  part_name          TEXT,
  chapter_number     TEXT NOT NULL,
  chapter_title      TEXT,
  rule_number        TEXT,
  rule_subsection    TEXT,
  rule_text          TEXT NOT NULL,
  embedding          VECTOR(768),
  search_vector      TSVECTOR,
  source_page        INT,
  created_at         TIMESTAMPTZ DEFAULT now(),
  UNIQUE(court_identity_id, chapter_number, rule_number, rule_subsection)
);

CREATE INDEX IF NOT EXISTS idx_crs_hnsw ON court_rule_sections
  USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_crs_search ON court_rule_sections
  USING GIN(search_vector);

CREATE OR REPLACE FUNCTION court_rule_sections_search_trigger() RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.chapter_title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.rule_text, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS court_rule_sections_search_update ON court_rule_sections;
CREATE TRIGGER court_rule_sections_search_update
  BEFORE INSERT OR UPDATE ON court_rule_sections
  FOR EACH ROW EXECUTE FUNCTION court_rule_sections_search_trigger();

-- Seed rule sections
INSERT INTO court_rule_sections
  (court_identity_id, part_name, chapter_number, chapter_title, rule_number, rule_subsection, rule_text, source_page)
VALUES
-- Chapter I — Preliminary
((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART I-GENERAL', 'I', 'PRELIMINARY', '7', '(i)-(ii)',
 'Every application, petition, objection or memorandum of appeal, presented in Court, shall be signed on every page by the applicant, the petitioner, the objector or the appellant, as the case may be, or by an advocate appearing on his behalf and shall be dated. Every affidavit, presented in court, shall be signed on every page by the deponent and shall be dated.',
 1),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART I-GENERAL', 'I', 'PRELIMINARY', '7', '(iii)',
 'All the annexures filed by the petitioner, applicant or appellant, along with the petition, application, affidavit, supplementary affidavit or rejoinder affidavit, shall be consecutively numbered as 1, 2, 3 and so on, and all the annexures filed by the respondent or opposite party along with the counter-affidavits, supplementary counter-affidavits or application shall be so consecutively numbered in case of their being filed by first respondent or opposite party as A-1, A-2, A-3 etc., and by second respondent as B-1, B-2 etc.',
 1),

-- Chapter IX — Appeals and Applications
((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART II-CIVIL JURISDICTION', 'IX', 'APPEALS AND APPLICATIONS', '1', '(1)-(2)',
 'Every memorandum of appeal or objection and every application other than an application made in any case pending in the Court shall bear the general heading "In the High Court of Judicature at Allahabad" and shall have written on it immediately below such heading the description of the proceeding and reference to the section/Act/Rule under which it is filed, followed by the case number and year.',
 41),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART II-CIVIL JURISDICTION', 'IX', 'APPEALS AND APPLICATIONS', '5', NULL,
 'Every application containing a statement of facts shall be divided into paragraphs which shall be numbered consecutively and each paragraph shall, as nearly as may be, be confined to a distinct portion of the subject.',
 44),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART II-CIVIL JURISDICTION', 'IX', 'APPEALS AND APPLICATIONS', '6', NULL,
 'Water-marked paper to be used. Every memorandum of appeal or objection or application shall be fairly and legibly written or typewritten, lithographed or printed with quarter margin on one side only of Government water-marked paper. Provided that the Court may, when considered necessary, permit any other paper of foolscap size or both sides of the paper to be used.',
 44),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART II-CIVIL JURISDICTION', 'IX', 'APPEALS AND APPLICATIONS', '11', '(4)',
 'Copies (of memoranda/applications supplied to the Court) shall be fairly and legibly written or typewritten, lithographed or printed with quarter margin on one side of durable paper. Provided that the Court may, when considered necessary, permit any other paper of foolscap size or both sides of the paper to be used.',
 46),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART II-CIVIL JURISDICTION', 'IX', 'APPEALS AND APPLICATIONS', NULL, NULL,
 'Every memorandum of appeal or objection and every application shall be in the language of the Court. Where papers filed are not in English or the language of the State, translations/transliterations are required per the accompanying rules.',
 43),

-- Chapter XIII — Paper Book in First Appeal
((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART II-CIVIL JURISDICTION', 'XIII', 'PAPER BOOK IN FIRST APPEAL', '2', NULL,
 'The paper book in a First Appeal shall, unless otherwise directed by the Chief Justice, be either typewritten or cyclostyled on one side of stout paper with double spacing, and consist of a fly-leaf, an index, and copies/transliterations/translations of the necessary papers.',
 63),

-- Chapter XVIII — Criminal Proceedings (Bail)
((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART III-CRIMINAL JURISDICTION', 'XVIII', 'PROCEEDINGS OTHER THAN ORIGINAL TRIALS', '18', '(1)',
 'No application for bail shall be entertained unless accompanied by a copy of the judgment or order appealed against/sought to be revised and a copy of the order passed by the Sessions Judge on the bail application, and unless the accused has surrendered (except where released on bail after conviction under Section 389(3) CrPC).',
 87),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART III-CRIMINAL JURISDICTION', 'XVIII', 'PROCEEDINGS OTHER THAN ORIGINAL TRIALS', '18', '(2)',
 'Every application for bail in a case under investigation or pending in a lower Court shall state whether an application for bail had or had not been previously made before the Magistrate and the Sessions Judge concerned, and the result of such applications, if any.',
 87),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART III-CRIMINAL JURISDICTION', 'XVIII', 'PROCEEDINGS OTHER THAN ORIGINAL TRIALS', '18', '(3)(a)-(c)',
 'Save in exceptional circumstances, no order granting bail shall be made unless notice has been given to the Government Advocate and not less than ten days have elapsed between such notice and the hearing. If the bail application is not moved within two days after this ten-day period, two days'' previous notice of the exact hearing date must be given to the Government Advocate.',
 87),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART III-CRIMINAL JURISDICTION', 'XVIII', 'PROCEEDINGS OTHER THAN ORIGINAL TRIALS', '18', '(4)',
 'Every bail application shall prominently show on the first page: the crime number, the police station, the section(s) and Act/Rules under which the applicant is being prosecuted or convicted, and whether the application is the first, second, or a subsequent application before this Court. It shall be accompanied by a copy of the FIR and state: (a) the date of the alleged occurrence, (b) the date of the applicant''s arrest.',
 88),

-- Chapter XXII — Writ Petitions (Art. 226/227)
((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART IV-ENFORCEMENT OF FUNDAMENTAL RIGHTS', 'XXII',
 'DIRECTION, ORDER OR WRIT UNDER ARTICLE 226 AND ARTICLE 227 OF THE CONSTITUTION OTHER THAN A WRIT IN THE NATURE OF HABEAS CORPUS',
 '1', '(1)',
 'An application for a direction, order or writ under Article 226 and Article 227 of the Constitution other than habeas corpus shall be made to the Division Bench appointed to receive applications, or the Judge appointed to receive applications in civil matters if no such Bench is sitting. Where ad-interim relief is sought, a separate application shall be made, after furnishing copies of the plea and supporting documents to the other side, unless the Court dispenses with this on being satisfied of urgency.',
 99),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART IV-ENFORCEMENT OF FUNDAMENTAL RIGHTS', 'XXII',
 'DIRECTION, ORDER OR WRIT UNDER ARTICLE 226 AND ARTICLE 227 OF THE CONSTITUTION OTHER THAN A WRIT IN THE NATURE OF HABEAS CORPUS',
 '1', '(2)',
 'The application shall set out concisely in numbered paragraphs the facts upon which the applicant relies and the grounds upon which the Court is asked to issue a direction, order or writ, and shall conclude with a prayer stating clearly the exact nature of relief sought. It shall be accompanied by an affidavit verifying the facts by reference to the paragraph numbers.',
 100),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART IV-ENFORCEMENT OF FUNDAMENTAL RIGHTS', 'XXII',
 'DIRECTION, ORDER OR WRIT UNDER ARTICLE 226 AND ARTICLE 227 OF THE CONSTITUTION OTHER THAN A WRIT IN THE NATURE OF HABEAS CORPUS',
 '1', '(3)(i)-(iv)',
 'The petitioner(s) shall categorically state in the opening paragraph that no Writ Petition, Application (including review), or other proceeding arising from or related to the impugned order or relief sought has been filed or is pending before this Court at Allahabad or Lucknow or any Court/Authority/Tribunal. If any related proceeding is pending elsewhere, full details shall be given. In a subsequent paragraph, a categorical statement shall indicate whether the petitioner has received or not received notice of any caveat application. Any substantial omission or misstatement shall render the application liable to be dismissed summarily.',
 101),

((SELECT id FROM court_identities WHERE short_code='AHC'),
 'PART IV-ENFORCEMENT OF FUNDAMENTAL RIGHTS', 'XXII',
 'DIRECTION, ORDER OR WRIT UNDER ARTICLE 226 AND ARTICLE 227 OF THE CONSTITUTION OTHER THAN A WRIT IN THE NATURE OF HABEAS CORPUS',
 '7', NULL,
 'No second application on same facts. Where an application has been rejected, it shall not be competent for the applicant to make a second application on the same facts.',
 103)

ON CONFLICT (court_identity_id, chapter_number, rule_number, rule_subsection) DO NOTHING;


-- =====================================================================
-- SECTION 3: court_rule_document_mapping — RAG retrieval rules
-- Maps document_type_key -> which chapters to pull at draft time.
-- =====================================================================
CREATE TABLE IF NOT EXISTS court_rule_document_mapping (
  id                  BIGSERIAL PRIMARY KEY,
  court_identity_id   BIGINT NOT NULL REFERENCES court_identities(id) ON DELETE CASCADE,
  document_type_key   TEXT NOT NULL,
  chapter_number      TEXT NOT NULL,
  relevance_note      TEXT,
  is_mandatory_source BOOLEAN DEFAULT true,
  UNIQUE(court_identity_id, document_type_key, chapter_number)
);

INSERT INTO court_rule_document_mapping
  (court_identity_id, document_type_key, chapter_number, relevance_note, is_mandatory_source)
VALUES
-- writ_petition_civil
((SELECT id FROM court_identities WHERE short_code='AHC'), 'writ_petition_civil', 'I',
 'Signing/dating requirements (every page) and annexure numbering scheme.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'writ_petition_civil', 'IX',
 'General heading format, paragraph numbering, paper/format rules (legacy paper-era, cited for completeness).', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'writ_petition_civil', 'XXII',
 'Substantive Art. 226/227 procedure — opening paragraph requirements, interim relief structure, no-second-application rule.', true),

-- writ_petition_criminal
((SELECT id FROM court_identities WHERE short_code='AHC'), 'writ_petition_criminal', 'I',
 'Signing/dating requirements and annexure numbering.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'writ_petition_criminal', 'IX',
 'General heading format, paragraph numbering.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'writ_petition_criminal', 'XXII',
 'Ch. XXII governs FIR-quashing/anticipatory-protection writs (filed under Art. 226, not a separate criminal writ chapter). Opening paragraph, caveat, no-second-application rules all apply.', true),

-- bail_application
((SELECT id FROM court_identities WHERE short_code='AHC'), 'bail_application', 'I',
 'Signing/dating and annexure numbering requirements.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'bail_application', 'XVIII',
 'Rule 18 governs bail application content requirements — first-page crime details, prior application disclosure, GA notice period.', true),

-- anticipatory_bail
((SELECT id FROM court_identities WHERE short_code='AHC'), 'anticipatory_bail', 'I',
 'Signing/dating requirements.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'anticipatory_bail', 'XVIII',
 'Rule 18 applies by extension to anticipatory bail (Sec. 438 CrPC/482 BNSS) filed at HC — confirm with lawyer whether anticipatory-bail-specific sub-rule exists beyond Rule 18.', false),

-- civil_appeal
((SELECT id FROM court_identities WHERE short_code='AHC'), 'civil_appeal', 'I',
 'Signing/dating requirements.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'civil_appeal', 'IX',
 'General heading format + memorandum-of-appeal format conventions (First Appeal / Second Appeal description).', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'civil_appeal', 'XI',
 'Presentation of appeals and applications.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'civil_appeal', 'XIII',
 'Paper book double-spacing requirement — applies to First Appeal paper-books, not the memorandum of appeal itself.', false),

-- criminal_appeal
((SELECT id FROM court_identities WHERE short_code='AHC'), 'criminal_appeal', 'I',
 'Signing/dating requirements.', true),
((SELECT id FROM court_identities WHERE short_code='AHC'), 'criminal_appeal', 'XX',
 'Examination of judgments of Sessions Judges — relevant for criminal appeal drafting context; verify applicability with lawyer.', false)

ON CONFLICT (court_identity_id, document_type_key, chapter_number) DO NOTHING;


-- =====================================================================
-- SECTION 4: court_formatting_rules — sourced formatting values
-- Paper-era rules from 1952. E-filing specs NOT YET SOURCED — see note.
-- =====================================================================
CREATE TABLE IF NOT EXISTS court_formatting_rules (
  id                       BIGSERIAL PRIMARY KEY,
  court_identity_id        BIGINT REFERENCES court_identities(id),
  court_level              TEXT,
  font_family              TEXT,
  body_font_size           TEXT,
  line_spacing             TEXT,
  margin_left_inches       NUMERIC,
  margin_right_inches      NUMERIC,
  margin_top_inches        NUMERIC,
  margin_bottom_inches     NUMERIC,
  margin_style             TEXT,
  paper_finish             TEXT,
  court_language           TEXT,
  requires_para_numbering  BOOLEAN DEFAULT false,
  paper_size               TEXT,
  is_sourced_from_rulebook BOOLEAN DEFAULT false,
  source_note              TEXT
);

INSERT INTO court_formatting_rules
  (court_identity_id, font_family, body_font_size, line_spacing, margin_style,
   paper_finish, court_language, requires_para_numbering, paper_size,
   is_sourced_from_rulebook, source_note)
VALUES
((SELECT id FROM court_identities WHERE short_code='AHC'),
 NULL,
 NULL,
 NULL,
 'quarter_margin',
 'water_marked_or_foolscap',
 'English (or language of the Court/State per translation rules)',
 true,
 'Not size-specified — "foolscap size" permitted as alternative to standard water-marked paper',
 true,
 'Sourced from Allahabad HC Rules 1952, Ch. IX R.6/R.11(4), Ch. XIII R.2. PAPER-ERA RULES ONLY (1952). MODERN E-FILING FORMAT (font/size/margin for PDF via the HC e-filing portal) is governed by separate Practice Directions/e-filing circulars NOT YET SOURCED. Do not assume 14pt Times New Roman or A4/2-inch-margin values for Allahabad HC until those circulars are located. Flag this explicitly in the UI export.');


-- =====================================================================
-- SECTION 5: document_structure_rules
-- Universal and court-specific structure rules.
-- source_type set inline in each INSERT (no UPDATE pass).
-- =====================================================================
CREATE TABLE IF NOT EXISTS document_structure_rules (
  id               BIGSERIAL PRIMARY KEY,
  applies_to       TEXT NOT NULL DEFAULT 'ALL',
  rule_key         TEXT NOT NULL,
  rule_description TEXT NOT NULL,
  is_heading       BOOLEAN,
  source_type      TEXT NOT NULL DEFAULT 'convention',
  UNIQUE(applies_to, rule_key)
);

INSERT INTO document_structure_rules (applies_to, rule_key, rule_description, is_heading, source_type)
VALUES
-- Rule-mandated (AHC Rules 1952 — cited chapter/rule)
('ALL', 'annexure_party_specific_numbering',
 'Annexures filed by petitioner/applicant/appellant numbered 1, 2, 3… Respondent (first) uses A-1, A-2… Second respondent uses B-1, B-2… [AHC Rules 1952, Ch. I R.7(iii)]',
 NULL, 'rule_mandated'),

('ALL', 'general_heading_format',
 'Every petition bears the general heading "IN THE HIGH COURT OF JUDICATURE AT ALLAHABAD" (+ "LUCKNOW BENCH" if applicable), with case-type description and number immediately below. [AHC Rules 1952, Ch. IX R.1]',
 NULL, 'rule_mandated'),

('ALL', 'interim_relief_separate_application',
 'Ad-interim relief must be structured as a distinct application (not merely a prayer sub-clause), with copies furnished to the opposite party unless urgency justifies waiver by the Court. [AHC Rules 1952, Ch. XXII R.1(1)]',
 NULL, 'rule_mandated'),

('ALL', 'no_second_application_same_facts',
 'Where a writ application has been rejected, a second application on the same facts is not competent. Must disclose any prior rejection and establish fresh grounds if refiling. [AHC Rules 1952, Ch. XXII R.7]',
 NULL, 'rule_mandated'),

('ALL', 'paragraph_numbering',
 'Every application containing a statement of facts must be divided into consecutively numbered paragraphs, each confined to a distinct portion of the subject. [AHC Rules 1952, Ch. IX R.5]',
 NULL, 'rule_mandated'),

-- Unconfirmed — genuinely ambiguous, flagged for lawyer sign-off
('ALL', 'signature_after_major_sections_only',
 'AMBIGUOUS: AHC Rules 1952 Ch. I R.7(i)-(ii) require every page to be signed and dated. Not confirmed whether the full block (PLACE/DATED/Name/Advocate/Enrollment) repeats per page, or a short signature/initial per page suffices with the full block only at section ends. Currently defaulting to: short signature+date per page footer, full block only at end of Synopsis, Main Petition/Prayer, Affidavit, Vakalatnama. REQUIRES LAWYER CONFIRMATION before relying on this default in the export engine.',
 NULL, 'unconfirmed'),

-- Convention-only (universal Bar practice, no specific AHC rule citation)
('ALL', 'jurisdiction_no_heading',
 'Jurisdiction is a plain numbered paragraph within the main body, never a labeled heading. Content (stating territorial/pecuniary jurisdiction) is required; the "no heading" formatting choice specifically is Bar practice / lawyer-reviewer correction, not independently rule-cited.',
 false, 'convention'),

('ALL', 'affidavit_fresh_page',
 'Affidavit section starts at the top of a new page, with "AFFIDAVIT" as a heading.',
 true, 'convention'),

('ALL', 'vakalatnama_fresh_page',
 'Vakalatnama section starts at the top of a new page, with "VAKALATNAMA" as a heading.',
 true, 'convention'),

('ALL', 'list_of_dates_from_structured_data',
 'The List of Dates and Events table is generated strictly from the structured dates_and_events field. Never invent, reorder, or paraphrase dates not present in structured data.',
 NULL, 'convention'),

('ALL', 'annexures_from_uploaded_docs_only',
 'List of Annexures must list only actual uploaded document names/types. If none uploaded, state "No supporting documents uploaded" — never invent generic placeholders.',
 NULL, 'convention'),

('ALL', 'index_heading_convention',
 'Include "INDEX" as a labeled table (S.No | Particulars | Page No.) at the start of the petition bundle. Only confirmed by AHC Rules for First Appeal paper-books (Ch. XIII); for writ petitions this is universal Bar practice.',
 true, 'convention'),

('ALL', 'synopsis_heading_convention',
 'Include "SYNOPSIS" as a labeled heading. Content is rule-mandated (Ch. IX R.7(1), Ch. XVIII R.3(1)); the specific heading label is Bar practice convention. [source_type: rule_mandated for content, convention for label]',
 true, 'rule_mandated'),

('ALL', 'list_of_dates_heading_convention',
 'Include "LIST OF DATES AND EVENTS" as a labeled table separate from Synopsis. Rule text bundles this into the same synopsis requirement; splitting into two headed sections is Bar practice convention.',
 true, 'convention'),

('ALL', 'prayer_heading_convention',
 'Include "PRAYER" as a labeled heading before the relief clause. Content is rule-mandated (Ch. XXII R.1(2) — application must conclude with a prayer stating exact relief); the heading label itself is convention.',
 true, 'rule_mandated'),

('ALL', 'grounds_heading_convention',
 'Include "GROUNDS" as a labeled heading before numbered grounds paragraphs. Numbered-paragraph format is rule-mandated (Ch. IX R.5); the "GROUNDS" label is Bar practice convention.',
 true, 'convention'),

('ALL', 'annexures_heading_convention',
 'Include "LIST OF ANNEXURES" as a labeled table. Annexure numbering scheme is rule-mandated (Ch. I R.7(iii)); the heading label/tabular format is convention.',
 true, 'convention'),

('high_court', 'paper_format_legacy',
 'Legacy paper-filing format (water-marked/foolscap paper, quarter margin) per AHC Rules 1952 Ch. IX R.6/R.11(4). Does NOT govern modern PDF e-filing — see court_formatting_rules.source_note for the e-filing gap.',
 NULL, 'rule_mandated')

ON CONFLICT (applies_to, rule_key) DO NOTHING;


-- =====================================================================
-- SECTION 6: mandatory_paragraphs
-- Per-doc-type mandatory paragraphs with source_type + citation
-- set directly in each INSERT (no UPDATE pass).
-- =====================================================================
CREATE TABLE IF NOT EXISTS mandatory_paragraphs (
  id                 BIGSERIAL PRIMARY KEY,
  court_level        TEXT NOT NULL,
  bench_name         TEXT,
  document_type_key  TEXT NOT NULL,
  para_key           TEXT NOT NULL,
  para_label         TEXT NOT NULL,
  instruction        TEXT NOT NULL,
  placement          TEXT,
  is_heading         BOOLEAN DEFAULT false,
  is_conditional     BOOLEAN DEFAULT false,
  condition_note     TEXT,
  sort_order         INTEGER DEFAULT 0,
  source_type        TEXT NOT NULL DEFAULT 'convention',
  source_citation    TEXT,
  UNIQUE(court_level, bench_name, document_type_key, para_key)
);

INSERT INTO mandatory_paragraphs
  (court_level, bench_name, document_type_key, para_key, para_label, instruction,
   placement, is_heading, is_conditional, condition_note, sort_order, source_type, source_citation)
VALUES

-- ── Writ Petition (Civil) ────────────────────────────────────────────
('high_court', NULL, 'writ_petition_civil', 'no_prior_petition',
 'No Prior Petition (Opening Paragraph)',
 'MUST be paragraph 1. Categorically state no writ petition/application/review or related proceeding has been filed or is pending before this Court at Allahabad or Lucknow or any other Court/Authority/Tribunal. If pending elsewhere, give full details. Substantial omission or misstatement renders the petition liable to summary dismissal.',
 'opening_paragraph', false, false, NULL, 0,
 'rule_mandated', 'AHC Rules 1952, Ch. XXII R.1(3)(i)-(ii)'),

('high_court', NULL, 'writ_petition_civil', 'caveat_notice_statement',
 'Caveat Notice Statement',
 'MUST be paragraph 2, immediately after no-prior-petition. State categorically whether the petitioner has "received" or "not received" notice of any caveat application.',
 'opening_paragraph', false, false, NULL, 1,
 'rule_mandated', 'AHC Rules 1952, Ch. XXII R.1(3)(iii)'),

('high_court', NULL, 'writ_petition_civil', 'alternative_remedy',
 'Alternative Remedy Exhausted / Inadequate',
 'State why Article 226 is invoked — no alternative statutory remedy exists, or the available remedy is inadequate given the facts.',
 'after_grounds', false, false, NULL, 2,
 'convention', NULL),

('high_court', NULL, 'writ_petition_civil', 'delay_explanation',
 'Delay Explanation',
 'Explain the gap between impugned order date and filing date, if any. Draw content only from dates_and_events data — do not invent dates.',
 'after_grounds', false, true, 'only if gap between impugned_order_date and filing date exceeds 30 days', 3,
 'convention', NULL),

-- ── Writ Petition (Criminal) ─────────────────────────────────────────
('high_court', NULL, 'writ_petition_criminal', 'no_prior_petition',
 'No Prior Petition (Opening Paragraph)',
 'MUST be paragraph 1. Categorically state no petition/application seeking quashing of the same FIR, or anticipatory bail on the same FIR, has been filed or is pending before this Court at Allahabad or Lucknow or any other Court/Authority/Tribunal. Reference lower-court order (OCR-extracted) if applicable. Omission renders the petition liable to summary dismissal.',
 'opening_paragraph', false, false, NULL, 0,
 'rule_mandated', 'AHC Rules 1952, Ch. XXII R.1(3)(i)-(ii)'),

('high_court', NULL, 'writ_petition_criminal', 'caveat_notice_statement',
 'Caveat Notice Statement',
 'MUST be paragraph 2. State "received" or "not received" notice of any caveat application.',
 'opening_paragraph', false, false, NULL, 1,
 'rule_mandated', 'AHC Rules 1952, Ch. XXII R.1(3)(iii)'),

('high_court', NULL, 'writ_petition_criminal', 'alternative_remedy',
 'Alternative Remedy Exhausted / Inadequate',
 'State why Article 226 / Section 482 CrPC (or Sec. 528 BNSS) route is invoked instead of, or in addition to, trial court remedies.',
 'after_grounds', false, false, NULL, 2,
 'convention', NULL),

('high_court', NULL, 'writ_petition_criminal', 'delay_explanation',
 'Delay Explanation',
 'Explain gap between FIR date and filing date, if any. Draw from dates_and_events only.',
 'after_grounds', false, true, 'only if gap between FIR date and filing date exceeds 30 days', 3,
 'convention', NULL),

('high_court', NULL, 'writ_petition_criminal', 'no_coercive_action_undertaking',
 'Undertaking Regarding Investigation',
 'State that petitioner undertakes full cooperation with investigation and will appear before the IO as required.',
 'after_grounds', false, false, NULL, 4,
 'convention', NULL),

-- ── Bail Application (District) ──────────────────────────────────────
('district', NULL, 'bail_application', 'jurisdiction',
 'Jurisdiction',
 'State Sessions Court jurisdiction as a plain numbered paragraph — NO heading.',
 'after_grounds', false, false, NULL, 1,
 'convention', NULL),

('district', NULL, 'bail_application', 'no_previous_bail',
 'No Previous Bail Application',
 'State whether an earlier bail application on the same FIR has been filed before this or any other court, and its outcome. Reference lower court order (OCR-extracted) if available.',
 'after_grounds', false, false, NULL, 2,
 'convention', NULL),

('district', NULL, 'bail_application', 'not_absconder',
 'Not an Absconder / Cooperation with Investigation',
 'State the accused is not a proclaimed offender, has not absconded, and has cooperated / will cooperate with investigation.',
 'after_grounds', false, false, NULL, 3,
 'convention', NULL),

('district', NULL, 'bail_application', 'roots_in_society',
 'Roots in Society / Flight Risk',
 'State facts establishing permanent residence, family ties, and employment in the jurisdiction.',
 'after_grounds', false, false, NULL, 4,
 'convention', NULL),

('district', NULL, 'bail_application', 'no_tampering_undertaking',
 'Undertaking Against Tampering',
 'State the accused undertakes not to tamper with evidence or influence witnesses if granted bail.',
 'after_grounds', false, false, NULL, 5,
 'convention', NULL),

-- ── Bail Application (High Court — AHC Ch. XVIII specific) ───────────
('high_court', NULL, 'bail_application', 'first_page_crime_details',
 'First-Page Crime Details',
 'The first page must prominently show: crime number, police station, section(s) and Act/Rules under which prosecuted/convicted, and whether this is the first/second/subsequent HC bail application. Must be accompanied by a copy of the FIR. State the date of alleged occurrence and date of arrest.',
 'opening_paragraph', false, false, NULL, 0,
 'rule_mandated', 'AHC Rules 1952, Ch. XVIII R.18(4)'),

('high_court', NULL, 'bail_application', 'no_previous_bail_hc',
 'No Previous Bail Application (High Court level)',
 'State whether application for bail had or had not been previously made before the Magistrate and the Sessions Judge concerned, and the result of such applications, if any.',
 'after_grounds', false, false, NULL, 2,
 'rule_mandated', 'AHC Rules 1952, Ch. XVIII R.18(2)'),

-- ── Anticipatory Bail (High Court) ───────────────────────────────────
('high_court', NULL, 'anticipatory_bail', 'jurisdiction',
 'Jurisdiction',
 'State territorial jurisdiction as a plain numbered paragraph — NO heading.',
 'after_grounds', false, false, NULL, 1,
 'convention', NULL),

('high_court', NULL, 'anticipatory_bail', 'no_previous_application',
 'No Previous Anticipatory Bail Application',
 'State whether an earlier anticipatory bail application on the same FIR/apprehension has been filed before this or any other court, and its outcome.',
 'after_grounds', false, false, NULL, 2,
 'unconfirmed', 'AHC Rules 1952, Ch. XVIII R.18 — applicability to anticipatory bail NOT confirmed in rule text. Rule 18 says "application for bail", does not explicitly address Sec. 438/482 anticipatory bail. Confirm with lawyer.'),

('high_court', NULL, 'anticipatory_bail', 'reasonable_apprehension',
 'Reasonable Apprehension of Arrest',
 'State specific facts giving rise to reasonable apprehension of arrest — statutory precondition for Sec. 438 CrPC/Sec. 482 BNSS relief. Must not be generic.',
 'after_grounds', false, false, NULL, 3,
 'convention', NULL),

('high_court', NULL, 'anticipatory_bail', 'not_absconder',
 'Not an Absconder / Willingness to Cooperate',
 'State applicant is not a proclaimed offender and is willing to join investigation as and when called.',
 'after_grounds', false, false, NULL, 4,
 'convention', NULL),

-- ── Civil Appeal (High Court) ─────────────────────────────────────────
('high_court', NULL, 'civil_appeal', 'jurisdiction',
 'Jurisdiction',
 'State appellate jurisdiction basis (statute/order under which appeal lies) — plain numbered paragraph, NO heading.',
 'after_grounds', false, false, NULL, 1,
 'convention', NULL),

('high_court', NULL, 'civil_appeal', 'limitation_compliance',
 'Limitation Compliance',
 'State date of impugned judgment/decree and confirm the appeal is within the statutory limitation period, or attach a delay condonation application.',
 'after_grounds', false, false, NULL, 2,
 'convention', NULL),

('high_court', NULL, 'civil_appeal', 'no_prior_appeal',
 'No Prior Appeal',
 'State no earlier appeal against the same judgment/decree has been filed and withdrawn or dismissed on merits before this or any other court.',
 'after_grounds', false, false, NULL, 3,
 'convention', NULL),

-- ── Criminal Appeal (High Court) ─────────────────────────────────────
('high_court', NULL, 'criminal_appeal', 'jurisdiction',
 'Jurisdiction',
 'State appellate jurisdiction basis (CrPC/BNSS provision) — plain numbered paragraph, NO heading.',
 'after_grounds', false, false, NULL, 1,
 'convention', NULL),

('high_court', NULL, 'criminal_appeal', 'limitation_compliance',
 'Limitation Compliance',
 'State date of impugned trial court judgment/order and confirm filing within limitation, or attach delay condonation application.',
 'after_grounds', false, false, NULL, 2,
 'convention', NULL),

('high_court', NULL, 'criminal_appeal', 'custody_status',
 'Custody Status of Appellant',
 'State whether appellant is in custody or on bail, and since when.',
 'after_grounds', false, false, NULL, 3,
 'convention', NULL),

-- ── Legal Notice (pre-litigation / district) ──────────────────────────
('district', NULL, 'legal_notice', 'demand_timeline',
 'Demand Compliance Timeline',
 'State a specific reasonable timeframe (e.g. 15/30 days) for compliance, failing which legal proceedings will be initiated.',
 'before_prayer', false, false, NULL, 1,
 'convention', NULL),

('district', NULL, 'legal_notice', 'reservation_of_rights',
 'Reservation of Rights',
 'State this notice is issued without prejudice to any other rights and remedies available under law.',
 'before_prayer', false, false, NULL, 2,
 'convention', NULL)

ON CONFLICT (court_level, bench_name, document_type_key, para_key) DO NOTHING;


-- =====================================================================
-- VERIFICATION QUERIES (run after migration, should return 0 rows each)
-- =====================================================================
-- SELECT rule_key, source_type FROM document_structure_rules WHERE source_type IS NULL;
-- SELECT para_key, document_type_key, source_type FROM mandatory_paragraphs WHERE source_type IS NULL;
-- SELECT chapter_number, count(*) FROM court_rule_sections GROUP BY chapter_number ORDER BY 1;
--   Expected: I(2), IX(5), XIII(1), XVIII(4), XXII(4)
-- SELECT short_code, court_name, has_benches FROM court_identities;
--   Expected: AHC | Allahabad High Court | true
