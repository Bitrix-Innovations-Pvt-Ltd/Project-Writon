'use client';

import { useEffect, useState } from 'react';
import {
  DocFormat,
  FONT_OPTIONS,
  PAGE_SIZES,
  PageSizeKey,
  buildDocCss,
  diffKeys,
} from '@/lib/docFormat';

interface FormatSettingsModalProps {
  open: boolean;
  /** Current effective formatting — every field opens pre-filled from this. */
  value: DocFormat;
  /**
   * What "Reset to court default" restores: the court-level (and, where the
   * rulebook specifies them, court-sourced) values with no user edits.
   */
  resetTarget: DocFormat;
  /** court_formatting_rules.source_note for the selected court, if any. */
  courtNote?: string | null;
  /** True when the court's rulebook actually specifies typography. */
  courtSourced?: boolean;
  onApply: (format: DocFormat, changedKeys: string[]) => void;
  onClose: () => void;
}

const LINE_SPACING_CHOICES = [1, 1.15, 1.5, 2];

/**
 * The formatting dialog shown when a draft is started, and reopenable from the
 * editor toolbar afterwards.
 *
 * Edits live in local state until Apply, so closing with Esc or the backdrop
 * leaves the document untouched. Apply reports which keys actually changed —
 * the wizard uses that to stop court-level defaults from later overwriting a
 * field the user set by hand.
 */
