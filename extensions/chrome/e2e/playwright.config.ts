import { defineConfig } from "@playwright/test";

// MV3 service workers + chrome.* APIs only run inside real Chromium with
// the extension loaded via `--disable-extensions-except` and
// `--load-extension`. That requires a *persistent* context and headed
// mode (chrome:extension service workers don't boot in headless=new
// reliably as of Playwright 1.49).
export default defineConfig({
  testDir: ".",
  fullyParallel: false, // single browser, single context — keep deterministic
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    actionTimeout: 10_000,
    trace: "retain-on-failure",
  },
  timeout: 60_000,
});
