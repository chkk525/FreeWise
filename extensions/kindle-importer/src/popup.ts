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
};

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
             placeholder="https://freewiseapi.chikaki.com">
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

  chrome.runtime.onMessage.addListener((msg: SyncMessage) => {
    handlePopupMessage(msg);
  });
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
  if (created > 0 && dup === 0) return `✓ Synced ${created} highlights`;
  if (created > 0) return `✓ Added ${created} new · ${dup} already in your library`;
  if (dup > 0) return `✓ Library up to date (${dup} highlights, no changes)`;
  return `⚠ No highlights found.`;
}

render();
