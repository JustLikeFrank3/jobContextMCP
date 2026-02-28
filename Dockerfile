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


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Weasyprint runtime dependencies (Cairo, Pango, GDK-Pixbuf, fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libharfbuzz0b \
    libffi8 \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

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

CMD ["python", "server.py"]
