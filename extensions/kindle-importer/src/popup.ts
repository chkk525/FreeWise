import { loadSettings, saveSettings, clearSettings } from './lib/storage';

const root = document.getElementById('root')!;

type SyncMessage =
  | { type: 'tab_opening' }
  | { type: 'login_required' }
  | { type: 'progress'; current: number; total: number }
  | { type: 'sync_complete'; result: SyncResult }
  | { type: 'error'; reason: string };

type SyncResult = {
  books_created?: number;
  books_matched?: number;
  highlights_created?: number;
  highlights_skipped_duplicates?: number;
  errors?: unknown[];
  _status?: string;
};

// Listener registered exactly once at module load. Earlier versions added
// it inside renderMain(), so every "Edit settings → Save" cycle stacked an
// additional listener and the popup eventually rendered each progress event
// N times. Module-scope handler is safe because renderMain rewrites
// document.getElementById('status') etc. — they're looked up fresh on each
// dispatch.
chrome.runtime.onMessage.addListener((msg: SyncMessage) => {
  handlePopupMessage(msg);
});

async function render(): Promise<void> {
  const settings = await loadSettings();
  if (!settings) {
    renderSettings();
  } else {
    renderMain();
  }
}

function renderSettings(): void {
  root.innerHTML = `
    <p class="intro">Configure your FreeWise server to start.</p>
    <label>
      <span class="label-text">Server URL</span>
      <input id="server" type="url"
             placeholder="https://freewise.chikaki.com or http://192.168.0.171:8063">
    </label>
    <label>
      <span class="label-text">API Token</span>
      <input id="token" type="password" autocomplete="off">
    </label>
    <button id="save" class="primary">Save</button>
  `;
  document.getElementById('save')!.addEventListener('click', async () => {
    const server_url = (document.getElementById('server') as HTMLInputElement).value.trim();
    const token = (document.getElementById('token') as HTMLInputElement).value.trim();
    if (!server_url || !token) {
      alert('Both fields are required.');
      return;
    }
    await saveSettings({ server_url, token });
    render();
  });
}

function renderMain(): void {
  root.innerHTML = `
    <div id="status" class="status">Ready</div>
    <button id="sync" class="primary">Sync now</button>
    <div id="progress" class="progress"></div>
    <div id="result" class="result hidden"></div>
    <button id="settings-link" class="link-button">Edit settings</button>
  `;

  document.getElementById('settings-link')!.addEventListener('click', async () => {
    await clearSettings();
    render();
  });

  document.getElementById('sync')!.addEventListener('click', () => {
    const btn = document.getElementById('sync') as HTMLButtonElement;
    btn.disabled = true;
    chrome.runtime.sendMessage({ type: 'sync_now' });
  });

  // Re-display the last sync's outcome on every popup open. Without this,
  // a sync that completes while the popup is closed (which is most of
  // the time — Chrome auto-closes popups on focus loss) leaves the user
  // with no feedback at all and the import looks like it "did nothing".
  void chrome.storage.local.get(['last_sync']).then((stored) => {
    const last = (stored as { last_sync?: StoredLastSync }).last_sync;
    if (!last) return;
    const result = document.getElementById('result');
    const status = document.getElementById('status');
    if (!result || !status) return;
    const ago = formatAgo(Date.now() - last.at);
    if (last.terminal?.type === 'error') {
      result.classList.remove('hidden', 'success', 'warning');
      result.classList.add('error');
      result.textContent = `Last sync (${ago} ago): ${last.terminal.reason}`;
    } else if (last.terminal?.type === 'login_required') {
      result.classList.remove('hidden', 'success', 'error');
      result.classList.add('warning');
      result.textContent = `Last sync (${ago} ago): please log in to read.amazon.com first.`;
    } else if (last.result) {
      result.classList.remove('hidden', 'warning', 'error');
      result.classList.add('success');
      result.textContent = `Last sync (${ago} ago): ${formatResult(last.result)}`;
    }
    status.textContent = '';
  });
}

type StoredLastSync = {
  at: number;
  result?: SyncResult;
  terminal?:
    | { type: 'error'; reason: string }
    | { type: 'login_required' };
};

function formatAgo(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

function handlePopupMessage(msg: SyncMessage): void {
  const status = document.getElementById('status');
  const progress = document.getElementById('progress');
  const result = document.getElementById('result');
  const sync = document.getElementById('sync') as HTMLButtonElement | null;
  if (!status || !progress || !result) return;

  switch (msg?.type) {
    case 'tab_opening':
      status.textContent = 'Opening read.amazon.com…';
      break;

    case 'login_required':
      status.textContent = '';
      result.classList.remove('hidden', 'success', 'error');
      result.classList.add('warning');
      result.textContent = 'Please log in to read.amazon.com first.';
      if (sync) sync.disabled = false;
      break;

    case 'progress':
      progress.textContent = `Scanning ${msg.current}/${msg.total} books…`;
      break;

    case 'sync_complete': {
      result.classList.remove('hidden', 'warning', 'error');
      result.classList.add('success');
      result.textContent = formatResult(msg.result);
      progress.textContent = '';
      status.textContent = 'Done';
      if (sync) sync.disabled = false;
      break;
    }

    case 'error':
      result.classList.remove('hidden', 'success', 'warning');
      result.classList.add('error');
      result.textContent = `Error: ${msg.reason}`;
      progress.textContent = '';
      status.textContent = '';
      if (sync) sync.disabled = false;
      break;
  }
}

function formatResult(r: SyncResult): string {
  const created = r.highlights_created ?? 0;
  const dup = r.highlights_skipped_duplicates ?? 0;
  const errCount = Array.isArray(r.errors) ? r.errors.length : 0;
  // Server tags the response `_status: "partial"` when one or more books
  // failed mid-import. Surface that distinctly so the user knows there's
  // something to retry.
  const partial = r._status === 'partial' || errCount > 0;
  const suffix = partial ? ` (${errCount} book${errCount === 1 ? '' : 's'} failed)` : '';
  if (created > 0 && dup === 0) return `${partial ? '⚠' : '✓'} Synced ${created} highlights${suffix}`;
  if (created > 0) return `${partial ? '⚠' : '✓'} Added ${created} new · ${dup} already in your library${suffix}`;
  if (dup > 0) return `${partial ? '⚠' : '✓'} Library up to date (${dup} highlights, no changes)${suffix}`;
  return `⚠ No highlights found${suffix}.`;
}

render();
