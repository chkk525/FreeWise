import { loadSettings } from './lib/storage';

const NOTEBOOK_URL = 'https://read.amazon.com/kp/notebook';
const TAB_LOAD_TIMEOUT_MS = 60_000;

// -1 is a "claim" sentinel held while chrome.tabs.create is awaiting; once
// the tab id is known it gets replaced by the real id. Without the sentinel,
// two `sync_now` messages racing each other both pass the null check before
// either await resolves and we end up with two background tabs.
const SYNC_PENDING = -1;

let currentSyncTab: number | null = null;
let currentPort: chrome.runtime.Port | null = null;
let tabUpdateHandler: Parameters<typeof chrome.tabs.onUpdated.addListener>[0] | null = null;
let collectedErrors: { book_title: string; reason: string }[] = [];

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === 'sync_now') {
    void startSync();
  }
});

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'kindle-sync') return;
  // Handshake gate: the content script connects on every page load, but we
  // only want to drive a scrape if `startSync` opened the tab. Otherwise a
  // user who happens to have read.amazon.com/kp/notebook open in a
  // different tab would trigger an unrequested scrape.
  if (currentSyncTab === null || currentSyncTab === SYNC_PENDING) {
    port.disconnect();
    return;
  }
  if (port.sender?.tab?.id !== currentSyncTab) {
    port.disconnect();
    return;
  }
  currentPort = port;

  port.onMessage.addListener((msg) => {
    if (msg?.type === 'progress') {
      void chrome.runtime.sendMessage({
        type: 'progress',
        current: msg.current,
        total: msg.total,
      });
    } else if (msg?.type === 'book_error') {
      collectedErrors.push({ book_title: msg.book_title, reason: msg.reason });
    } else if (msg?.type === 'done') {
      void onScrapeComplete(msg.payload).catch((e) => {
        void broadcastTerminal({ type: 'error', reason: String(e) });
        cleanup();
      });
    } else if (msg?.type === 'error') {
      void broadcastTerminal({ type: 'error', reason: msg.reason });
      cleanup();
    } else if (msg?.type === 'aborted') {
      cleanup();
    }
  });

  port.onDisconnect.addListener(() => {
    if (currentPort === port) currentPort = null;
  });

  port.postMessage({ type: 'start' });
});

async function startSync(): Promise<void> {
  // Reject re-entry: if a sync is already in flight (pending tab create or
  // active sync), ignore the new request. The SYNC_PENDING sentinel closes
  // the TOCTOU window between the null check and chrome.tabs.create resolving.
  if (currentSyncTab !== null) {
    void broadcastTerminal({ type: 'error', reason: 'Sync already in progress.' });
    return;
  }
  currentSyncTab = SYNC_PENDING;

  collectedErrors = [];
  void chrome.runtime.sendMessage({ type: 'tab_opening' });

  let tab: chrome.tabs.Tab;
  try {
    // Foreground tab. Amazon's notebook lazy-loads the book list with an
    // IntersectionObserver gated on real visibility; a background tab leaves
    // the list empty and the scrape comes back with zero books. The tab
    // auto-closes on cleanup, so the user only sees a flash.
    tab = await chrome.tabs.create({ url: NOTEBOOK_URL, active: true });
  } catch (err) {
    currentSyncTab = null;
    void broadcastTerminal({
      type: 'error',
      reason: `tab.create failed: ${String(err)}`,
    });
    return;
  }
  if (!tab.id) {
    currentSyncTab = null;
    void broadcastTerminal({ type: 'error', reason: 'tab.create returned no id' });
    return;
  }
  currentSyncTab = tab.id;

  const tabId = tab.id;
  const start = Date.now();
  const handler = (
    updatedId: number,
    info: chrome.tabs.TabChangeInfo,
    t: chrome.tabs.Tab
  ): void => {
    if (updatedId !== tabId) return;
    if (info.status === 'complete' && t.url) {
      if (!t.url.startsWith('https://read.amazon.com/kp/notebook')) {
        void broadcastTerminal({ type: 'login_required' });
        cleanup();
      }
    }
  };
  tabUpdateHandler = handler;
  chrome.tabs.onUpdated.addListener(handler);

  setTimeout(() => {
    if (currentSyncTab !== null && Date.now() - start > TAB_LOAD_TIMEOUT_MS) {
      void broadcastTerminal({ type: 'error', reason: 'Tab did not finish loading within 60s' });
      cleanup();
    }
  }, TAB_LOAD_TIMEOUT_MS + 1000);
}

