import { test as base, chromium, type BrowserContext, type Worker } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// extensions/chrome/  ←  one level up from extensions/chrome/e2e
const EXTENSION_PATH = path.resolve(__dirname, "..");

export type FreewiseFixtures = {
  context: BrowserContext;
  extensionId: string;
  serviceWorker: Worker;
  baseUrl: string;
  apiToken: string;
};

/**
 * Each test gets a fresh persistent Chromium profile with the
 * unpacked FreeWise extension loaded. The service worker is awaited
 * before the test body runs so chrome.contextMenus / chrome.storage
 * are guaranteed to exist.
 *
 * `baseUrl` and `apiToken` are read from env vars set by the runner
 * script (so the same code paths exercise dev/prod when needed).
 */
export const test = base.extend<FreewiseFixtures>({
  baseUrl: async ({}, use) => {
    const v = process.env.FREEWISE_E2E_BASE_URL;
    if (!v) throw new Error("FREEWISE_E2E_BASE_URL must be set");
    await use(v);
  },
  apiToken: async ({}, use) => {
    const v = process.env.FREEWISE_E2E_TOKEN;
    if (!v) throw new Error("FREEWISE_E2E_TOKEN must be set");
    await use(v);
  },
  context: async ({}, use) => {
    const userDataDir = path.join(
      __dirname,
      ".pw-profile-" + Math.random().toString(36).slice(2, 8),
    );
    const ctx = await chromium.launchPersistentContext(userDataDir, {
      headless: false,
      args: [
        `--disable-extensions-except=${EXTENSION_PATH}`,
        `--load-extension=${EXTENSION_PATH}`,
        // Chrome refuses extensions in --headless=old. We launch headed,
        // but on CI the workflow can wrap with xvfb-run.
        "--no-first-run",
        "--no-default-browser-check",
      ],
    });
    await use(ctx);
    await ctx.close();
  },
  serviceWorker: async ({ context }, use) => {
    let [sw] = context.serviceWorkers();
    if (!sw) sw = await context.waitForEvent("serviceworker");
    await use(sw);
  },
  extensionId: async ({ serviceWorker }, use) => {
    // chrome-extension://<id>/...
    const url = serviceWorker.url();
    const m = url.match(/^chrome-extension:\/\/([^/]+)\//);
    if (!m) throw new Error("Could not extract extension id from " + url);
    await use(m[1]);
  },
});

export const expect = test.expect;
