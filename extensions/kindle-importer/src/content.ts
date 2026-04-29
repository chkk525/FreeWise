import { extractLibrary, extractCurrentBookHighlights } from './lib/kindle-extract';
import { validateExportEnvelope } from './lib/schema-validate';
import { SELECTORS } from './lib/selectors';

const POLL_INTERVAL_MS = 200;
const POLL_MAX_TRIES = 50;
const PER_BOOK_TIMEOUT_MS = 5000;

async function waitForLibrary(): Promise<boolean> {
  for (let i = 0; i < POLL_MAX_TRIES; i++) {
    for (const sel of SELECTORS.library_container) {
      if (document.querySelector(sel)) return true;
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  return false;
}

async function clickAndWaitForHighlights(asin: string): Promise<void> {
  const row = document.querySelector<HTMLElement>(
    `[data-asin="${asin}"], [id="${asin}"]`
  );
  if (!row) throw new Error(`book row not found for asin=${asin}`);
  row.click();

  const start = Date.now();
  while (Date.now() - start < PER_BOOK_TIMEOUT_MS) {
    for (const sel of SELECTORS.annotation_container) {
      const c = document.querySelector(sel);
      if (c && c.querySelectorAll(SELECTORS.annotation_row).length > 0) return;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  // No highlights for this book — valid empty state, not an error.
}

async function scrapeAll(port: chrome.runtime.Port): Promise<void> {
  if ((document as unknown as { prerendering?: boolean }).prerendering) {
    port.postMessage({ type: 'aborted', reason: 'prerendering' });
    return;
  }

  const libraryReady = await waitForLibrary();
  if (!libraryReady) {
    port.postMessage({ type: 'error', reason: 'library not found within 10s' });
    return;
  }

  const books = extractLibrary(document);
  port.postMessage({ type: 'progress', current: 0, total: books.length });

  for (let i = 0; i < books.length; i++) {
    const book = books[i];
    try {
      await clickAndWaitForHighlights(book.asin);
      book.highlights = extractCurrentBookHighlights(document);
    } catch (err) {
      port.postMessage({
        type: 'book_error',
        book_title: book.title,
        reason: String(err),
      });
    }
    port.postMessage({ type: 'progress', current: i + 1, total: books.length });
  }

  const envelope = {
    schema_version: '1.0',
    exported_at: new Date().toISOString(),
    source: 'kindle_notebook',
    books,
  };

  const validation = validateExportEnvelope(envelope);
  if (!validation.ok) {
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
