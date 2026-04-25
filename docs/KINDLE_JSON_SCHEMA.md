# Kindle Notebook Export JSON Schema

The contract between the **scraper** (separate repo: `freewise-qnap-deploy`,
`feat/kindle-scraper` branch) and the **importer** (this repo, `app/importers/kindle_notebook.py`).

Both sides MUST agree on this schema. When changing it, bump `schema_version`
and update the importer to handle both old and new versions until the scraper
is also upgraded.

## Top-level

```json
{
  "schema_version": "1.0",
  "exported_at": "2026-04-25T12:34:56Z",
  "source": "kindle_notebook",
  "books": [...]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | yes | semver-ish. Importer rejects unknown majors. |
| `exported_at` | ISO-8601 string (UTC) | yes | When the scraper finished. Used as fallback `created_at`. |
| `source` | string | yes | Always `"kindle_notebook"` for this scraper. |
| `books` | array | yes | May be empty. |

## Book

```json
{
  "asin": "B07FCMBLM6",
  "title": "Sapiens: A Brief History of Humankind",
  "author": "Yuval Noah Harari",
  "cover_url": "https://m.media-amazon.com/images/I/...",
  "highlights": [...]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `asin` | string | yes | Amazon Standard Identification Number. Stable book identifier; primary dedup key. Stored in `Book.document_tags` as `asin:<value>` until a dedicated column is added. |
| `title` | string | yes | As shown in Kindle library. |
| `author` | string \| null | no | May be missing for self-published or very old titles. |
| `cover_url` | string \| null | no | Mapped to `Book.cover_image_url`, with `cover_image_source = "kindle"`. |
| `highlights` | array | yes | May be empty (book in library with no highlights). |

## Highlight

```json
{
  "id": "QID:abc123",
  "text": "The cognitive revolution kicked off about 70,000 years ago.",
  "note": "Compare to Diamond's GGS chronology.",
  "color": "yellow",
  "location": 1234,
  "page": 45,
  "created_at": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Kindle-internal identifier (`data-id` on the highlight DOM element). Primary dedup key for highlights within a book. |
| `text` | string | yes | The highlighted passage. May contain newlines. |
| `note` | string \| null | no | User's annotation. |
| `color` | enum: `"yellow"`, `"blue"`, `"pink"`, `"orange"`, `null` | no | Kindle highlight color. Not in current `Highlight` model — importer SHOULD prepend `[color]` to `note` only if the user opts in (CLI flag). v1: ignore. |
| `location` | int \| null | no | Kindle Location number. Mapped to `Highlight.location` with `location_type = "kindle_location"`. |
| `page` | int \| null | no | Page number when available. Used as fallback when `location` is null, with `location_type = "page"`. |
| `created_at` | ISO-8601 string \| null | no | **Kindle does NOT expose timestamps via kp/notebook.** Always null in v1. Importer falls back to top-level `exported_at`. |

## Mapping to FreeWise models

| JSON | FreeWise field |
|---|---|
| `book.title` | `Book.title` |
| `book.author` | `Book.author` |
| `book.cover_url` | `Book.cover_image_url` (+ `cover_image_source = "kindle"`) |
| `book.asin` | `Book.document_tags` += `"asin:<value>"` (v1; dedicated column later) |
| `highlight.text` | `Highlight.text` |
| `highlight.note` | `Highlight.note` |
| `highlight.location` | `Highlight.location` (`location_type = "kindle_location"`) |
| `highlight.page` | fallback for `Highlight.location` if `location` is null (`location_type = "page"`) |
| `highlight.created_at` | `Highlight.created_at`, falling back to top-level `exported_at` |
| `highlight.color` | (v1: ignored) |
| `highlight.id` | (not stored; used as in-memory dedup key during import) |

## Dedup rules

- **Book**: match existing `Book` row by `(title, author)` first (current FreeWise behavior). If `asin` is present and a future schema adds a dedicated column, prefer ASIN.
- **Highlight**: within a book, match by `(text, location)` to avoid duplicates on re-import. The scraper-provided `highlight.id` is NOT persisted; it is only used for the scraper's own internal change tracking.

## Validation

The importer MUST:

1. Reject the file if `schema_version` major differs from supported.
2. Reject the file if `source != "kindle_notebook"`.
3. Skip (with a warning) any book missing `title` or `asin`.
4. Skip (with a warning) any highlight missing `text` or `id`.
5. Continue processing the remainder on per-record errors (best-effort import, never a single bad row failing the whole file).
