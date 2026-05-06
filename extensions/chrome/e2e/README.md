# FreeWise Chrome extension — Playwright E2E

Automated end-to-end coverage for the right-click save flow. Boots a
fresh FreeWise on `:8064`, mints a temp API token, loads the unpacked
extension into a real Chromium profile, then exercises:

| Spec | Verifies |
|---|---|
| `popup.spec.ts` | Popup *Test connection* button reaches `/api/v2/auth/`; *Save* persists base URL + token to `chrome.storage.local`. |
| `save-selection.spec.ts` | Service-worker `postHighlight` POSTs the selection, the API records it, and the popup's "Recent saves" list re-renders with the OK pill. |

## Run it

```bash
bash extensions/chrome/e2e/run.sh           # all specs
bash extensions/chrome/e2e/run.sh popup.spec.ts
```

The runner installs `@playwright/test` + Chromium on first invocation,
spins uvicorn behind a temp SQLite file, seeds an `ApiToken`, then
hands `FREEWISE_E2E_BASE_URL` / `FREEWISE_E2E_TOKEN` to the test
runner. Cleanup is automatic (trap on EXIT).

## Why headed mode

Chromium refuses to load extensions in `--headless=old`, and MV3
service workers don't boot reliably under `--headless=new` as of
Playwright 1.49. CI can wrap the runner with `xvfb-run` for headless
display.

## Driving the right-click without an OS context menu

The OS-level menu can't be triggered from Playwright. Instead the
test calls `postHighlight()` directly inside the service-worker
context — the same function `chrome.contextMenus.onClicked` invokes
when a real user picks "Save selection to FreeWise". This exercises
the entire fetch → /api/v2/highlights → chrome.storage.local pipeline
without paying the cost of a fragile OS-driver.
