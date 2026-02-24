# JobContextMCP v0.5 (v5) Visual Roadmap

## Objective
Enable users to bootstrap a full JobContextMCP workspace conversationally via CLI or Copilot.

## Flow Diagram (ASCII / Markdown-friendly)

```
[User clones repo]
        |
        v
[Run CLI: setup_workspace()] -----------------+
        |                                     |
        v                                     v
[Interactive prompts]                     [Copilot Chat]
  - Workspace root                          - Conversational guidance
  - Resumes folder                           - Explain folder purpose
  - Pipeline folder                          - Suggest starter data
  - Materials folder                          (same as CLI)
  - Preferred language (Java/Python/etc.)
        |
        v
[Directories + starter templates created]
        |
        v
[config.json generated with user settings]
        |
        v
[Optional multi-language prep scaffolding]
        |
        v
[Workspace ready]
```

### Key Features
- CLI-first, optional Copilot guidance
- Multi-language coding prep support
- Starter templates and sample pipeline/resume data
- Fully automated folder and file creation

### Deliverables
- `setup_workspace()` CLI script
- `setup_workspace_conversational()` MCP/Copilot function
- Multi-language prep folders with templates
- Config-driven workspace setup
