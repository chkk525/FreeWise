# FreeWise Save Highlight (Chrome / Chromium MV3)

A minimal browser extension that lets you right-click any selection on a web
page and save it to your FreeWise instance via its Readwise-compatible
`/api/v2/highlights/` endpoint.

## Install (developer mode)

1. Open `chrome://extensions/` (Chrome / Edge / Brave / Arc / Vivaldi all work).
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select this `extensions/chrome/` directory.
4. Pin the extension icon to the toolbar.

## Configure

1. Open your FreeWise instance and create an API token:
   `https://<your-host>/import/api-token` → enter a label → Create → **copy the
   token shown ONCE**.
2. Click the FreeWise extension icon in the toolbar.
3. Fill **Base URL** (e.g. `https://freewise.chikaki.com`) and **API Token**.
4. Click **Save**, then **Test connection** — you should see "OK (204)".

## Usage

1. On any web page, select text you want to save.
2. Right-click → **Save selection to FreeWise**.
3. A native notification confirms creation (or surfaces the HTTP error).

## What gets sent

```json
{
  "highlights": [
    {
      "text": "<your selection>",
      "title": "<page title>",
      "source_url": "<page URL>",
      "source_type": "article",
      "category": "articles",
      "highlighted_at": "<ISO-8601 now>"
    }
  ]
}
```

The FreeWise API dedups by (book, text, location) so re-saving the same
selection is a no-op.

## Cloudflare Access note

If your FreeWise is behind Cloudflare Access (Google OAuth), the API path
`/api/v2/*` MUST be excluded from the human auth flow. Add a Service Token
bypass policy in the Cloudflare Access app:

- Application: your FreeWise hostname
- Path: `/api/v2/*`
- Action: bypass
- Service token: any (the Authorization header is already FreeWise-internal)

Without this, the extension's POST will be intercepted by Cloudflare and
returned as 302 → Google login HTML.

## Icons

Icons are intentionally not committed (any 16/48/128 PNG works). For now the
manifest references `icons/icon-{16,48,128}.png` — drop your own PNGs in
`icons/` or remove the `icons` block from `manifest.json` and the action's
default Chrome puzzle icon will be used instead.

## License

CC0 — same as FreeWise itself.
