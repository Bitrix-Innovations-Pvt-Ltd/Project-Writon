"""
Full-act ingestion for legal_code_sections.

Replaces the hand-picked "greatest hits" statute seed with the complete text of
every act in legal_codes, parsed from IndianKanoon's Akoma-Ntoso act pages
(server-rendered, robots.txt permits /doc/ except an explicit takedown list).

Per act:
  1. Discover the "Entire Act" doc id via IK search (majority vote over the
     top results), verify the page title matches code_name + year, and cache
     the id in legal_codes.ik_doc_id so discovery runs once.
  2. Parse <section class="akn-section" id="section_N"> blocks into
     (section_number, title, text).
  3. Upsert into legal_code_sections: insert missing sections; update an
     existing section only when the parsed text is substantially longer than
     what is stored (the old seed rows are truncated summaries). Any changed
     row gets embedding=NULL so scripts/embed_statutes.py re-embeds it.

Also purges junk rows (pure-numeric section_number > 999 — amendment years
like '2015'/'2017' that were ingested as sections) and seeds frequently-cited
acts that were missing from legal_codes entirely (NDPS, Limitation, MV, ...).

Usage:
  python scripts/ingest_full_acts.py                 # all codes except COI
  python scripts/ingest_full_acts.py NI PMLA POCSO   # subset by short_code
  python scripts/ingest_full_acts.py --dry-run NI    # parse + report only
"""
import html
import os
import re
import sys
import time

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

IK_BASE = "https://indiankanoon.org"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WritOnline-ingester/1.0"}
FETCH_DELAY_S = 1.2
MAX_NUMERIC_SECTION = 999  # no Indian act has a pure-numeric section beyond this

# Frequently-cited acts referenced by the drafting pipeline's retrieval hints
# but absent from legal_codes. Seed data (same pattern as scripts/seed_legal_codes.py).
SEED_NEW_CODES = [
    ("NDPS",       "Narcotic Drugs and Psychotropic Substances Act, 1985", 1985, ["criminal", "special"]),
    ("LIMITATION", "Limitation Act, 1963",                                 1963, ["civil", "procedure"]),
    ("MV",         "Motor Vehicles Act, 1988",                             1988, ["civil", "transport"]),
    ("ATA",        "Administrative Tribunals Act, 1985",                   1985, ["civil", "service"]),
    ("COCA",       "Contempt of Courts Act, 1971",                         1971, ["civil", "criminal", "constitutional"]),
    ("RERA",       "Real Estate (Regulation and Development) Act, 2016",   2016, ["civil", "property", "consumer"]),
    ("NGT",        "National Green Tribunal Act, 2010",                    2010, ["civil", "environment"]),
    ("CCA",        "Commercial Courts Act, 2015",                          2015, ["civil", "procedure", "corporate"]),
    ("IDA",        "Industrial Disputes Act, 1947",                        1947, ["civil", "labour"]),
    ("SMA",        "Special Marriage Act, 1954",                           1954, ["civil", "family"]),
    ("GWA",        "Guardians and Wards Act, 1890",                        1890, ["civil", "family"]),
    ("HMGA",       "Hindu Minority and Guardianship Act, 1956",            1956, ["civil", "family"]),
    ("HAMA",       "Hindu Adoptions and Maintenance Act, 1956",            1956, ["civil", "family"]),
]

_session = requests.Session()
_session.headers.update(UA)
_robots_disallowed: set = set()


def _load_robots():
    try:
        txt = _session.get(f"{IK_BASE}/robots.txt", timeout=20).text
        for m in re.finditer(r"Disallow:\s*/doc(?:fragment)?/(\d+)/", txt):
            _robots_disallowed.add(m.group(1))
    except Exception as e:
        print(f"[robots] fetch failed ({e}) — proceeding with empty disallow list")


