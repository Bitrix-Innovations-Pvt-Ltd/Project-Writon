/**
 * lib/docFormat.ts — the single source of truth for how a generated draft is
 * typeset.
 *
 * Before this module the same values lived, hardcoded and duplicated, in five
 * places inside the draft wizard: the Word export header, the print `@page`
 * block, the on-screen page box, the ReactMarkdown component styles and the
 * contentEditable container. Changing a font meant editing all five and hoping
 * they stayed in agreement.
 *
 * Everything now derives from one `DocFormat` object:
 *   - `buildDocCss`      — the typography rules (screen, print and Word)
 *   - `buildPageBoxStyle`— the on-screen paper rectangle
 *   - `buildPrintPageCss`/`buildWordPageCss` — the `@page` declarations
 *
 * The rules are emitted as a scoped stylesheet rather than inline styles on
 * purpose. "Edit Text" snapshots the rendered page's innerHTML (see htmlPages
 * in the wizard), so inline styles get baked into the saved HTML and a later
 * formatting change would silently not reach the edited pages. A stylesheet
 * keeps applying to that snapshot.
 */

import type { CSSProperties } from 'react';

export type FontOption = { label: string; stack: string };

/** Serif faces first — a filed paper book is set in Times unless told otherwise. */
export const FONT_OPTIONS: FontOption[] = [
  { label: 'Times New Roman', stack: '"Times New Roman", Times, serif' },
  { label: 'Cambria',         stack: 'Cambria, Georgia, serif' },
  { label: 'Georgia',         stack: 'Georgia, "Times New Roman", serif' },
  { label: 'Arial',           stack: 'Arial, Helvetica, sans-serif' },
  { label: 'Calibri',         stack: 'Calibri, Candara, sans-serif' },
  { label: 'Verdana',         stack: 'Verdana, Geneva, sans-serif' },
  { label: 'Courier New',     stack: '"Courier New", Courier, monospace' },
];

export type PageSizeKey = 'legal' | 'a4' | 'letter';

/** Page dimensions in inches. Legal is the existing default (8.5in x 14in). */
export const PAGE_SIZES: Record<PageSizeKey, { label: string; width: number; height: number }> = {
  legal:  { label: 'Legal (8.5" × 14")',  width: 8.5,  height: 14 },
  a4:     { label: 'A4 (8.27" × 11.69")', width: 8.27, height: 11.69 },
  letter: { label: 'Letter (8.5" × 11")', width: 8.5,  height: 11 },
};

export type Margins = { top: number; right: number; bottom: number; left: number };

export type DocFormat = {
  fontFamily: string;          // CSS stack, one of FONT_OPTIONS[].stack
  bodyFontSize: number;        // pt
  headingFontSize: number;     // pt
  lineSpacing: number;         // multiplier — spacing between lines of content
  paragraphSpacing: number;    // pt — spacing between paragraphs
  headingSpaceBefore: number;  // pt — between a heading and the content above it
  headingSpaceAfter: number;   // pt — between a heading and its own content
  headingAlign: 'center' | 'left';
  headingCase: 'uppercase' | 'none';
  headingUnderline: boolean;
  bodyAlign: 'justify' | 'left';
  firstLineIndent: number;     // inches
  pageSize: PageSizeKey;
  margins: Margins;            // inches
};

/**
 * Reproduces exactly what the wizard rendered before this feature existed, so
 * a user who opens the dialog and clicks Apply gets a byte-identical document.
 *
 * The pt values are the old rem values converted at the browser's 16px root:
 * 1rem = 16px = 12pt (paragraph spacing), 1.5rem = 24px = 18pt (heading space
 * before). The left margin matches the Supreme Court default, which is the
 * court level the wizard starts on; `courtLevelMargins` keeps it in step when
 * the user picks a different level.
 */
export const DEFAULT_DOC_FORMAT: DocFormat = {
  fontFamily: FONT_OPTIONS[0].stack,
  bodyFontSize: 14,
  headingFontSize: 14,
  lineSpacing: 1.5,
  paragraphSpacing: 12,
  headingSpaceBefore: 18,
  headingSpaceAfter: 12,
  headingAlign: 'center',
  headingCase: 'uppercase',
  headingUnderline: false,
  bodyAlign: 'justify',
  firstLineIndent: 0,
  pageSize: 'legal',
  margins: { top: 1, right: 1, bottom: 0.5, left: 2 },
};

