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

function querySelectorAny(root: ParentNode, selectors: readonly string[]): Element | null {
  for (const s of selectors) {
    const found = root.querySelector(s);
    if (found) return found;
  }
  return null;
}

function parseLocation(text: string): number | null {
  const match = text.match(/(\d[\d,]*)/);
  if (!match) return null;
  return parseInt(match[1].replace(/,/g, ''), 10);
}

function colorFromClass(el: Element): KindleHighlight['color'] {
  const prefix = SELECTORS.highlight_color_prefix;
  for (const cls of Array.from(el.classList)) {
    if (cls.startsWith(prefix)) {
      const color = cls.slice(prefix.length);
      if (color === 'yellow' || color === 'blue' || color === 'pink' || color === 'orange') {
        return color;
      }
    }
  }
  return null;
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

    const noteEl = row.querySelector(SELECTORS.note_text);
    const locEl = row.querySelector(SELECTORS.location_text);
    const locText = (locEl?.textContent ?? '').toLowerCase();

    out.push({
      id,
      text: (textEl.textContent ?? '').trim(),
      note: noteEl ? (noteEl.textContent ?? '').trim() : null,
      color: colorFromClass(textEl),
      location: locText.includes('location') ? parseLocation(locText) : null,
      page: locText.includes('page') ? parseLocation(locText) : null,
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
    const coverEl = row.querySelector(SELECTORS.book_cover_image) as HTMLImageElement | null;
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