export default function FormatSettingsModal({
  open,
  value,
  resetTarget,
  courtNote,
  courtSourced,
  onApply,
  onClose,
}: FormatSettingsModalProps) {
  const [draft, setDraft] = useState<DocFormat>(value);

  // Re-seed each time the dialog opens: the court selection (and therefore the
  // margins) can have moved since it was last shown.
  useEffect(() => {
    if (open) setDraft(value);
  }, [open, value]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const set = <K extends keyof DocFormat>(key: K, val: DocFormat[K]) =>
    setDraft(d => ({ ...d, [key]: val }));

  const setMargin = (side: keyof DocFormat['margins'], val: number) =>
    setDraft(d => ({ ...d, margins: { ...d.margins, [side]: val } }));

  const numberField = (
    label: string,
    val: number,
    onChange: (n: number) => void,
    opts: { min: number; max: number; step: number; suffix: string },
  ) => (
    <label className="block">
      <span className="block text-xs font-bold text-on-surface-variant mb-1">{label}</span>
      <div className="relative">
        <input
          type="number"
          value={val}
          min={opts.min}
          max={opts.max}
          step={opts.step}
          onChange={e => {
            const n = parseFloat(e.target.value);
            if (Number.isFinite(n)) onChange(Math.min(opts.max, Math.max(opts.min, n)));
          }}
          className="w-full p-2 pr-10 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] text-on-surface-variant pointer-events-none">
          {opts.suffix}
        </span>
      </div>
    </label>
  );

  const sectionTitle = (icon: string, text: string) => (
    <h3 className="flex items-center gap-2 text-sm font-bold text-on-surface mb-3">
      <span className="material-symbols-outlined text-base text-primary">{icon}</span>
      {text}
    </h3>
  );

  const toggle = (label: string, active: boolean, onClick: () => void) => (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-colors ${
        active
          ? 'bg-primary text-white border-primary'
          : 'bg-white text-on-surface-variant border-outline-variant hover:bg-surface-container-low'
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center p-4 print:hidden">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={onClose} />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Document formatting"
        className="relative w-full max-w-4xl max-h-[90vh] flex flex-col bg-white rounded-2xl shadow-2xl border border-outline-variant animate-fade-slide-up"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-6 py-5 border-b border-outline-variant">
          <div>
            <h2 className="font-display-lg text-xl font-bold text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-primary">format_shapes</span>
              Document Formatting
            </h2>
            <p className="text-sm text-on-surface-variant mt-1">
              These settings apply to the preview, the printed PDF and the Word export.
              You can change them any time from the editor toolbar.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 text-on-surface-variant hover:text-on-surface transition-colors"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        {/* Court sourcing notice */}
        {courtNote && (
          <div className="mx-6 mt-4 rounded-lg border border-[#E4C853]/50 bg-[#E4C853]/10 px-4 py-3">
            <p className="text-[11px] font-bold tracking-wider uppercase text-[#715000] mb-1">
              {courtSourced
                ? 'Defaults from this court’s rulebook'
                : 'This court’s rulebook does not specify a filing format'}
            </p>
            <p className="text-xs text-on-surface-variant leading-relaxed">{courtNote}</p>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
          <div className="space-y-6">
            {/* Typography */}
            <section>
              {sectionTitle('text_fields', 'Typography')}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label className="block sm:col-span-1">
                  <span className="block text-xs font-bold text-on-surface-variant mb-1">Font</span>
                  <select
                    value={draft.fontFamily}
                    onChange={e => set('fontFamily', e.target.value)}
                    className="w-full p-2 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                  >
                    {FONT_OPTIONS.map(f => (
                      <option key={f.label} value={f.stack}>{f.label}</option>
                    ))}
                  </select>
                </label>
                {numberField('Body font size', draft.bodyFontSize, n => set('bodyFontSize', n),
                  { min: 8, max: 24, step: 0.5, suffix: 'pt' })}
                {numberField('Heading font size', draft.headingFontSize, n => set('headingFontSize', n),
                  { min: 8, max: 32, step: 0.5, suffix: 'pt' })}
              </div>
            </section>

            {/* Spacing */}
            <section>
              {sectionTitle('format_line_spacing', 'Spacing')}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label className="block">
                  <span className="block text-xs font-bold text-on-surface-variant mb-1">
                    Line spacing <span className="font-normal">(between lines)</span>
                  </span>
                  <select
                    value={draft.lineSpacing}
                    onChange={e => set('lineSpacing', parseFloat(e.target.value))}
                    className="w-full p-2 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                  >
                    {(LINE_SPACING_CHOICES.includes(draft.lineSpacing)
                      ? LINE_SPACING_CHOICES
                      : [...LINE_SPACING_CHOICES, draft.lineSpacing].sort((a, b) => a - b)
                    ).map(v => (
                      <option key={v} value={v}>
                        {v === 1 ? 'Single (1.0)' : v === 2 ? 'Double (2.0)' : `${v.toFixed(2).replace(/0$/, '')}`}
                      </option>
                    ))}
                  </select>
                </label>
                {numberField('Between paragraphs', draft.paragraphSpacing, n => set('paragraphSpacing', n),
                  { min: 0, max: 48, step: 1, suffix: 'pt' })}
                {numberField('First-line indent', draft.firstLineIndent, n => set('firstLineIndent', n),
                  { min: 0, max: 1.5, step: 0.05, suffix: 'in' })}
                {numberField('Above a heading', draft.headingSpaceBefore, n => set('headingSpaceBefore', n),
                  { min: 0, max: 72, step: 1, suffix: 'pt' })}
                {numberField('Below a heading', draft.headingSpaceAfter, n => set('headingSpaceAfter', n),
                  { min: 0, max: 72, step: 1, suffix: 'pt' })}
              </div>
            </section>

            {/* Headings & alignment */}
            <section>
              {sectionTitle('title', 'Headings & alignment')}
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
                <div>
                  <span className="block text-xs font-bold text-on-surface-variant mb-1">Heading alignment</span>
                  <div className="flex gap-2">
                    {toggle('Centred', draft.headingAlign === 'center', () => set('headingAlign', 'center'))}
                    {toggle('Left', draft.headingAlign === 'left', () => set('headingAlign', 'left'))}
                  </div>
                </div>
                <div>
                  <span className="block text-xs font-bold text-on-surface-variant mb-1">Heading style</span>
                  <div className="flex gap-2">
                    {toggle('UPPERCASE', draft.headingCase === 'uppercase',
                      () => set('headingCase', draft.headingCase === 'uppercase' ? 'none' : 'uppercase'))}
                    {toggle('Underline', draft.headingUnderline,
                      () => set('headingUnderline', !draft.headingUnderline))}
                  </div>
                </div>
                <div>
                  <span className="block text-xs font-bold text-on-surface-variant mb-1">Body alignment</span>
                  <div className="flex gap-2">
                    {toggle('Justified', draft.bodyAlign === 'justify', () => set('bodyAlign', 'justify'))}
                    {toggle('Left', draft.bodyAlign === 'left', () => set('bodyAlign', 'left'))}
                  </div>
                </div>
              </div>
            </section>

            {/* Page */}
            <section>
              {sectionTitle('description', 'Page & margins')}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <label className="block sm:col-span-3">
                  <span className="block text-xs font-bold text-on-surface-variant mb-1">Paper size</span>
                  <select
                    value={draft.pageSize}
                    onChange={e => set('pageSize', e.target.value as PageSizeKey)}
                    className="w-full p-2 rounded-lg border border-outline-variant focus:border-primary focus:ring-1 focus:ring-primary outline-none text-sm bg-white"
                  >
                    {(Object.keys(PAGE_SIZES) as PageSizeKey[]).map(k => (
                      <option key={k} value={k}>{PAGE_SIZES[k].label}</option>
                    ))}
                  </select>
                </label>
                {numberField('Top margin', draft.margins.top, n => setMargin('top', n),
                  { min: 0, max: 4, step: 0.1, suffix: 'in' })}
                {numberField('Bottom margin', draft.margins.bottom, n => setMargin('bottom', n),
                  { min: 0, max: 4, step: 0.1, suffix: 'in' })}
                {numberField('Right margin', draft.margins.right, n => setMargin('right', n),
                  { min: 0, max: 4, step: 0.1, suffix: 'in' })}
                {numberField('Left margin (binding edge)', draft.margins.left, n => setMargin('left', n),
                  { min: 0, max: 4, step: 0.1, suffix: 'in' })}
              </div>
            </section>
          </div>

          {/* Live preview */}
          <div className="lg:sticky lg:top-0 self-start w-full">
            <span className="block text-xs font-bold text-on-surface-variant mb-2">Preview</span>
            <div className="border border-outline-variant rounded-lg bg-white p-4 overflow-hidden">
              {/* Scoped to .wr-doc-preview so it cannot leak onto the real document. */}
              <style>{buildDocCss(draft, '.wr-doc-preview')}</style>
              <div className="wr-doc-preview origin-top-left scale-[0.72] w-[139%]">
                <h2>In the Supreme Court of India</h2>
                <p>
                  That the Petitioner is a citizen of India and is entitled to the fundamental
                  rights guaranteed under Part III of the Constitution.
                </p>
                <h3>Grounds</h3>
                <p>
                  Because the impugned order is contrary to the settled position of law and
                  suffers from non-application of mind.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-outline-variant bg-surface-container-lowest rounded-b-2xl">
          <button
            type="button"
            onClick={() => setDraft(resetTarget)}
            className="text-xs font-bold text-primary hover:text-[#004131] underline"
          >
            Reset to court default
          </button>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2.5 text-on-surface-variant hover:bg-surface-container-low rounded-lg text-sm font-bold transition-colors border border-transparent"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => onApply(draft, diffKeys(value, draft))}
              className="px-8 py-2.5 bg-primary text-white text-sm font-bold rounded-lg hover:bg-[#004131] transition-colors shadow-md"
            >
              Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