/**
 * The gutter a filed petition needs on the binding edge: the Supreme Court
 * paper book is stitched at 2in, a High Court at 1.5in, everything else at 1in.
 */
export function courtLevelMargins(courtLevel: string): Partial<Margins> {
  return { left: courtLevel === 'supreme' ? 2 : courtLevel === 'high' ? 1.5 : 1 };
}

/**
 * Per-heading-level multipliers applied to headingSpaceBefore/After. Keeps the
 * visual hierarchy the old inline styles had (h3 and h4 sat tighter than h1/h2)
 * while leaving the user one pair of numbers to reason about.
 */
const HEADING_SCALE: Record<string, { before: number; after: number }> = {
  h1: { before: 1,    after: 1 },
  h2: { before: 1,    after: 1 },
  h3: { before: 0.8,  after: 0.6 },
  h4: { before: 0.67, after: 0.5 },
  h5: { before: 0.67, after: 0.5 },
  h6: { before: 0.67, after: 0.5 },
};

/** Trims trailing zeros so the emitted CSS reads like handwritten CSS. */
const pt = (v: number) => `${Math.round(v * 100) / 100}pt`;

/** A CSS declaration block, as property → value. */
type Decls = Record<string, string>;

/**
 * The formatting rules, as data.
 *
 * Everything that renders a draft — the app's stylesheet, the print stylesheet
 * and the inline styles written into the Word export — is derived from this one
 * function, so the three can never drift apart.
 *
 * Units are deliberately absolute (pt/in, never rem): the Word export applies
 * these declarations outside any browser, where a root font size does not exist.
 */
function docRules(fmt: DocFormat): { root: Decls; tags: Record<string, Decls> } {
  const root: Decls = {
    'font-family': fmt.fontFamily,
    'font-size': pt(fmt.bodyFontSize),
    'line-height': String(fmt.lineSpacing),
  };

  // Every block declares font-family and font-size rather than inheriting them.
  // Word's importer re-asserts its own Normal style (Calibri 11pt) on any
  // paragraph that does not say otherwise, so inheritance alone is not enough
  // to make a downloaded draft match what was approved on screen.
  const tags: Record<string, Decls> = {
    p: {
      ...root,
      margin: `0 0 ${pt(fmt.paragraphSpacing)} 0`,
      'text-align': fmt.bodyAlign,
      'text-justify': 'inter-word',
      'text-indent': `${fmt.firstLineIndent}in`,
    },
    ul: {
      ...root,
      margin: `${pt(fmt.paragraphSpacing * 0.5)} 0 ${pt(fmt.paragraphSpacing * 0.5)} 18pt`,
    },
    li: {
      ...root,
      margin: `${pt(fmt.paragraphSpacing * 0.3)} 0`,
      'text-align': fmt.bodyAlign,
    },
    // Tables (the Dates & Events chart) previously got their grid purely from
    // Tailwind classes, which mean nothing once the HTML is outside the app —
    // the exported .doc lost every rule line. The values below restate those
    // classes exactly (outline-variant #bec9c2, px-4/py-2, my-6), so the screen
    // is unchanged and the download finally keeps its borders.
    table: {
      ...root,
      width: '100%',
      'border-collapse': 'collapse',
      border: '1px solid #bec9c2',
      'text-align': 'left',
      margin: '18pt 0',
    },
    th: {
      ...root,
      border: '1px solid #bec9c2',
      padding: '6pt 12pt',
      'background-color': '#f2f3ff',
      'font-weight': 'bold',
    },
    td: {
      ...root,
      border: '1px solid #bec9c2',
      padding: '6pt 12pt',
    },
  };
  tags.ol = tags.ul;

  Object.keys(HEADING_SCALE).forEach(tag => {
    const s = HEADING_SCALE[tag];
    tags[tag] = {
      'font-family': fmt.fontFamily,
      'font-size': pt(fmt.headingFontSize),
      'font-weight': 'bold',
      'text-align': fmt.headingAlign,
      'text-transform': fmt.headingCase === 'uppercase' ? 'uppercase' : 'none',
      'text-decoration': fmt.headingUnderline ? 'underline' : 'none',
      'line-height': String(fmt.lineSpacing),
      margin: `${pt(fmt.headingSpaceBefore * s.before)} 0 ${pt(fmt.headingSpaceAfter * s.after)} 0`,
    };
  });

  return { root, tags };
}

