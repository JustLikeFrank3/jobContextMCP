This MCP server solves that by giving any AI assistant a set of tools it can call to retrieve all of that context instantly.

---

## Architecture

### System Overview

```mermaid
graph TB
    subgraph "VS Code Workspace"
        VSCode[VS Code + GitHub Copilot]
        MCP[MCP Server<br/>FastMCP + Python]
    end
    
    subgraph "Data Layer"
        Config[config.json<br/>Paths + API Keys]
        Status[status.json<br/>Job Pipeline]
        Mental[mental_health_log.json<br/>Check-ins]
        Context[personal_context.json<br/>Stories]
        Tone[tone_samples.json<br/>Writing Voice]
        RAG[Vector Index<br/>Embeddings]
    end
    
    subgraph "Resume Folder"
        Master[Master Resume.txt]
        Resumes[01-Current-Optimized/<br/>Tailored Resumes]
        Covers[02-Cover-Letters/<br/>Cover Letters]
        PDFs[03-Resume-PDFs/<br/>Exported PDFs]
        Ref[06-Reference-Materials/<br/>Awards, Feedback]
    end
    
    subgraph "External"
        OpenAI[OpenAI API<br/>GPT-4 + Embeddings]
        Projects[Side Projects<br/>Skill Scanner]
    end
    
    VSCode <-->|MCP Protocol| MCP
    MCP -->|Read/Write| Config
    MCP -->|Read/Write| Status
    MCP -->|Read/Write| Mental
    MCP -->|Read/Write| Context
    MCP -->|Read/Write| Tone
    MCP -->|Query| RAG
    MCP -->|Read/Write| Master
    MCP -->|Read/Write| Resumes
    MCP -->|Read/Write| Covers
    MCP -->|Generate| PDFs
    MCP -->|Read| Ref
    MCP -->|Optional| OpenAI
    MCP -->|Scan| Projects
    
    style VSCode fill:#0969da
    style MCP fill:#1f883d
    style OpenAI fill:#8250df
```

### Tool Categories

```mermaid
graph LR
    subgraph "Job Hunt Tools"
        A1[get_job_hunt_status]
        A2[update_application]
    end
    
    subgraph "Resume Tools"
        B1[read_master_resume]
        B2[list_existing_materials]
        B3[read_existing_resume]
        B4[read_reference_file]
    end
    
    subgraph "Fitment & Strategy"
        C1[assess_job_fitment]
        C2[get_customization_strategy]
    end
    
    subgraph "Interview Prep"
        D1[get_interview_quick_reference]
        D2[get_leetcode_cheatsheet]
        D3[generate_interview_prep_context]
        D4[get_existing_prep_file]
        D5[get_star_story_context]
    end
    
    subgraph "Mental Health"
        E1[log_mental_health_checkin]
        E2[get_mental_health_log]
    end
    
    subgraph "RAG Search"
        F1[search_materials]
        F2[reindex_materials]
    end
    
    subgraph "Personal Context (v3)"
        G1[log_personal_story]
        G2[get_personal_context]
    end
    
    subgraph "Tone System (v3)"
        H1[log_tone_sample]
        H2[get_tone_profile]
        H3[scan_materials_for_tone]
    end
    
    subgraph "Generation (v4/v4.1)"
        I1[generate_resume]
        I2[generate_cover_letter]
        I3[export_resume_pdf]
        I4[export_cover_letter_pdf]
        I5[draft_outreach_message]
    end
    
    subgraph "Skills Scanner (v4)"
        J1[scan_project_for_skills]
    end
    
    style A1 fill:#ddf4ff
    style B1 fill:#ddf4ff
    style C1 fill:#fff8c5
    style D1 fill:#ffe3e3
    style E1 fill:#f6e3ff
    style F1 fill:#e3f7ed
    style G1 fill:#ffedd5
    style H1 fill:#ffe3f7
    style I1 fill:#d5f3ff
    style J1 fill:#e3e3ff
```

### Data Flow: Resume Generation

