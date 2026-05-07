# Ollama Operations for FreeWise

This FreeWise deployment uses Ollama on the Mac as the embedding and RAG
model host. The QNAP FreeWise container calls the Mac over the LAN.

Current production shape:

- FreeWise: QNAP Docker container, LAN `192.168.0.171:8063`
- Ollama: Mac launchd service, LAN `192.168.0.151:11434`
- Embedding model: `nomic-embed-text`
- Generate model: `llama3.2`
- Embedding input cap: `FREEWISE_EMBED_TEXT_MAX_CHARS=1000`

## Daily Check

On the Mac:

```bash
ollama list
curl -fsS http://127.0.0.1:11434/api/tags
```

From the FreeWise repo on the Mac:

```bash
ssh qnap 'export PATH=/share/CACHEDEV1_DATA/.qpkg/container-station/bin:$PATH; docker exec freewise curl -fsS http://127.0.0.1:8063/healthz'
```

Healthy output should show:

```text
"embedded_pct":100.0
"ollama":{"host":"192.168.0.151","reachable":true
```

## Start or Restart Ollama

Ollama should run through Homebrew services with a launchd environment that
binds it to the LAN, not just `127.0.0.1`.

```bash
launchctl setenv OLLAMA_HOST 0.0.0.0:11434
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
brew services restart ollama
```

Verify from both sides:

```bash
curl -fsS http://127.0.0.1:11434/api/tags
ssh qnap 'curl -fsS --connect-timeout 5 http://192.168.0.151:11434/api/tags'
```

If the Mac LAN IP changes, update QNAP:

```bash
ssh qnap 'cd /share/Container/freewise && sed -i "s#^FREEWISE_OLLAMA_URL=.*#FREEWISE_OLLAMA_URL=http://NEW_MAC_IP:11434#" .env.qnap'
ssh qnap 'export PATH=/share/CACHEDEV1_DATA/.qpkg/container-station/bin:$PATH; cd /share/Container/freewise && docker compose -f docker-compose.qnap.yml --env-file .env.qnap up -d'
```

## Pull Models

Run on the Mac:

```bash
ollama pull nomic-embed-text
ollama pull llama3.2
```

## Backfill Embeddings

Backfill is resumable. New highlights imported after the initial full backfill
only need incremental embedding.

Run inside the QNAP FreeWise container:

```bash
ssh qnap 'export PATH=/share/CACHEDEV1_DATA/.qpkg/container-station/bin:$PATH; docker exec -i freewise python -' <<'PY'
from sqlmodel import Session
from app.db import get_engine
from app.services.embeddings import backfill_embeddings

with Session(get_engine()) as s:
    report = backfill_embeddings(s, batch_size=128, model="nomic-embed-text")
print(report.as_dict())
PY
```

Repeat until `remaining` is `0`.

## Performance Notes

Production measurements after full backfill:

- Related-highlight top-k: about 1 second
- Full semantic duplicate page: about 50 seconds for 23k highlights
- Repeated semantic duplicate calls with the same library fingerprint are served
  from a process-local cache for 10 minutes by default

The duplicate page computes all pairwise similarities, so it is expected to be
much heavier than related-highlight lookup. The cache key includes the model,
user, threshold, limit, chunk size, and an active-embedding fingerprint, so new
imports, new embeddings, discard, and restore actions naturally trigger a fresh
scan.

To tune or disable the cache, set this in QNAP `.env.qnap` and recreate the
container:

```bash
FREEWISE_SEMANTIC_DUP_CACHE_TTL_SECONDS=600
```

Use `0` to disable caching.

## Operational Risks

- If the Mac sleeps, FreeWise semantic features and `/ask` lose Ollama access.
- If the Mac IP changes, update `FREEWISE_OLLAMA_URL` in QNAP `.env.qnap`.
- If `llama3.2` is not pulled, embeddings still work but `/ask` generation fails.
- Long highlights are embedded from the first 1000 characters by default to avoid
  Ollama context-length failures.