const declsToText = (d: Decls) =>
  Object.entries(d).map(([k, v]) => `${k}: ${v}`).join('; ') + ';';

const declsToBlock = (d: Decls) =>
  Object.entries(d).map(([k, v]) => `  ${k}: ${v};`).join('\n');

/**
 * The typography stylesheet.
 *
 * `scope` is a selector prefix — `.wr-doc` in the app. Pass an empty string for
 * the Word export: Word's HTML importer is unreliable with descendant
 * combinators, so there the rules are emitted as bare element selectors
 * (`p { … }`) with `body` carrying the inherited defaults.
 */
export function buildDocCss(fmt: DocFormat, scope: string): string {
  const { root, tags } = docRules(fmt);
  const sel = (tag: string) => (scope ? `${scope} ${tag}` : tag);

  const blocks = [`${scope || 'body'} {\n${declsToBlock(root)}\n}`];
  // ul and ol share one object; emit them as one rule rather than twice.
  const emitted = new Set<Decls>();
  Object.keys(tags).forEach(tag => {
    const decls = tags[tag];
    if (emitted.has(decls)) return;
    emitted.add(decls);
    const selector = Object.keys(tags)
      .filter(t => tags[t] === decls)
      .map(sel)
      .join(', ');
    blocks.push(`${selector} {\n${declsToBlock(decls)}\n}`);
  });

  return blocks.join('\n');
}

/**
 * Writes the formatting into the HTML itself, as `style` attributes.
 *
 * The Word export needs this. A `.doc` built from HTML is opened by Word's own
 * importer, which honours inline styles far more dependably than a `<style>`
 * block — without this, a downloaded draft could come back in Word's defaults
 * (Calibri 11pt, single-spaced) no matter what the user chose.
 *
 * Any style already on an element is appended *after* the generated ones so it
 * still wins: that is what preserves the bold/italic/centre-alignment the user
 * applied with the editor toolbar, which lives in inline styles of its own.
 */
export function inlineDocStyles(html: string, fmt: DocFormat): string {
  if (typeof DOMParser === 'undefined') return html;   // SSR — nothing to do
  const { tags } = docRules(fmt);
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');

  Object.keys(tags).forEach(tag => {
    const base = declsToText(tags[tag]);
    doc.body.querySelectorAll(tag).forEach(el => {
      const existing = el.getAttribute('style');
      el.setAttribute('style', existing ? `${base} ${existing}` : base);
    });
  });

  return doc.body.innerHTML;
}

/** The inherited defaults, for the wrapper element of an export. */
export function rootInlineStyle(fmt: DocFormat): string {
  return declsToText(docRules(fmt).root);
}

/** The paper rectangle drawn on screen. 96 CSS px to the inch. */
export function buildPageBoxStyle(fmt: DocFormat): CSSProperties {
  const page = PAGE_SIZES[fmt.pageSize];
  return {
    width: `${page.width * 96}px`,
    maxWidth: '100%',
    minHeight: `${page.height * 96}px`,
    paddingTop: `${fmt.margins.top}in`,
    paddingRight: `${fmt.margins.right}in`,
    paddingBottom: `${fmt.margins.bottom}in`,
    paddingLeft: `${fmt.margins.left}in`,
  };
}

/** `@page` for browser printing / print-to-PDF. */
export function buildPrintPageCss(fmt: DocFormat): string {
  const page = PAGE_SIZES[fmt.pageSize];
  return `@page {
  size: ${page.width}in ${page.height}in;
  margin-top: ${fmt.margins.top}in;
  margin-right: ${fmt.margins.right}in;
  margin-bottom: ${fmt.margins.bottom}in;
  margin-left: ${fmt.margins.left}in;
}`;
}

/** `@page` for the Word (.doc) export, which needs a named section. */
export function buildWordPageCss(fmt: DocFormat): string {
  const page = PAGE_SIZES[fmt.pageSize];
  return `@page WordSection1 { size: ${page.width}in ${page.height}in; margin: ${fmt.margins.top}in ${fmt.margins.right}in ${fmt.margins.bottom}in ${fmt.margins.left}in; }
div.WordSection1 { page: WordSection1; }`;
}

