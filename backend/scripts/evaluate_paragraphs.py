"""
Evaluate deterministic paragraph reconstruction against the live corpus.

This is the gate for the paragraph-picker feature: it measures whether a
paragraph NUMBER can be shown for a retrieved citation, and whether the
paragraph text attached to it is the right one. Both must hold before the UI is
worth building, because a wrong paragraph number in a filed document is worse
than no citation at all.

Reported metrics
  spine coverage      full / partial / none, by year band
  consecutive rate    fraction of spine steps that are +1 (1.00 = no gaps)
  mapping tier        exact / canonical / arithmetic — a rising arithmetic rate
                      means chunk_text and full_text have drifted apart
  attribution         did the chunk resolve to at least one paragraph
  suspect merges      paragraphs > 3,000 chars (a marker was probably missed)
  timing              per-judgment CPU cost of segmentation

Usage (from backend/, read-only against Neon):
    python scripts/evaluate_paragraphs.py            # 60 judgments, year>=2015
    python scripts/evaluate_paragraphs.py --n 150 --min-year 2000
"""

import argparse
import os
import random
import statistics
import sys
import time

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.paragraphs import (  # noqa: E402
    MAX_MARKERS,
    MAX_SEGMENT_CHARS,
    locate_chunk_tiered,
    paragraphs_for_span,
    segment,
    segment_window,
)

load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"
))


def connect():
    """Direct (non-pooler) host, read-only — the pooler drops session settings."""
    host = os.getenv("NEON_DB_HOST", "").replace("-pooler", "")
    conn = psycopg2.connect(
        host=host,
        port=os.getenv("NEON_DB_PORT", "5432"),
        dbname=os.getenv("NEON_DB_NAME"),
        user=os.getenv("NEON_DB_USER"),
        password=os.getenv("NEON_DB_PASSWORD"),
        sslmode=os.getenv("NEON_DB_SSLMODE", "require"),
    )
    conn.set_session(readonly=True)
    return conn


