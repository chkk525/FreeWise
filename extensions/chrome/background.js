// FreeWise Save Highlight — service worker.
//
// Wires a right-click context menu on selected text → POST to the configured
// FreeWise /api/v2/highlights endpoint with the Readwise-shaped JSON body.
// Token + base URL are stored via chrome.storage.sync.

const MENU_ID = "freewise-save-selection";

function notify(title, message) {
  // Notifications API requires the icon to exist; chrome falls back gracefully
  // if it doesn't, but we set it anyway.
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon-48.png",
    title,
    message: message.slice(0, 240),
  });
}

async function loadConfig() {
  const { baseUrl, token } = await chrome.storage.sync.get(["baseUrl", "token"]);
  return { baseUrl: baseUrl || "", token: token || "" };
}

async function postHighlight({ text, title, sourceUrl }) {
  const { baseUrl, token } = await loadConfig();
  if (!baseUrl || !token) {
    notify(
      "FreeWise: not configured",
      "Open the extension popup and set the FreeWise base URL + API token first.",
    );
    return;
  }

  const url = baseUrl.replace(/\/+$/, "") + "/api/v2/highlights/";
  const body = {
    highlights: [
      {
        text,
        title: title || "Web clipping",
        source_url: sourceUrl,
        source_type: "article",
        category: "articles",
        highlighted_at: new Date().toISOString(),
      },
    ],
  };

  try {
    const r = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": `Token ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (r.status === 201 || r.status === 200) {
      const j = await r.json().catch(() => ({}));
      notify(
        "FreeWise: saved",
        `Created ${j.created || 1} highlight (${j.skipped_duplicates || 0} dupes).`,
      );
    } else {
      const t = await r.text().catch(() => "");
      notify(`FreeWise: HTTP ${r.status}`, t.slice(0, 240) || r.statusText);
    }
  } catch (e) {
    notify("FreeWise: network error", String(e));
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "Save selection to FreeWise",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  const text = (info.selectionText || "").trim();
  if (!text) return;
  const title = tab?.title || "";
  const sourceUrl = info.pageUrl || tab?.url || "";
  await postHighlight({ text, title, sourceUrl });
});
