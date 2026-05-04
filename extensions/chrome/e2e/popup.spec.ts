import { test, expect } from "./fixtures.js";

test.describe("FreeWise extension — popup configuration", () => {
  test("Test connection succeeds against the live FreeWise instance", async ({
    context,
    extensionId,
    baseUrl,
    apiToken,
  }) => {
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);

    await popup.fill("#baseUrl", baseUrl);
    await popup.fill("#token", apiToken);
    await popup.click("#test");

    // popup.js writes "OK (204)." or "OK (200)." into #status on success.
    await expect(popup.locator("#status")).toContainText(/OK \(\d+\)/, {
      timeout: 10_000,
    });
    await expect(popup.locator("#status")).toHaveClass(/ok/);
  });

  test("Save button persists baseUrl + token to chrome.storage.local", async ({
    context,
    extensionId,
    baseUrl,
    apiToken,
    serviceWorker,
  }) => {
    const popup = await context.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);

    await popup.fill("#baseUrl", baseUrl);
    await popup.fill("#token", apiToken);
    await popup.click("#save");
    await expect(popup.locator("#status")).toHaveText("Saved.");

    const stored = await serviceWorker.evaluate(async () => {
      return await chrome.storage.local.get(["baseUrl", "token"]);
    });
    expect(stored.baseUrl).toBe(baseUrl);
    expect(stored.token).toBe(apiToken);
  });
});
