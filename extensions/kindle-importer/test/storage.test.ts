import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock chrome.storage.local so storage.ts can run in node.
const mockStorage = new Map<string, unknown>();
(globalThis as any).chrome = {
  storage: {
    local: {
      get: vi.fn(async (keys: string[]) => {
        const out: Record<string, unknown> = {};
        for (const k of keys) if (mockStorage.has(k)) out[k] = mockStorage.get(k);
        return out;
      }),
      set: vi.fn(async (data: Record<string, unknown>) => {
        for (const [k, v] of Object.entries(data)) mockStorage.set(k, v);
      }),
      remove: vi.fn(async (keys: string[]) => {
        for (const k of keys) mockStorage.delete(k);
      }),
    },
  },
};

import { loadSettings, saveSettings, clearSettings } from '../src/lib/storage';

describe('storage', () => {
  beforeEach(() => mockStorage.clear());

  it('returns null when no settings stored', async () => {
    expect(await loadSettings()).toBeNull();
  });

  it('saves and loads settings, stripping trailing slashes from server_url', async () => {
    await saveSettings({ server_url: 'https://x.example.com//', token: 'abc' });
    const s = await loadSettings();
    expect(s).toEqual({ server_url: 'https://x.example.com', token: 'abc' });
  });

  it('clearSettings removes only the relevant keys', async () => {
    mockStorage.set('unrelated', 'keep-me');
    await saveSettings({ server_url: 'https://x', token: 'abc' });
    await clearSettings();
    expect(await loadSettings()).toBeNull();
    expect(mockStorage.get('unrelated')).toBe('keep-me');
  });
});