```mermaid
sequenceDiagram
    participant User as User (Copilot Chat)
    participant MCP as MCP Server
    participant Data as Data Layer
    participant OpenAI as OpenAI API
    participant Files as File System
    
    User->>MCP: generate_resume("Stripe", "SWE", "JD text")
    MCP->>Data: Load master resume
    Data-->>MCP: Master resume content
    MCP->>Data: Load tone profile
    Data-->>MCP: Writing samples
    MCP->>Data: Get customization strategy
    Data-->>MCP: Role-specific guidance
    
    alt OpenAI key configured
        MCP->>OpenAI: Generate tailored resume
        OpenAI-->>MCP: Generated content
    else No OpenAI key
        MCP-->>User: Context package (for Copilot)
        User->>MCP: save_resume_txt(content)
    end
    
    MCP->>Files: Save .txt file
    Files-->>MCP: File saved
    MCP->>Files: Render PDF (WeasyPrint)
    Files-->>MCP: PDF exported
    MCP-->>User: ✅ Resume saved + PDF exported
```

### Workspace Structure Flow

```mermaid
graph TD
    subgraph "Multi-Root VS Code Workspace"
        Root1[job-search-mcp/<br/>MCP Server]
        Root2[Resume 2025/<br/>Materials]
        Root3[LeetCodePractice/<br/>Interview Prep]
        Root4[Side Project/<br/>Skills Source]
    end
    
    Root1 -->|.vscode/mcp.json| AutoStart[Auto-start MCP Server]
    Root2 -->|.github/copilot-instructions.md| Context1[Call get_session_context]
    Root3 -->|.github/copilot-instructions.md| Context2[Call get_session_context]
    Root4 -->|Scannable by MCP| Scanner[scan_project_for_skills]
    
    AutoStart -->|Tools Available| Copilot[GitHub Copilot]
    Context1 -->|Session Context| Copilot
    Context2 -->|Session Context| Copilot
    Scanner -->|Resume Bullets| Copilot
    
    style Root1 fill:#1f883d
    style Root2 fill:#0969da
    style Root3 fill:#8250df
    style Root4 fill:#d1242f
    style Copilot fill:#0969da
```

### Personal Context & Tone System (v3)

```mermaid
graph LR
    subgraph "Input Sources"
        Stories[log_personal_story<br/>Family stories, motivations]
        Samples[log_tone_sample<br/>Past writing samples]
        Scanner[scan_materials_for_tone<br/>Auto-extract from files]
    end
    
    subgraph "Storage"
        ContextDB[(personal_context.json<br/>Stories + Tags + People)]
        ToneDB[(tone_samples.json<br/>Text + Source + Context)]
        ScanIndex[(scan_index.json<br/>Processed files)]
    end
    
    subgraph "Retrieval"
        GetContext[get_personal_context<br/>Filter by tag/person]
        GetTone[get_tone_profile<br/>All samples]
        GetSTAR[get_star_story_context<br/>Stories + Metrics + Framing]
    end
    
    subgraph "Usage"
        CoverLetter[Cover Letter Generation]
        Interview[Interview Prep]
        Outreach[Outreach Messages]
    end
    
    Stories --> ContextDB
    Samples --> ToneDB
    Scanner --> ToneDB
    Scanner --> ScanIndex
    
    ContextDB --> GetContext
    ToneDB --> GetTone
    ContextDB --> GetSTAR
    
    GetContext --> CoverLetter
    GetContext --> Interview
    GetContext --> Outreach
    GetTone --> CoverLetter
    GetTone --> Outreach
    GetSTAR --> Interview
    
    style ContextDB fill:#ffedd5
    style ToneDB fill:#ffe3f7
    style ScanIndex fill:#e3e3ff
```

### RAG Search Architecture

```mermaid
graph TB
    subgraph "Indexing Phase"
        Materials[Resume Files<br/>Cover Letters<br/>Prep Docs]
        Embedder[OpenAI<br/>text-embedding-3-small]
        VectorDB[(Vector Index<br/>Embeddings + Metadata)]
    end
    
    subgraph "Query Phase"
        Query[search_materials<br/>semantic query]
        Matcher[Similarity Search<br/>Cosine Distance]
        Results[Ranked Results<br/>+ Context Snippets]
    end
    
    Materials -->|One-time| Embedder
    Embedder -->|Store| VectorDB
    Query -->|Embed Query| Embedder
    Embedder -->|Query Vector| Matcher
    VectorDB -->|Compare| Matcher
    Matcher --> Results
    
    Reindex[reindex_materials<br/>Rebuild index]
    Reindex -.->|Trigger| Embedder
    
    style VectorDB fill:#e3f7ed
    style Embedder fill:#8250df
    style Results fill:#ddf4ff
```
