'use client';

import { useCallback, useEffect, useState } from 'react';

/**
 * ParagraphPicker — lets the advocate choose which WHOLE paragraphs of a
 * judgment get quoted verbatim in the Grounds.
 *
 * Retrieval matches ~1,750-char chunks, and 52% of them start mid-sentence, so
 * the snippet shown on the citation card is usually a fragment. This expands
 * that fragment into the complete numbered paragraphs behind it.
 *
 * Paragraph numbers come from the judgment text itself (see
 * backend/app/core/paragraphs.py), never from a model. Where the scan lost a
 * marker the backend returns a range like "5-6" rather than guessing, and this
 * component surfaces that instead of hiding it.
 */

export interface JudgmentParagraph {
  para_number: number;
  para_number_end: number | null;
  label: string;
  number_uncertain: boolean;
  text: string;
  is_match: boolean;
  suspect_merge: boolean;
  marker_observed: boolean;
}

interface ParagraphResponse {
  judgment_id: number;
  case_title?: string;
  paragraphs: JudgmentParagraph[];
  matched_paragraphs?: number[];
  total_paragraphs?: number;
  coverage: 'full' | 'partial' | 'none';
  // 'unknown' = the judgment was matched by BM25 alone, so there is no chunk to
  // attribute a paragraph to and every paragraph is offered.
  zone?: 'body' | 'front_matter' | 'after_body' | 'unknown';
  reason?: string;
}

interface Props {
  judgmentId: number;
  chunkId?: number | null;
  chunkIndex?: number | null;
  selected: Set<number>;
  onChange: (paraNumbers: Set<number>) => void;
  apiUrl: string;
}

export default function ParagraphPicker({
  judgmentId,
  chunkId,
  chunkIndex,
  selected,
  onChange,
  apiUrl,
}: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ParagraphResponse | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (includeAll: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/api/v1/drafts/judgment-paragraphs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          judgment_id: judgmentId,
          chunk_id: chunkId ?? null,
          chunk_index: chunkIndex ?? null,
          include_all: includeAll,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError('Could not load paragraphs for this judgment.');
    } finally {
      setLoading(false);
    }
  }, [apiUrl, judgmentId, chunkId, chunkIndex]);

  // Fetch on first expand only — the endpoint costs a round trip, and Step 6
  // already spends 20-25s before this card is even visible.
  useEffect(() => {
    if (open && !data && !loading) load(false);
  }, [open, data, loading, load]);

  const toggle = (paraNumber: number, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(paraNumber);
    else next.delete(paraNumber);
    onChange(next);
  };

  const paragraphs = data?.paragraphs ?? [];
  const matchCount = paragraphs.filter(p => p.is_match).length;

  return (
    <div className="mt-3 border-t border-outline-variant/60 pt-3">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline"
      >
        <span className="material-symbols-outlined text-[16px]">
          {open ? 'expand_less' : 'expand_more'}
        </span>
        {open ? 'Hide paragraphs' : 'Choose paragraphs to quote'}
        {selected.size > 0 && (
          <span className="ml-1 rounded-full bg-primary text-on-primary px-2 py-0.5 text-[10px] font-bold">
            {selected.size} selected
          </span>
        )}
      </button>

      {open && (
        <div className="mt-3 space-y-2">
          {loading && (
            <p className="text-xs text-on-surface-variant italic">Loading paragraphs…</p>
          )}

          {error && <p className="text-xs text-error">{error}</p>}

          {!loading && !error && data?.coverage === 'none' && (
            <p className="text-xs text-on-surface-variant italic">
              {data.reason === 'no_paragraph_numbering'
                ? 'This judgment has no printed paragraph numbers, so individual paragraphs cannot be cited. The full extract above will be used.'
                : 'Paragraphs are unavailable for this judgment.'}
            </p>
          )}

          {!loading && !error && paragraphs.length > 0 && (
            <>
              {data?.zone === 'front_matter' && matchCount === 0 && (
                <p className="text-[11px] text-on-surface-variant bg-surface-container-low rounded-lg p-2">
                  The match fell in the headnote, which carries no paragraph
                  number. The opening paragraphs of the judgment are shown instead.
                </p>
              )}

              {data?.zone === 'unknown' && (
                <p className="text-[11px] text-on-surface-variant bg-surface-container-low rounded-lg p-2">
                  This judgment was matched on keywords rather than a specific
                  passage, so no single paragraph is highlighted. All{' '}
                  {data?.total_paragraphs} paragraphs are listed — pick the ones
                  you want quoted.
                </p>
              )}

              {paragraphs.map(para => {
                const isSelected = selected.has(para.para_number);
                return (
                  <label
                    key={para.para_number}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                      isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-outline-variant/60 hover:border-primary/30'
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 w-4 h-4 text-primary rounded border-outline focus:ring-primary"
                      checked={isSelected}
                      onChange={e => toggle(para.para_number, e.target.checked)}
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <span className="text-[11px] font-bold font-mono px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface">
                          Para {para.label}
                        </span>
                        {para.is_match && (
                          <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-green-100 text-green-800">
                            Matched
                          </span>
                        )}
                        {para.number_uncertain && (
                          <span
                            className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-amber-100 text-amber-800"
                            title="The scan lost a paragraph marker, so this block covers more than one paragraph. Verify the numbering against the reported judgment before filing."
                          >
                            Spans {para.label}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-on-surface-variant whitespace-pre-wrap">
                        {para.text}
                      </p>
                    </div>
                  </label>
                );
              })}

              {!showAll && (data?.total_paragraphs ?? 0) > paragraphs.length && (
                <button
                  type="button"
                  onClick={() => { setShowAll(true); load(true); }}
                  className="text-xs font-semibold text-primary hover:underline"
                >
                  Show all {data?.total_paragraphs} paragraphs of this judgment
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
