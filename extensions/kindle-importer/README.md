# FreeWise Kindle Importer (Chrome MV3)

A Chrome extension that scrapes the user's own Kindle "Your Notebook"
page (`https://read.amazon.com/kp/notebook`) and uploads the parsed
highlights to a self-hosted FreeWise server. Single-user, unpacked
load only — not distributed via the Chrome Web Store.

## Build

```sh
npm install
npm run build      # one-shot
npm run dev        # watch mode
```

## Load

1. `npm run build`
2. Chrome → `chrome://extensions/` → enable Developer mode → Load unpacked → select `extensions/kindle-importer/dist/`

## Test

```sh
npm run test
```

## Architecture

- `manifest.json` — MV3 manifest (host permissions for `read.amazon.com` and `freewiseapi.chikaki.com`)
- `src/popup.{html,ts,css}` — toolbar popup UI (server URL, token, "Sync now")
- `src/background.ts` — service worker; orchestrates scrape + POST
- `src/content.ts` — runs on `read.amazon.com/kp/notebook`; extracts the DOM
- `dist/` — built output, loadable as unpacked extension
