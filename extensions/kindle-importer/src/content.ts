import { extractLibrary, extractCurrentBookHighlights } from './lib/kindle-extract';
import { validateExportEnvelope } from './lib/schema-validate';
import { SELECTORS } from './lib/selectors';

const POLL_INTERVAL_MS = 200;
const POLL_MAX_TRIES = 50;
const PER_BOOK_TIMEOUT_MS = 5000;

async function waitForLibrary(): Promise<string | null> {
  for (let i = 0; i < POLL_MAX_TRIES; i++) {
    for (const sel of SELECTORS.library_container) {
      if (document.querySelector(sel)) return sel;
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  return null;
}

async function clickAndWaitForHighlights(asin: string): Promise<'has-rows' | 'empty'> {
  const row = document.querySelector<HTMLElement>(
    `[data-asin="${asin}"], [id="${asin}"]`
  );
  if (!row) throw new Error(`book row not found for asin=${asin}`);
  row.click();

  const start = Date.now();
  while (Date.now() - start < PER_BOOK_TIMEOUT_MS) {
    for (const sel of SELECTORS.annotation_container) {
      const c = document.querySelector(sel);
      if (c && c.querySelectorAll(SELECTORS.annotation_row).length > 0) {
        return 'has-rows';
      }
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  // Timed out waiting for any annotation rows. Could be a book with zero
  // highlights, or a slow-loading panel — caller decides.
  return 'empty';
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