type ImportEnvelope = {
  schema_version: string;
  exported_at: string;
  source: string;
  books: unknown[];
};

type ImportResult = {
  books_created?: number;
  books_matched?: number;
  highlights_created?: number;
  highlights_skipped_duplicates?: number;
  errors?: unknown[];
  _status?: string;
};

async function onScrapeComplete(payload: ImportEnvelope): Promise<void> {
  const settings = await loadSettings();
  if (!settings) {
    void broadcastTerminal({ type: 'error', reason: 'No server configured. Open settings first.' });
    cleanup();
    return;
  }

  const url = `${settings.server_url}/api/v2/imports/kindle`;
  const json = JSON.stringify(payload);
  const compressed = await gzipString(json);

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Token ${settings.token}`,
        'Content-Type': 'application/json',
        'Content-Encoding': 'gzip',
      },
      body: compressed,
    });
  } catch (err) {
    void broadcastTerminal({
      type: 'error',
      reason: `FreeWise unreachable: ${String(err)}`,
    });
    cleanup();
    return;
  }

  if (response.status === 401) {
    void broadcastTerminal({ type: 'error', reason: 'Token rejected (401)' });
    cleanup();
    return;
  }
  if (!response.ok) {
    const text = await response.text();
    void broadcastTerminal({
      type: 'error',
      reason: `HTTP ${response.status}: ${text.slice(0, 200)}`,
    });
    cleanup();
    return;
  }

  const result = (await response.json()) as ImportResult;
  if (collectedErrors.length > 0) {
    result.errors = (result.errors ?? []).concat(collectedErrors);
  }
  // Persist before broadcasting: Chrome popups close as soon as the user
  // clicks anywhere outside them, so a sync that completes after the popup
  // has closed loses its message. Storing the outcome lets the next popup
  // render show "Last sync: …" instead of leaving the user wondering.
  await chrome.storage.local.set({
    last_sync: { at: Date.now(), result },
  });
  void chrome.runtime.sendMessage({ type: 'sync_complete', result });
  cleanup();
}

// Return ArrayBuffer (not Uint8Array): TypeScript's strict DOM lib types
// reject `Uint8Array<ArrayBufferLike>` for `BodyInit` because the typed-array
// view type isn't part of the BodyInit union. ArrayBuffer is.
async function gzipString(s: string): Promise<ArrayBuffer> {
  const stream = new Response(
    new Blob([s]).stream().pipeThrough(new CompressionStream('gzip'))
  );
  return await stream.arrayBuffer();
}

// Broadcast a terminal status (error / login_required) AND mirror it into
// chrome.storage.local so the next popup open can re-display it. Chrome
// closes the popup the moment focus leaves it, which during a tab-switch
// or alt-tab is most of the time — without this, errors evaporate
// silently and users assume the import "did nothing".
async function broadcastTerminal(
  msg:
    | { type: 'error'; reason: string }
    | { type: 'login_required' },
): Promise<void> {
  void chrome.runtime.sendMessage(msg);
  try {
    await chrome.storage.local.set({
      last_sync: { at: Date.now(), terminal: msg },
    });
  } catch {
    /* storage write is best-effort — never let it mask the original error */
  }
}

function cleanup(): void {
  if (tabUpdateHandler) {
    chrome.tabs.onUpdated.removeListener(tabUpdateHandler);
    tabUpdateHandler = null;
  }
  if (currentSyncTab !== null && currentSyncTab !== SYNC_PENDING) {
    void chrome.tabs.remove(currentSyncTab).catch(() => {});
  }
  currentSyncTab = null;
  currentPort = null;
}

console.info('FreeWise Kindle Importer SW ready');
