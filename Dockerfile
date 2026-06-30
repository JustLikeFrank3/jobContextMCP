# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps for native packages (weasyprint, cffi, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 1b: frontend build (Vite → React SPA served under /app) ────────────
# Debian-based (glibc) image avoids musl edge cases with esbuild/rollup native
# binaries that can surface on Alpine.
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

# Install from the lockfile first so this layer caches unless deps change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Build the SPA. vite.config.js sets base=/app/, output → /frontend/dist.
COPY frontend/ ./
RUN npm run build


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Weasyprint runtime dependencies (Cairo, Pango, GDK-Pixbuf, fonts)
# + curl to fetch the tectonic installer
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    libharfbuzz0b \
    libffi8 \
    shared-mime-info \
    fonts-liberation \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install tectonic (self-contained LaTeX engine, ~10MB vs ~400MB for texlive)
RUN curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.16.9/tectonic-0.16.9-x86_64-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin \
    && chmod +x /usr/local/bin/tectonic \
    && tectonic --version

# Fixed, user-agnostic cache location for tectonic's LaTeX support bundle.
# Set before the warm-up below so both build-time and runtime use the same dir
# regardless of $HOME / the uid the container runs as.
ENV TECTONIC_CACHE_DIR=/opt/tectonic-cache

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Copy the freshly built React SPA from the frontend stage. The app serves it
# under /app (transport/http/app.py:_mount_spa expects /app/frontend/dist).
# frontend/dist is .dockerignore'd, so it must come from the build stage —
# never the build context — guaranteeing a clean, reproducible bundle.
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Pre-fetch tectonic's LaTeX support bundle at build time so the running
# container never needs outbound network to relay.fullyjustified.net. Compiling
# the warm-up letter (which \usepackage{TLCresume} + \input{_header}, mirroring
# the real cover-letter template) caches every package it pulls into
# TECTONIC_CACHE_DIR. This is the one build step that requires network; the
# baked cache then makes runtime cover-letter generation fully offline-capable.
RUN set -eux; \
    cd templates/latex_assets; \
    tectonic _warmup.tex; \
    rm -f _warmup.pdf; \
    chmod -R a+rX "$TECTONIC_CACHE_DIR"

# Entrypoint selects server mode via START_MODE env var:
#   START_MODE=mcp  (default) → python server.py       (Claude Desktop / MCP clients)
#   START_MODE=http           → python -m transport.http.main  (AKS / REST / dashboard)
RUN chmod +x scripts/docker-entrypoint.sh

# Runtime volumes (mounted by user)
#   /workspace  → resume_folder  (your local resumes directory)
#   /leetcode   → leetcode_folder
#   /projects   → side project folders (optional)
VOLUME ["/workspace", "/leetcode", "/projects"]

# SSE / streamable-http port (ignored when MCP_TRANSPORT=stdio)
EXPOSE 8000

# MCP_TRANSPORT: stdio | sse | streamable-http  (default: stdio)
ENV MCP_TRANSPORT=stdio
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000
ENV START_MODE=mcp

# ── OCI image labels ──────────────────────────────────────────────────────────
LABEL org.opencontainers.image.title="jobContextMCP"
LABEL org.opencontainers.image.description="AI-powered job search context MCP server. Manage resumes, cover letters, applications, interview prep, and long-term career memory with RAG and Claude."
LABEL org.opencontainers.image.url="https://github.com/JustLikeFrank3/jobContextMCP"
LABEL org.opencontainers.image.source="https://github.com/JustLikeFrank3/jobContextMCP"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.version="0.6.0"

ENTRYPOINT ["scripts/docker-entrypoint.sh"]