def _get(url: str) -> str:
    for attempt in range(4):
        try:
            resp = _session.get(url, timeout=60)
            if resp.status_code == 200:
                time.sleep(FETCH_DELAY_S)
                return resp.content.decode("utf-8", errors="replace")
            if resp.status_code in (403, 429, 503):
                wait = 5 * (attempt + 1)
                print(f"    HTTP {resp.status_code} — backing off {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except requests.RequestException as e:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"unreachable: {url}")


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(fragment: str) -> str:
    # Strip, unescape, then strip again: IK's amendment annotations contain
    # entity-escaped markup (&lt;SPAN class=amd1&gt;), so unescaping a
    # tag-free string can hand back live tags. One pass leaves them behind.
    txt = _TAG_RE.sub(" ", fragment)
    txt = html.unescape(txt)
    txt = _TAG_RE.sub(" ", txt)
    txt = txt.replace("�", " ")  # mojibake em-dashes in IK markup
    return re.sub(r"\s+", " ", txt).strip()


def discover_doc_id(code_name: str, year: int) -> str | None:
    """Majority-vote the 'Entire Act' target across IK search results.

    Falls back to a title-restricted search when the plain search is dominated
    by cousin acts (e.g. BNS searches surface BNSS entire-act links).
    """
    base_name = code_name.split(",")[0].strip()
    candidates: list = []
    for form in (f"{code_name} doctypes: laws", f"title:({base_name}) doctypes: laws"):
        page = _get(f"{IK_BASE}/search/?formInput={requests.utils.quote(form)}")
        ids = re.findall(r'<a href="/doc/(\d+)/">\s*Entire Act', page)
        counts: dict = {}
        for i in ids:
            counts[i] = counts.get(i, 0) + 1
        candidates.extend(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))
    if not candidates:
        return None
    seen = set()
    for doc_id, _ in candidates:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        if doc_id in _robots_disallowed:
            continue
        title_page = _get(f"{IK_BASE}/doc/{doc_id}/")
        m = re.search(r'class="doc_title"[^>]*>([^<]{5,150})', title_page)
        title = _strip_tags(m.group(1)) if m else ""
        # Verify: the page title must carry the enactment year and a
        # distinctive token of the act name (guards against amendment acts).
        name_tokens = [w for w in re.findall(r"[A-Za-z]{5,}", code_name)][:3]
        if str(year) in title and all(t.lower() in title.lower() for t in name_tokens):
            if "amendment" in title.lower() and "amendment" not in code_name.lower():
                continue
            return doc_id
    return None


# akn-section blocks nest other <section> elements (akn-subsection /
# akn-paragraph), so neither a lazy `.*?</section>` (truncates at the first
# subsection) nor a slice to the next section opening (swallows the entire
# rest of the page when sections are not in document order, as in CPC's
# Schedules) is correct. Walk the tags and close at matching depth instead.
_SECTION_OPEN_RE = re.compile(r'<section class="akn-section" id="section_([0-9A-Za-z\-.]+)">')
_SECTION_TAG_RE = re.compile(r"<section\b|</section>")
_H3_RE = re.compile(r"<h3>(.*?)</h3>", re.S)

MAX_SECTION_CHARS = 20000  # guard: no real section runs longer than this


def _section_body(page_html: str, start: int) -> str:
    """Body of the <section> element that opens at `start`, by tag depth."""
    depth = 1
    pos = start
    for tag in _SECTION_TAG_RE.finditer(page_html, start):
        depth += 1 if tag.group(0) != "</section>" else -1
        if depth == 0:
            return page_html[start:tag.start()]
        pos = tag.end()
    return page_html[start:pos]