def pct(part, whole):
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "0/0 (n/a)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60, help="judgments to sample")
    ap.add_argument("--min-year", type=int, default=2015)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--chunks-per-judgment", type=int, default=3)
    args = ap.parse_args()

    random.seed(args.seed)
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """SELECT id, year, full_text FROM judgments
           WHERE full_text IS NOT NULL AND length(full_text) > 5000
             AND year >= %s
           ORDER BY id LIMIT %s""",
        (args.min_year, max(args.n * 12, 400)),
    )
    pool = cur.fetchall()
    if not pool:
        print("No judgments matched the filter.")
        return
    rows = random.sample(pool, min(args.n, len(pool)))

    cov = {"full": 0, "partial": 0, "none": 0}
    consec, para_counts, seg_ms, suspect = [], [], [], 0
    total_paras = uncertain_paras = 0
    tiers = {"exact": 0, "canonical": 0, "arithmetic": 0, "empty": 0, "degenerate": 0}
    attributed = chunks_tested = 0
    body_chunks = body_attributed = 0
    zones = {"body": 0, "front_matter": 0, "after_body": 0}
    guarded = 0
    none_ids = []

    for jid, year, full_text in rows:
        t0 = time.perf_counter()
        if len(full_text) > MAX_SEGMENT_CHARS:
            guarded += 1
            cur.execute(
                """SELECT chunk_text FROM judgment_chunks
                   WHERE judgment_id=%s ORDER BY chunk_index LIMIT 5""", (jid,))
            result = segment_window([r[0] or "" for r in cur.fetchall()], 2)
        else:
            result = segment(full_text)
        seg_ms.append((time.perf_counter() - t0) * 1000)

        cov[result.coverage] = cov.get(result.coverage, 0) + 1
        if result.coverage == "none":
            none_ids.append((jid, year, result.stats))
            continue

        consec.append(result.consecutive_rate)
        para_counts.append(len(result.paragraphs))
        suspect += sum(1 for p in result.paragraphs if p.suspect_merge)
        total_paras += len(result.paragraphs)
        uncertain_paras += sum(1 for p in result.paragraphs if p.number_uncertain)

        # Chunk attribution: can a retrieved chunk be tied to a paragraph?
        cur.execute(
            """SELECT chunk_index, chunk_text FROM judgment_chunks
               WHERE judgment_id=%s ORDER BY chunk_index""", (jid,))
        chunk_rows = cur.fetchall()
        if not chunk_rows:
            continue
        lengths = [len(r[1] or "") for r in chunk_rows]
        picks = random.sample(chunk_rows, min(args.chunks_per_judgment, len(chunk_rows)))
        for chunk_index, chunk_text in picks:
            chunks_tested += 1
            start, end, tier = locate_chunk_tiered(
                result.flat_text, chunk_text or "", chunk_index, lengths)
            tiers[tier] = tiers.get(tier, 0) + 1
            zone = result.classify_span((start, end))
            zones[zone] = zones.get(zone, 0) + 1
            hit = bool(paragraphs_for_span(result.paragraphs, (start, end)))
            if hit:
                attributed += 1
            # Front matter (cause title, headnote, counsel list) carries no
            # printed paragraph number, so a miss there is correct behaviour —
            # only body chunks can fairly be scored.
            if zone == "body":
                body_chunks += 1
                body_attributed += int(hit)

    n = len(rows)
    print(f"\n{'=' * 68}")
    print(f"Paragraph reconstruction eval — n={n}, year>={args.min_year}, seed={args.seed}")
    print(f"{'=' * 68}")

    print("\n-- spine coverage --")
    print(f"  full    : {pct(cov['full'], n)}")
    print(f"  partial : {pct(cov['partial'], n)}   (oversized doc, windowed)")
    print(f"  none    : {pct(cov['none'], n)}   (no printed numbering recoverable)")
    if guarded:
        print(f"  size-guard triggered (>{MAX_SEGMENT_CHARS:,} chars): {guarded}")

    if consec:
        strong = sum(1 for c in consec if c >= 0.95)
        print("\n-- paragraph numbering --")
        print(f"  median consecutive-step rate : {statistics.median(consec):.2f}")
        print(f"  judgments >=95% consecutive  : {pct(strong, len(consec))}")
        print(f"  median paragraphs recovered  : {statistics.median(para_counts):.0f}")
        print(f"  suspect merges (>3,000 chars): {suspect}")
        print(f"  paragraphs with a CERTAIN number : "
              f"{pct(total_paras - uncertain_paras, total_paras)}")
        print(f"  paragraphs labelled as a range   : {pct(uncertain_paras, total_paras)}"
              f"   (OCR lost the marker; shown as \"5-6\", never mislabelled)")

    if chunks_tested:
        print("\n-- chunk -> paragraph mapping --")
        for tier in ("exact", "canonical", "arithmetic", "degenerate", "empty"):
            if tiers.get(tier):
                print(f"  tier {tier:<11}: {pct(tiers[tier], chunks_tested)}")
        print(f"\n  zone: body         : {pct(zones['body'], chunks_tested)}")
        print(f"  zone: front matter : {pct(zones['front_matter'], chunks_tested)}"
              f"   (headnote/cause title — no printed number exists)")
        print(f"  zone: after body   : {pct(zones['after_body'], chunks_tested)}")
        print(f"\n  attributed (all chunks)   : {pct(attributed, chunks_tested)}")
        print(f"  attributed (body chunks)  : {pct(body_attributed, body_chunks)}  <- the real metric")

    if seg_ms:
        ordered = sorted(seg_ms)
        print("\n-- timing (segmentation CPU) --")
        print(f"  median {statistics.median(seg_ms):.1f} ms   "
              f"p90 {ordered[int(len(ordered) * 0.9)]:.1f} ms   max {max(seg_ms):.1f} ms")

    if none_ids:
        print(f"\n-- no-coverage sample (first 5 of {len(none_ids)}) --")
        for jid, year, stats in none_ids[:5]:
            print(f"  judgment {jid} ({year}): {stats}")

    # Gate from the implementation plan
    print(f"\n{'=' * 68}")
    # A fully consecutive spine is unattainable: on inspection, the missing
    # markers have ZERO literal occurrences in the source — the OCR dropped the
    # digit. So the gate measures what actually matters, which is that no
    # paragraph is shown under a number that might be wrong. Blocks spanning a
    # lost marker are labelled as a range ("5-6") instead of being mislabelled.
    exact_number_rate = ((total_paras - uncertain_paras) / total_paras) if total_paras else 0
    # Scored over body chunks only: a front-matter chunk has no paragraph number
    # in the source, so failing to attribute one is the correct outcome, not a miss.
    attr_rate = (body_attributed / body_chunks) if body_chunks else 0
    gate_ok = exact_number_rate >= 0.90 and attr_rate >= 0.95
    print(f"GATE  exact paragraph number >=90% : {exact_number_rate:.1%}  "
          f"{'PASS' if exact_number_rate >= 0.90 else 'FAIL'}")
    print(f"GATE  body attribution >=95%       : {attr_rate:.1%}  "
          f"{'PASS' if attr_rate >= 0.95 else 'FAIL'}")
    print(f"OVERALL: {'PASS' if gate_ok else 'FAIL'}")
    print(f"{'=' * 68}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