// ---------------------------------------------------------------------------
// Court-sourced defaults
// ---------------------------------------------------------------------------

/**
 * Maps one row of GET /court-identities/{code}/formatting onto a partial
 * DocFormat. Only non-null fields are returned: the rulebooks are paper-era and
 * mostly leave font/size/spacing unspecified, and an unsourced NULL must not
 * overwrite a sensible default.
 */
export function fromCourtFormatting(row: any): Partial<DocFormat> {
  const out: Partial<DocFormat> = {};
  if (!row) return out;

  if (row.font_family) {
    const match = FONT_OPTIONS.find(
      f => f.label.toLowerCase() === String(row.font_family).trim().toLowerCase()
    );
    if (match) out.fontFamily = match.stack;
  }

  const size = parseFloat(String(row.body_font_size ?? ''));
  if (Number.isFinite(size) && size > 0) out.bodyFontSize = size;

  const spacing = parseLineSpacing(row.line_spacing);
  if (spacing) out.lineSpacing = spacing;

  const margins: Partial<Margins> = {};
  const num = (v: any) => {
    const n = parseFloat(String(v ?? ''));
    return Number.isFinite(n) ? n : undefined;
  };
  const [t, r, b, l] = [
    num(row.margin_top_inches), num(row.margin_right_inches),
    num(row.margin_bottom_inches), num(row.margin_left_inches),
  ];
  if (t !== undefined) margins.top = t;
  if (r !== undefined) margins.right = r;
  if (b !== undefined) margins.bottom = b;
  if (l !== undefined) margins.left = l;
  if (Object.keys(margins).length) {
    out.margins = { ...DEFAULT_DOC_FORMAT.margins, ...margins };
  }

  return out;
}

/** Accepts "1.5", "double", "one and a half" and the like. */
function parseLineSpacing(value: any): number | null {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim().toLowerCase();
  const n = parseFloat(raw);
  if (Number.isFinite(n) && n >= 1 && n <= 3) return n;
  if (raw.includes('double')) return 2;
  if (raw.includes('one and a half') || raw.includes('1 1/2')) return 1.5;
  if (raw.includes('single')) return 1;
  return null;
}

/**
 * Merges court-sourced (or court-level) values into the fields the user has not
 * edited. Picking a High Court after setting custom margins must not undo them.
 */
export function applyUntouched(
  current: DocFormat,
  incoming: Partial<DocFormat>,
  touched: Set<string>,
): DocFormat {
  const next = { ...current };
  (Object.keys(incoming) as (keyof DocFormat)[]).forEach(key => {
    if (touched.has(key)) return;
    const value = incoming[key];
    if (value === undefined) return;
    (next as any)[key] = value;
  });
  return next;
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'writon:doc_format:v1';

export type StoredFormat = { format: DocFormat; touched: string[] };

/**
 * Last-used formatting, so the dialog opens on the user's own numbers rather
 * than the factory ones. Everything restored counts as touched — a saved
 * preference outranks a court-level default.
 */
export function loadSavedFormat(): StoredFormat | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.format !== 'object') return null;
    return {
      // Spread over the defaults so a format saved by an older build, missing
      // keys added since, still yields a complete object.
      format: { ...DEFAULT_DOC_FORMAT, ...parsed.format,
                margins: { ...DEFAULT_DOC_FORMAT.margins, ...(parsed.format.margins || {}) } },
      touched: Array.isArray(parsed.touched) ? parsed.touched : [],
    };
  } catch {
    return null;
  }
}

export function saveFormat(format: DocFormat, touched: Set<string>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ format, touched: Array.from(touched) } as StoredFormat),
    );
  } catch {
    // Private-browsing quota errors are not worth failing a draft over.
  }
}

/** Keys of `next` whose value differs from `base` — what the user just changed. */
export function diffKeys(base: DocFormat, next: DocFormat): string[] {
  return (Object.keys(next) as (keyof DocFormat)[]).filter(
    key => JSON.stringify(base[key]) !== JSON.stringify(next[key]),
  );
}
