import { extractLibrary, extractCurrentBookHighlights } from './lib/kindle-extract';
import { validateExportEnvelope } from './lib/schema-validate';
import { SELECTORS } from './lib/selectors';

const POLL_INTERVAL_MS = 200;
const POLL_MAX_TRIES = 50;
const PER_BOOK_TIMEOUT_MS = 8000;
const LIBRARY_SCROLL_TIMEOUT_MS = 15000;
const LIBRARY_SCROLL_STABLE_MS = 1500;

async function waitForLibrary(): Promise<string | null> {
  for (let i = 0; i < POLL_MAX_TRIES; i++) {
    for (const sel of SELECTORS.library_container) {
      if (document.querySelector(sel)) return sel;
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  return null;
}

// Amazon's notebook lazy-loads library rows via IntersectionObserver. The
// initial DOM only contains the books visible in the viewport (often just
// 3-4). To capture the full library we scroll the container to its bottom
// repeatedly until the row count stops growing for `LIBRARY_SCROLL_STABLE_MS`.
async function loadAllLibraryRows(containerSel: string): Promise<number> {
  const start = Date.now();
  let lastCount = 0;
  let lastChange = Date.now();
  while (Date.now() - start < LIBRARY_SCROLL_TIMEOUT_MS) {
    const container = document.querySelector(containerSel);
    if (!container) break;
    const count = container.querySelectorAll(SELECTORS.library_row).length;
    if (count !== lastCount) {
      console.info(`[FreeWise] library row count: ${lastCount} → ${count}`);
      lastCount = count;
      lastChange = Date.now();
    }
    if (Date.now() - lastChange >= LIBRARY_SCROLL_STABLE_MS && count > 0) {
      return count;
    }
    // Scroll the container itself if scrollable, plus the window — Amazon
    // sometimes triggers the observer off either.
    const target = lastVisibleRow(container);
    if (target) {
      target.scrollIntoView({ behavior: 'instant', block: 'end' });
    }
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise((r) => setTimeout(r, 350));
  }
  return lastCount;
}

function lastVisibleRow(container: Element): HTMLElement | null {
  const rows = container.querySelectorAll<HTMLElement>(SELECTORS.library_row);
  return rows.length === 0 ? null : rows[rows.length - 1];
}

// Try increasingly aggressive ways to "select" a book row. Amazon mounts
// click handlers on child anchors; clicking the outer div is a no-op.
async function activateBookRow(asin: string, row: HTMLElement): Promise<string> {
  // Bring it into the viewport — IntersectionObserver gates click handling.
  row.scrollIntoView({ behavior: 'instant', block: 'center' });
  await new Promise((r) => setTimeout(r, 100));

  const anchor = row.querySelector<HTMLElement>('a[href]');
  if (anchor) {
    // Clicking the anchor would normally navigate; intercept with
    // preventDefault on the next click event so we stay on the page but
    // still trigger Amazon's React handler that loads the highlights.
    anchor.addEventListener(
      'click',
      (e) => {
        e.preventDefault();
      },
      { once: true, capture: true },
    );
    anchor.click();
    return `anchor[href=${(anchor as HTMLAnchorElement).getAttribute('href')}]`;
  }
  // Fallback: dispatch a synthetic mouse sequence on the row itself, in
  // case the handler is on the row or a non-anchor child.
  for (const type of ['mousedown', 'mouseup', 'click'] as const) {
    row.dispatchEvent(
      new MouseEvent(type, { bubbles: true, cancelable: true, view: window }),
    );
  }
  return `synthetic-mouseevents on ${row.tagName.toLowerCase()}.${asin}`;
}

async function clickAndWaitForHighlights(asin: string): Promise<{
  status: 'has-rows' | 'empty';
  via: string;
}> {
  const row = document.querySelector<HTMLElement>(
    `[data-asin="${asin}"], [id="${asin}"]`
  );
  if (!row) throw new Error(`book row not found for asin=${asin}`);
  const via = await activateBookRow(asin, row);

  // Capture rows-before-click so we can tell when the panel actually
  // re-rendered for THIS book vs. just inheriting stale rows from a
  // previous click. Match by the first row's id (which is the highlight
  // id; differs per book).
  const containerSel = SELECTORS.annotation_container[0];
  const before =
    document.querySelector(containerSel)?.querySelector(SELECTORS.annotation_row)?.id ?? '';

  const start = Date.now();
  while (Date.now() - start < PER_BOOK_TIMEOUT_MS) {
    for (const sel of SELECTORS.annotation_container) {
      const c = document.querySelector(sel);
      if (!c) continue;
      const firstRow = c.querySelector(SELECTORS.annotation_row);
      if (firstRow && firstRow.id !== before) {
        return { status: 'has-rows', via };
      }
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  // Either zero highlights or the click never landed.
  return { status: 'empty', via };
}

async function scrapeAll(port: chrome.runtime.Port): Promise<void> {
  if ((document as unknown as { prerendering?: boolean }).prerendering) {
    console.info('[FreeWise] aborting: page is prerendering');
    port.postMessage({ type: 'aborted', reason: 'prerendering' });
    return;
  }

  console.info('[FreeWise] scrape starting at', location.href);
  const libraryHit = await waitForLibrary();
  if (!libraryHit) {
    console.warn(
      '[FreeWise] library container not found. Tried selectors:',
      SELECTORS.library_container,
    );
    port.postMessage({ type: 'error', reason: 'library not found within 10s' });
    return;
  }
  console.info(`[FreeWise] library container found via selector: ${libraryHit}`);

  const books = extractLibrary(document);
  console.info(
    `[FreeWise] extracted ${books.length} books from library:`,
    books.map((b) => ({ asin: b.asin, title: b.title })),
  );
  if (books.length === 0) {
    const container = document.querySelector(libraryHit);
    console.warn(
      '[FreeWise] library container had 0 matching rows. Selector used:',
      SELECTORS.library_row,
      'Container HTML preview:',
      container?.outerHTML?.slice(0, 500),
    );
  }
  port.postMessage({ type: 'progress', current: 0, total: books.length });

  let totalHighlights = 0;
  let booksWithZero = 0;
  for (let i = 0; i < books.length; i++) {
    const book = books[i];
    try {
      const status = await clickAndWaitForHighlights(book.asin);
      book.highlights = extractCurrentBookHighlights(document);
      if (book.highlights.length === 0) booksWithZero++;
      totalHighlights += book.highlights.length;
      console.info(
        `[FreeWise] [${i + 1}/${books.length}] "${book.title}" (${book.asin}) — ` +
          `panel ${status}, extracted ${book.highlights.length} highlights`,
      );
    } catch (err) {
      console.warn(`[FreeWise] book "${book.title}" (${book.asin}) failed:`, err);
      port.postMessage({
        type: 'book_error',
        book_title: book.title,
        reason: String(err),
      });
    }
    port.postMessage({ type: 'progress', current: i + 1, total: books.length });
  }

  console.info(
    `[FreeWise] scrape complete: ${books.length} books, ${totalHighlights} highlights total ` +
      `(${booksWithZero} books had 0 highlights)`,
  );

  const envelope = {
    schema_version: '1.0',
    exported_at: new Date().toISOString(),
    source: 'kindle_notebook',
    books,
  };

  const validation = validateExportEnvelope(envelope);
  if (!validation.ok) {
    console.warn('[FreeWise] schema validation failed:', validation.errors);
    port.postMessage({
      type: 'error',
      reason: 'schema validation failed: ' + JSON.stringify(validation.errors),
    });
    return;
  }

  port.postMessage({ type: 'done', payload: envelope });
}

const port = chrome.runtime.connect({ name: 'kindle-sync' });

port.onMessage.addListener((msg) => {
  if (msg?.type === 'start') {
    scrapeAll(port).catch((err) => {
      port.postMessage({ type: 'error', reason: String(err) });
    });
  }
});
