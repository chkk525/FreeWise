# Semantic similarity (C2) setup

FreeWise's "related highlights" feature uses local embeddings via
[Ollama](https://ollama.com). This is the one thing Readwise can't do:
your library never leaves your network, and the model is yours to swap.

## Why Ollama (vs sentence-transformers / fastembed)

- Self-hosted matches FreeWise's privacy ethos.
- Zero new heavy Python deps (no PyTorch, no ONNX runtime).
- Easy model swap via env var (`FREEWISE_OLLAMA_EMBED_MODEL`).
- Optional: if Ollama is unreachable, the rest of the app keeps working;
  related-highlights sections show a "not yet embedded" hint instead.

The QNAP CPU is too weak for fast embedding inference — run Ollama on a
laptop or other host with more compute, and point FreeWise at it.

## 1. Install + run Ollama

```bash
# macOS
brew install ollama
ollama serve &            # background daemon on 127.0.0.1:11434

# Linux
curl -fsSL https://ollama.com/install.sh | sh
systemctl --user enable --now ollama
```

## 2. Pull an embedding model

```bash
# Default: 768-dim, English-tuned, ~80MB
ollama pull nomic-embed-text

# Better for Japanese / multilingual: ~330MB
ollama pull jeffh/intfloat-multilingual-e5-large

# Larger English-only, 1024-dim: ~660MB
ollama pull mxbai-embed-large
```

The default is `nomic-embed-text` — change with `FREEWISE_OLLAMA_EMBED_MODEL`.

## 3. Make Ollama reachable from the FreeWise container

If Ollama runs on the same host as the QNAP container, that's already
on the LAN. Otherwise expose it on a routable interface:

```bash
# Bind to all interfaces (Ollama defaults to 127.0.0.1)
OLLAMA_HOST=0.0.0.0:11434 ollama serve &
```

Then in `~/Development/freewise-qnap-deploy/.env.qnap`:

```
FREEWISE_OLLAMA_URL=http://<host-on-LAN>:11434
FREEWISE_OLLAMA_EMBED_MODEL=nomic-embed-text
```

Re-deploy: `LOCAL_SRC=~/Development/freewise-kindle bash ~/Development/freewise-qnap-deploy/tools/deploy_qnap.sh`

## 4. Backfill embeddings

```bash
# Loops in batches of 64 until done. Resumable — re-running picks up
# where it stopped because we filter on NOT EXISTS.
freewise embed-backfill

# Override per-call:
freewise embed-backfill --batch-size 128 --max 1000 --model mxbai-embed-large
```

For a 25k-highlight library:
- ~25k Ollama calls, sequenced one at a time
- ~50-200ms per call depending on model + host
- Estimated total: 20-90 minutes

Re-running `embed-backfill` after a partial run only processes the
remainder. Failed rows (Ollama timeout, etc.) stay in the pending pool
and get retried on the next call.

## 5. Verify

The dashboard will show "Semantic similarity: X% embedded" once the
first batch lands. Visit any `/highlights/ui/h/{id}` permalink — the
"Related highlights" section auto-loads via HTMX.

From Claude Code (via the MCP server):

> Find me other highlights in my library related to highlight #1234.

→ Claude calls `freewise_related(highlight_id=1234)` and you get scored matches.

## Switching models

Models can coexist — the `embedding` table is keyed by `(highlight_id,
model_name)`. To A/B test a new model:

```bash
export FREEWISE_OLLAMA_EMBED_MODEL=mxbai-embed-large
freewise embed-backfill                  # backfills the new model alongside the old one
freewise related 1234 --model mxbai-embed-large
```

Each `related` call uses the model passed via `--model`, falling back
to `FREEWISE_OLLAMA_EMBED_MODEL`.

## Troubleshooting

**`OllamaUnavailable: could not reach Ollama at http://...`**
- Check `FREEWISE_OLLAMA_URL` points at a reachable host
- Verify with `curl http://<host>:11434/api/tags` from the QNAP

**`Ollama returned HTTP 404: model not found`**
- Run `ollama pull <model-name>` on the Ollama host

**Backfill is slow**
- Default sequencing is one call at a time. Increase Ollama's
  parallelism (`OLLAMA_NUM_PARALLEL=4`) and re-run

**Dashboard says 0% even after backfill**
- Coverage counts only `is_discarded=False` highlights for the
  *currently configured* model. If you changed `FREEWISE_OLLAMA_EMBED_MODEL`,
  rerun backfill for the new model.
