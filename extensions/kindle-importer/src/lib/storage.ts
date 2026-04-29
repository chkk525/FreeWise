export type Settings = {
  server_url: string;
  token: string;
};

export async function loadSettings(): Promise<Settings | null> {
  const data = await chrome.storage.local.get(['server_url', 'token']);
  if (!data.server_url || !data.token) return null;
  return { server_url: data.server_url, token: data.token };
}

export async function saveSettings(s: Settings): Promise<void> {
  await chrome.storage.local.set({
    server_url: s.server_url.replace(/\/+$/, ''),
    token: s.token,
  });
}

export async function clearSettings(): Promise<void> {
  await chrome.storage.local.remove(['server_url', 'token']);
}
