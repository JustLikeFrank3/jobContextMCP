# jobContextMCP Remote + Mobile Architecture Plan

## Goal

Add remote/mobile access support to jobContextMCP so the system can be used from:
- iPad
- browser clients
- Open WebUI
- VS Code tunnels
- future SaaS/web UI

WITHOUT breaking existing local stdio MCP support for Claude Desktop.

The system currently runs locally on macOS and already supports:
- persistent professional context
- STAR stories
- tone samples
- resume generation
- job analysis
- vector/FAISS retrieval
- LangGraph workflows

We want to expose these capabilities over HTTP/SSE/WebSocket for remote clients while preserving the existing MCP architecture.

---

# High-Level Architecture Target

Current:

```text
Claude Desktop
    ↓ stdio
jobContextMCP
```

Target:

```text
                ┌─────────────────────┐
                │ Claude Desktop      │
                │ (existing stdio)    │
                └──────────┬──────────┘
                           │
                        stdio
                           │
                ┌──────────▼──────────┐
                │   jobContextMCP     │
                │ core tools/services │
                └──────────┬──────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
       REST              SSE             WebSocket
         │                 │                 │
         ▼                 ▼                 ▼
   Open WebUI         Browser UI        iPad clients
   Custom app         Streaming         Remote agents
```

---

# Critical Design Requirement

DO NOT tightly couple business logic to MCP transport.

Refactor into layers:

```text
transport/
    mcp_stdio/
    http/
    websocket/

services/
    resume_service.py
    job_analysis_service.py
    retrieval_service.py
    tone_service.py
    langgraph_service.py

repositories/
    vector_store/
    documents/
    embeddings/

workflows/
    langgraph/
```

The MCP tools should become thin wrappers around reusable services.

---

# Requested Features

## 1. Add FastAPI Server

Implement a FastAPI application exposing HTTP endpoints.

Suggested structure:

```text
server/
    api/
        routes/
        models/
        dependencies/
```

Dependencies:
- FastAPI
- uvicorn
- pydantic

Example startup:

```python
uvicorn server.api.main:app --host 0.0.0.0 --port 8000
```

---

# 2. Add REST Endpoints

Implement endpoints for the most important workflows.

## Job Analysis

```http
POST /api/jobs/analyze
```

Input:

```json
{
  "job_description": "...",
  "target_role": "...",
  "resume_id": "default"
}
```

Returns:
- keyword extraction
- match score
- missing skills
- recommended STAR stories
- suggested resume edits

---

## Resume Generation

```http
POST /api/resumes/generate
```

Returns:
- tailored resume markdown
- ATS optimized version
- optional PDF/docx later

---

## STAR Story Retrieval

```http
POST /api/stories/search
```

Returns:
- semantically relevant STAR stories
- relevance scores
- categorized experience snippets

---

## Tone Sample Retrieval

```http
POST /api/tone/search
```

---

# 3. LangGraph Integration Layer

The experimental LangGraph branch should follow this architecture:

```text
LangGraph nodes
    ↓
service layer
    ↓
repositories/vector store
```

LangGraph should orchestrate workflows only.

The services should remain independently callable from:
- MCP tools
- REST APIs
- future CLI
- future UI

---

# 4. Add Streaming Support

Implement Server-Sent Events (SSE).

Use cases:
- streaming resume generation
- live job analysis progress
- multi-step LangGraph workflows

Suggested endpoint:

```http
GET /api/workflows/stream/{session_id}
```

This is especially important for browser/iPad UX.

---

# 5. Authentication

Implement lightweight auth.

Recommended:
- API keys initially
- JWT later if needed

Simple first version:

```http
Authorization: Bearer <token>
```

Store token in:

```text
.env
```

---

# 6. Add Remote Access Support

Recommended setup:
- Tailscale-compatible
- LAN-safe by default
- configurable host binding

DO NOT expose publicly by default.

Suggested config:

```env
HOST=127.0.0.1
PORT=8000
ENABLE_REMOTE=false
```

---

# 7. Preserve Existing MCP Support

The existing stdio MCP server MUST continue working.

Refactor MCP tools into wrappers like:

```python
@mcp.tool()
async def analyze_job(...):
    return await job_analysis_service.analyze(...)
```

Avoid duplicated logic between HTTP and MCP.

---

# 8. Suggested Near-Term UX

Target usage flow:

```text
iPad Safari
    ↓
Open WebUI
    ↓
jobContextMCP HTTP API
    ↓
LangGraph workflows + retrieval
```

This should enable:
- recruiter-call workflows
- couch/mobile resume editing
- rapid job assessment
- STAR story retrieval
- AI-assisted tailoring

without requiring local MCP support on iPad.

---

# 9. Suggested Nice-to-Haves

Future-ready ideas:
- SQLite/Postgres metadata layer
- hybrid BM25 + vector retrieval
- Redis cache
- background job queue
- resumable workflow sessions
- conversation persistence
- export pipeline (PDF/DOCX)
- recruiter/company memory

---

# 10. Important Non-Goals

Do NOT:
- rewrite the entire MCP server
- remove stdio support
- tightly bind UI to backend
- make LangGraph the only orchestration path
- overengineer auth initially

Prioritize:
- modularity
- transport independence
- mobile/browser usability
- clean service abstraction

---

# Deliverables

1. Working FastAPI server
2. Shared service layer
3. Existing MCP compatibility preserved
4. REST endpoints implemented
5. SSE streaming support
6. LangGraph integration cleaned up
7. Example Open WebUI integration docs
8. Example iPad/browser workflow docs

