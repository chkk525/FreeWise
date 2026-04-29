import { loadSettings } from './lib/storage';

const NOTEBOOK_URL = 'https://read.amazon.com/kp/notebook';
const TAB_LOAD_TIMEOUT_MS = 60_000;

let currentSyncTab: number | null = null;
let currentPort: chrome.runtime.Port | null = null;
let collectedErrors: { book_title: string; reason: string }[] = [];

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === 'sync_now') {
    void startSync();
  }
});

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'kindle-sync') return;
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
        void chrome.runtime.sendMessage({ type: 'error', reason: String(e) });
        cleanup();
      });
    } else if (msg?.type === 'error') {
      void chrome.runtime.sendMessage({ type: 'error', reason: msg.reason });
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
  // Reject re-entry: if a sync is already in flight, ignore the new request.
  if (currentSyncTab !== null) {
    void chrome.runtime.sendMessage({
      type: 'error',
      reason: 'Sync already in progress.',
    });
    return;
  }

  collectedErrors = [];
  void chrome.runtime.sendMessage({ type: 'tab_opening' });

  const tab = await chrome.tabs.create({ url: NOTEBOOK_URL, active: false });
  if (!tab.id) {
    void chrome.runtime.sendMessage({
      type: 'error',
      reason: 'tab.create returned no id',
    });
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
        chrome.tabs.onUpdated.removeListener(handler);
        void chrome.runtime.sendMessage({ type: 'login_required' });
        cleanup();
      }
    }
  };
  chrome.tabs.onUpdated.addListener(handler);

  setTimeout(() => {
    if (currentSyncTab !== null && Date.now() - start > TAB_LOAD_TIMEOUT_MS) {
      chrome.tabs.onUpdated.removeListener(handler);
      void chrome.runtime.sendMessage({
        type: 'error',
        reason: 'Tab did not finish loading within 60s',
      });
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
    void chrome.runtime.sendMessage({
      type: 'error',
      reason: 'No server configured. Open settings first.',
    });
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
    void chrome.runtime.sendMessage({
      type: 'error',
      reason: `FreeWise unreachable: ${String(err)}`,
    });
    cleanup();
    return;
  }

  if (response.status === 401) {
    void chrome.runtime.sendMessage({
      type: 'error',
      reason: 'Token rejected (401)',
    });
    cleanup();
    return;
  }
  if (!response.ok) {
    const text = await response.text();
    void chrome.runtime.sendMessage({
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
  void chrome.runtime.sendMessage({ type: 'sync_complete', result });
  cleanup();
}

async function gzipString(s: string): Promise<Uint8Array> {
  const stream = new Response(
    new Blob([s]).stream().pipeThrough(new CompressionStream('gzip'))
  );
  return new Uint8Array(await stream.arrayBuffer());
}

function cleanup(): void {
  if (currentSyncTab !== null) {
    void chrome.tabs.remove(currentSyncTab).catch(() => {});
    currentSyncTab = null;
  }
  currentPort = null;
}

console.info('FreeWise Kindle Importer SW ready');
