import { SELECTORS } from './selectors';

export type KindleHighlight = {
  id: string;
  text: string;
  note: string | null;
  color: 'yellow' | 'blue' | 'pink' | 'orange' | null;
  location: number | null;
  page: number | null;
  created_at: null;
};

export type KindleBook = {
  asin: string;
  title: string;
  author: string | null;
  cover_url: string | null;
  highlights: KindleHighlight[];
};

const COLORS = ['yellow', 'blue', 'pink', 'orange'] as const;
type Color = (typeof COLORS)[number];

function querySelectorAny(
  root: ParentNode,
  selectors: readonly string[],
): Element | null {
  for (const s of selectors) {
    const found = root.querySelector(s);
    if (found) return found;
  }
  return null;
}

function parseFirstNumber(text: string): number | null {
  const match = text.match(/(\d[\d,]*)/);
  if (!match) return null;
  const n = parseInt(match[1].replace(/,/g, ''), 10);
  return Number.isFinite(n) ? n : null;
}

function colorFromClass(el: Element): Color | null {
  const prefix = SELECTORS.highlight_color_prefix;
  for (const cls of Array.from(el.classList)) {
    if (cls.startsWith(prefix)) {
      const color = cls.slice(prefix.length);
      if ((COLORS as readonly string[]).includes(color)) return color as Color;
    }
  }
  return null;
}

function colorFromHeaderText(headerText: string): Color | null {
  const lower = headerText.toLowerCase();
  for (const c of COLORS) {
    if (lower.includes(`${c} highlight`)) return c;
  }
  return null;
}

function extractColor(row: Element, headerText: string): Color | null {
  // The color class lives on the inner `.kp-notebook-highlight` div, not
  // on `span#highlight`. Fall back to the header label ("Yellow highlight
  // | Location: 747") if the class is missing.
  const highlightDiv = row.querySelector(SELECTORS.highlight_container);
  if (highlightDiv) {
    const fromClass = colorFromClass(highlightDiv);
    if (fromClass) return fromClass;
  }
  return colorFromHeaderText(headerText);
}

function readLocationField(el: Element): string {
  // The location is rendered as `<input type="hidden" value="747">` in the
  // current Amazon DOM but used to be `<span>Location 747</span>`. Read both.
  const input = el as HTMLInputElement;
  if (typeof input.value === 'string' && input.value.length > 0) return input.value;
  return el.textContent ?? '';
}

function extractLocationAndPage(
  row: Element,
  headerText: string,
): { location: number | null; page: number | null } {
  const lowerHeader = headerText.toLowerCase();
  let location: number | null = null;
  let page: number | null = null;

  // Prefer the header text — it labels which one the row uses.
  if (lowerHeader.includes('location')) {
    location = parseFirstNumber(lowerHeader);
  } else if (lowerHeader.includes('page')) {
    page = parseFirstNumber(lowerHeader);
  }

  // Fallback to the location field. It's a bare number with no label, so
  // we only use it if the header didn't tell us which kind it is.
  if (location === null && page === null) {
    const locEl = row.querySelector(SELECTORS.location_text);
    if (locEl) {
      const raw = readLocationField(locEl);
      location = parseFirstNumber(raw);
    }
  }

  return { location, page };
}

function extractNote(row: Element): string | null {
  const noteEl = row.querySelector(SELECTORS.note_text);
  if (!noteEl) return null;
  // Amazon renders an empty placeholder note container with `aok-hidden`
  // for highlights without a note — treat that as "no note".
  const container = noteEl.closest(SELECTORS.note_container);
  if (container && container.classList.contains('aok-hidden')) return null;
  const text = (noteEl.textContent ?? '').trim();
  return text === '' ? null : text;
}

export function extractCurrentBookHighlights(doc: Document): KindleHighlight[] {
  const container = querySelectorAny(doc, SELECTORS.annotation_container);
  if (!container) return [];

  const rows = container.querySelectorAll(SELECTORS.annotation_row);
  const out: KindleHighlight[] = [];

  for (const row of Array.from(rows)) {
    const id = row.id || row.getAttribute('data-id');
    const textEl = row.querySelector(SELECTORS.highlight_text);
    if (!id || !textEl) continue;

    const headerEl = row.querySelector(SELECTORS.header_text);
    const headerText = headerEl?.textContent ?? '';

    const { location, page } = extractLocationAndPage(row, headerText);

    out.push({
      id,
      text: (textEl.textContent ?? '').trim(),
      note: extractNote(row),
      color: extractColor(row, headerText),
      location,
      page,
      created_at: null,
    });
  }
  return out;
}

export function extractLibrary(doc: Document): KindleBook[] {
  const container = querySelectorAny(doc, SELECTORS.library_container);
  if (!container) return [];

  const rows = container.querySelectorAll(SELECTORS.library_row);
  const out: KindleBook[] = [];

  for (const row of Array.from(rows)) {
    const asin = row.getAttribute('data-asin') ?? row.id;
    if (!asin) continue;
    const titleEl = row.querySelector(SELECTORS.book_title);
    const authorEl = row.querySelector(SELECTORS.book_author);
    const coverEl = row.querySelector(
      SELECTORS.book_cover_image,
    ) as HTMLImageElement | null;
    out.push({
      asin,
      title: (titleEl?.textContent ?? '').trim(),
      author: authorEl ? (authorEl.textContent ?? '').trim() : null,
      cover_url: coverEl?.src ?? null,
      highlights: [],
    });
  }
  return out;
}