def parse_entire_act(page_html: str) -> list:
    """Return [(section_number, title, text)] from an IK Akoma-Ntoso act page."""
    out = {}
    for m in _SECTION_OPEN_RE.finditer(page_html):
        raw_num = m.group(1)
        body = _section_body(page_html, m.end())
        h3 = _H3_RE.search(body)
        title = ""
        if h3:
            title = _strip_tags(h3.group(1))
            # "138. Dishonour of cheque ...  —" → drop leading number + trailing dash
            title = re.sub(r"^\s*[0-9A-Za-z\-.]+\s*\.?\s*", "", title, count=1)
            title = title.rstrip(" .—-–")
            # Some acts run the opening provision straight into the heading;
            # keep only the heading clause so titles stay searchable labels.
            title = re.split(r"\s[-–—]\s|\.\s*[-–—]|\s*\(1\)\s", title)[0].strip()
            title = title[:180].rstrip(" .—-–")
            body = body[h3.end():]
        text = _strip_tags(body)
        num = raw_num.strip(".").strip()
        if num.isdigit() and int(num) > MAX_NUMERIC_SECTION:
            continue  # amendment-year artifacts
        if len(text) > MAX_SECTION_CHARS:
            text = text[:MAX_SECTION_CHARS]
        if len(text) < 20:
            continue  # empty / repealed shells
        # duplicates (amended versions repeated on the page): keep the longest
        if num not in out or len(text) > len(out[num][1]):
            out[num] = (title, text)
    return [(num, t, txt) for num, (t, txt) in out.items()]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv

    conn = psycopg2.connect(os.environ["DATABASE_URL"].strip('"'))
    conn.set_session(readonly=False, autocommit=False)
    cur = conn.cursor()

    # Schema prep + seed missing codes + junk purge (idempotent)
    # The original seed inserted explicit ids without advancing the sequence
    cur.execute("SELECT setval(pg_get_serial_sequence('legal_codes','id'), (SELECT max(id) FROM legal_codes))")
    cur.execute("ALTER TABLE legal_codes ADD COLUMN IF NOT EXISTS ik_doc_id varchar")
    cur.execute("ALTER TABLE legal_codes ADD COLUMN IF NOT EXISTS aliases varchar[]")
    for short, name, year, domains in SEED_NEW_CODES:
        cur.execute(
            """INSERT INTO legal_codes (short_code, code_name, year_enacted, status, domains)
               SELECT %s, %s, %s, 'active', %s
               WHERE NOT EXISTS (SELECT 1 FROM legal_codes WHERE short_code = %s)""",
            (short, name, year, domains, short),
        )
    cur.execute(
        r"""DELETE FROM legal_code_sections
            WHERE section_number ~ '^\d+$' AND section_number::int > %s
            RETURNING id, legal_code_id, section_number""",
        (MAX_NUMERIC_SECTION,),
    )
    purged = cur.fetchall()
    if purged:
        print(f"Purged {len(purged)} junk section rows: {purged}")
    # Content-free rows (repealed/omitted stubs from the original seed) can be
    # matched by BM25 but carry nothing for the LLM to cite.
    cur.execute("DELETE FROM legal_code_sections WHERE coalesce(section_text, '') = ''")
    if cur.rowcount:
        print(f"Purged {cur.rowcount} empty-text section rows")
    conn.commit()

    cur.execute(
        "SELECT id, short_code, code_name, year_enacted, ik_doc_id FROM legal_codes "
        "WHERE short_code != 'COI' ORDER BY id"
    )
    codes = cur.fetchall()
    if args:
        wanted = {a.upper() for a in args}
        codes = [c for c in codes if c[1].upper() in wanted]

    _load_robots()
    grand_ins = grand_upd = 0

    for code_id, short, name, year, ik_doc_id in codes:
        print(f"\n=== {short}: {name} ===")
        try:
            if not ik_doc_id:
                ik_doc_id = discover_doc_id(name, year or 0)
                if not ik_doc_id:
                    print("  !! could not discover Entire Act doc id — skipped")
                    continue
                cur.execute("UPDATE legal_codes SET ik_doc_id=%s WHERE id=%s", (ik_doc_id, code_id))
                conn.commit()
                print(f"  discovered ik_doc_id={ik_doc_id}")

            sections = parse_entire_act(_get(f"{IK_BASE}/doc/{ik_doc_id}/"))
            if len(sections) < 5:
                print(f"  !! parsed only {len(sections)} sections — refusing to ingest (bad page?)")
                continue
            print(f"  parsed {len(sections)} sections")
            if dry_run:
                for num, title, text in sections[:8]:
                    print(f"    s.{num} [{title[:60]}] {len(text)} chars")
                continue

            ins = upd = 0
            for num, title, text in sections:
                cur.execute(
                    """INSERT INTO legal_code_sections
                           (legal_code_id, section_number, title, section_text)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (legal_code_id, section_number) DO UPDATE
                       SET title = EXCLUDED.title,
                           section_text = EXCLUDED.section_text,
                           embedding = NULL
                       WHERE char_length(EXCLUDED.section_text) >
                             char_length(legal_code_sections.section_text) * 1.2
                          -- repair rows left over-long or title-bloated by the
                          -- earlier depth-unaware parser (correct text is shorter,
                          -- so the "only if longer" rule would skip them)
                          OR char_length(legal_code_sections.section_text) > %s
                          OR char_length(legal_code_sections.title) > 180
                       RETURNING (xmax = 0) AS inserted""",
                    (code_id, num, title[:500], text, MAX_SECTION_CHARS),
                )
                row = cur.fetchone()
                if row is not None:
                    if row[0]:
                        ins += 1
                    else:
                        upd += 1
            conn.commit()
            grand_ins += ins
            grand_upd += upd
            print(f"  inserted {ins}, updated {upd}, untouched {len(sections) - ins - upd}")
        except Exception as e:
            conn.rollback()
            print(f"  !! {short} failed: {e}")

    cur.execute("SELECT count(*) FROM legal_code_sections WHERE embedding IS NULL")
    pending = cur.fetchone()[0]
    print(f"\nDone. Inserted {grand_ins}, updated {grand_upd} sections total.")
    print(f"{pending} sections now need embedding -- run: python scripts/embed_statutes.py")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
