import { test, expect } from "./fixtures.js";

/**
 * Drives the full save-highlight pipeline that the right-click menu
 * triggers in real use. We can't simulate the OS-level context menu
 * from Playwright, so the service worker fires
 * ``chrome.contextMenus.onClicked`` with the same shape Chrome uses,
 * then we verify:
 *
 *   1. The popup's "Recent saves" history shows the OK entry.
 *   2. The FreeWise API search endpoint actually returns the
 *      highlight we just sent.
 */
test("right-click → POST → highlight visible via search API", async ({
  context,
  extensionId,
  serviceWorker,
  baseUrl,
  apiToken,
}) => {
  // Pre-seed config so the worker has somewhere to POST.
  await serviceWorker.evaluate(async ([url, tok]) => {
    await chrome.storage.local.set({ baseUrl: url, token: tok, lastSaves: [] });
  }, [baseUrl, apiToken]);

  // Use a unique substring so the search query is deterministic even
  // when the dev DB already has thousands of imports.
  const marker = "FW-E2E-MARKER-" + Math.random().toString(36).slice(2, 10);
  const text = `Stoicism teaches discipline and acceptance. ${marker}`;
  const sourceUrl = "https://example.com/e2e-clip";
  const title = "FreeWise E2E article";

  // background.js declares ``postHighlight`` at module scope of a
  // classic service worker (no ``"type": "module"`` in manifest), so
  // it lands on ``globalThis``. We call it directly with the same
  // shape the contextMenus listener would build — this exercises the
  // exact code path that runs after a right-click, just without the
  // OS-level chrome the test runner can't drive.
  await serviceWorker.evaluate(
    async ([t, src, ttl]) => {
      // @ts-expect-error — function lives on globalThis at runtime.
      if (typeof postHighlight !== "function") {
        throw new Error("postHighlight not on globalThis — background.js shape changed");
      }
      // @ts-expect-error — see above.
      await postHighlight({ text: t, title: ttl, sourceUrl: src });
    },
    [text, sourceUrl, title],
  );

  // Background fetch is async; give it a beat.
  // Poll lastSaves until the OK entry appears (or timeout).
  const lastSave = await serviceWorker.evaluate(async () => {
    for (let i = 0; i < 40; i++) {
      const { lastSaves = [] } = await chrome.storage.local.get(["lastSaves"]);
      if (lastSaves.length) return lastSaves[0];
      await new Promise((r) => setTimeout(r, 250));
    }
    return null;
  });
  expect(lastSave, "service worker did not record a save outcome").not.toBeNull();
  expect(lastSave.ok).toBe(true);
  expect(lastSave.title).toBe(title);
  expect(lastSave.url).toBe(sourceUrl);

  // Now verify the highlight actually landed in FreeWise.
  const searchResp = await fetch(
    baseUrl + "/api/v2/highlights/search?q=" + encodeURIComponent(marker),
    { headers: { Authorization: `Token ${apiToken}` } },
  );
  expect(searchResp.status).toBe(200);
  const body = (await searchResp.json()) as {
    count: number;
    results: { text: string }[];
  };
  expect(body.count, "marker not found via /api/v2/highlights/search").toBeGreaterThan(0);
  expect(body.results[0].text).toContain(marker);

  // And the popup re-renders the recent saves list.
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  await expect(popup.locator("#recent-list")).toContainText("OK");
  await expect(popup.locator("#recent-list")).toContainText(title);
});
