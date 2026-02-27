# ═══════════════════════════════════════════════════════════════════════
#  FreeWise – Production Dockerfile (multi-stage)
#
#  Stage 1  "tailwind"  – Node 20-alpine  → compiles Tailwind CSS
#  Stage 2  "runtime"   – Python 3.12-slim → lean production image
# ═══════════════════════════════════════════════════════════════════════

# ── Stage 1: Build Tailwind CSS ──────────────────────────────────────
FROM node:20-alpine AS tailwind
WORKDIR /build

COPY package.json tailwind.config.js ./
RUN npm install

# Copy only what Tailwind needs to scan for class usage
COPY app/templates/            app/templates/
COPY app/static/css/input.css  app/static/css/input.css
COPY app/static/sw.js          app/static/sw.js

RUN npm run build:css


# ── Stage 2: Python production image ─────────────────────────────────
FROM python:3.12-slim AS runtime

# Prevent .pyc files and enable real-time log output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/freewise

# System deps – curl is used by the HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN groupadd -r freewise && useradd -r -g freewise -d /srv/freewise freewise

# Install Python dependencies (exclude test-only packages)
COPY requirements.txt .
RUN grep -vE '^\s*(pytest|pytest-asyncio)\b' requirements.txt > requirements-prod.txt \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-prod.txt \
    && rm requirements-prod.txt requirements.txt

# Copy the application source
COPY app/ app/

# Overwrite the development CSS with the freshly-compiled version
COPY --from=tailwind /build/app/static/css/tailwind.css app/static/css/tailwind.css

# Prepare writable directories for runtime data
RUN mkdir -p db app/static/uploads/covers \
    && chown -R freewise:freewise /srv/freewise

USER freewise

EXPOSE 8063

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8063/ || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8063"]
