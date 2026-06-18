import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from lib import config
from lib.io import _load_master_context


def _git_pull(folder: Path) -> str:
    """Attempt git pull on a project folder. Returns a one-line status string."""
    try:
        result = subprocess.run(
            ["git", "-C", str(folder), "pull"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return output or "Already up to date."
        return f"warning: {output}"
    except subprocess.TimeoutExpired:
        return "skipped: git pull timed out (>20s)"
    except FileNotFoundError:
        return "skipped: git not found in PATH"
    except Exception as e:
        return f"skipped: {e}"


def _clone_repo(url: str, dest: Path, branch: str = "") -> str:
    """Shallow-clone a git repo URL into dest. Returns a one-line status string."""
    try:
        cmd = ["git", "clone", "--depth=1"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [url, str(dest)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return "cloned ok"
        return f"warning: {output}"
    except subprocess.TimeoutExpired:
        return "skipped: clone timed out (>60s)"
    except FileNotFoundError:
        return "skipped: git not found in PATH"
    except Exception as e:
        return f"skipped: {e}"

# ── Technology detection registry ─────────────────────────────────────────────
# Each entry:
#   label       — display name (also used as the set key)
#   resume_kw   — keywords to check in the master resume (already-on-resume gate)
#   exts        — file extensions to match (empty = any extension)
#   filenames   — exact filenames (lowercase) that are sufficient alone (no content check)
#   content     — file content: ANY of these → match (only checked after ext/filename gate)
#   content_all — file content: ALL of these must be present → match
_TECH_REGISTRY: list[dict] = [
    # ── Languages ──────────────────────────────────────────────────────────────
    {"label": "Python",                      "resume_kw": ["python"],                                        "exts": [".py"]},
    {"label": "Go",                          "resume_kw": ["golang", " go "],                                "exts": [".go"]},
    {"label": "Rust",                        "resume_kw": ["rust"],                                          "exts": [".rs"]},
    {"label": "Java",                        "resume_kw": ["java"],                                          "exts": [".java"]},
    {"label": "Kotlin",                      "resume_kw": ["kotlin"],                                        "exts": [".kt", ".kts"]},
    {"label": "TypeScript/JavaScript",       "resume_kw": ["typescript"],                                    "exts": [".ts", ".tsx", ".js", ".jsx"]},
    {"label": "Swift / iOS",                 "resume_kw": ["swift"],                                         "exts": [".swift"]},
    {"label": "C# / .NET",                   "resume_kw": ["c#", "csharp", ".net"],                          "exts": [".cs"]},
    {"label": "Ruby",                        "resume_kw": ["ruby"],                                          "exts": [".rb"]},
    {"label": "PHP",                         "resume_kw": ["php"],                                           "exts": [".php"]},
    {"label": "Scala",                       "resume_kw": ["scala"],                                         "exts": [".scala"]},
    {"label": "C / C++",                     "resume_kw": ["c++"],                                           "exts": [".c", ".cpp", ".h", ".hpp"]},
    {"label": "Dart / Flutter",              "resume_kw": ["dart", "flutter"],                               "exts": [".dart"]},
    # ── Python frameworks & libraries ─────────────────────────────────────────
    {"label": "FastAPI",                     "resume_kw": ["fastapi"],                                       "exts": [".py"],               "content": ["fastapi"]},
    {"label": "Django",                      "resume_kw": ["django"],                                        "exts": [".py"],               "content": ["django"]},
    {"label": "Flask",                       "resume_kw": ["flask"],                                         "exts": [".py"],               "content": ["flask"]},
    {"label": "Pydantic",                    "resume_kw": ["pydantic"],                                      "exts": [".py"],               "content": ["pydantic"]},
    {"label": "SQLAlchemy",                  "resume_kw": ["sqlalchemy"],                                    "exts": [".py"],               "content": ["sqlalchemy"]},
    {"label": "Celery",                      "resume_kw": ["celery"],                                        "exts": [".py"],               "content": ["celery"]},
    {"label": "Python async/await",          "resume_kw": ["async/await", "async def"],                      "exts": [".py"],               "content": ["async def"]},
    {"label": "WebSockets",                  "resume_kw": ["websocket"],                                     "exts": [".py", ".ts", ".js"], "content": ["websocket"]},
    {"label": "pytest",                      "resume_kw": ["pytest"],                                        "exts": [".py"],               "content": ["pytest", "conftest"]},
    # ── JS / TS frontend & mobile ─────────────────────────────────────────────
    {"label": "React",                       "resume_kw": ["react"],                                         "exts": [".ts", ".tsx", ".js", ".jsx"], "content": ["react"]},
    {"label": "React Native",                "resume_kw": ["react native"],                                  "exts": [".ts", ".tsx", ".js", ".jsx"], "content": ["react-native", "react native"]},
    {"label": "Next.js",                     "resume_kw": ["next.js", "nextjs"],                             "exts": [".ts", ".tsx", ".js", ".jsx"], "content": ["from 'next", "next/router", "next/image"]},
    {"label": "Vue.js",                      "resume_kw": ["vue"],                                           "exts": [".vue", ".ts", ".js"],         "content": ["vue"]},
    {"label": "Angular",                     "resume_kw": ["angular"],                                       "exts": [".ts"],               "content": ["@angular"]},
    {"label": "Svelte",                      "resume_kw": ["svelte"],                                        "exts": [".svelte"]},
    {"label": "Expo",                        "resume_kw": ["expo"],                                          "exts": [".ts", ".tsx", ".js", ".jsx"], "content": ["expo"]},
    {"label": "iOS TestFlight deployment",   "resume_kw": ["testflight"],                                    "exts": [".ts", ".tsx", ".js"],"content": ["testflight"]},
    # ── Databases ──────────────────────────────────────────────────────────────
    {"label": "SQLite / aiosqlite",          "resume_kw": ["sqlite", "aiosqlite"],                           "exts": [".py"],               "content": ["sqlite", "aiosqlite"]},
    {"label": "PostgreSQL",                  "resume_kw": ["postgresql", "postgres"],                        "exts": [".py", ".ts", ".js", ".go", ".java", ".yml", ".yaml"], "content": ["postgresql", "postgres", "psycopg"]},
    {"label": "MySQL",                       "resume_kw": ["mysql"],                                         "exts": [".py", ".ts", ".js", ".go", ".java"], "content": ["mysql"]},
    {"label": "MongoDB",                     "resume_kw": ["mongodb", "mongoose"],                           "exts": [".py", ".ts", ".js", ".go"], "content": ["mongodb", "mongoose", "pymongo"]},
    {"label": "Redis",                       "resume_kw": ["redis"],                                         "exts": [".py", ".ts", ".js", ".go"], "content": ["redis"]},
    {"label": "DynamoDB",                    "resume_kw": ["dynamodb"],                                      "exts": [".py", ".ts", ".js"], "content": ["dynamodb"]},
    {"label": "Elasticsearch",               "resume_kw": ["elasticsearch"],                                 "exts": [".py", ".ts", ".js"], "content": ["elasticsearch"]},
    {"label": "Pinecone",                    "resume_kw": ["pinecone"],                                      "exts": [".py", ".ts"],        "content": ["pinecone"]},
    {"label": "Snowflake",                   "resume_kw": ["snowflake"],                                     "exts": [".py", ".sql"],       "content": ["snowflake"]},
    {"label": "Cassandra",                   "resume_kw": ["cassandra"],                                     "exts": [".py", ".java"],      "content": ["cassandra"]},
    # ── Cloud — Azure ──────────────────────────────────────────────────────────
    {"label": "Azure Blob Storage",          "resume_kw": ["azure blob"],                                    "exts": [".py", ".ts", ".yml", ".yaml", ".sh"], "content": ["azure blob", "blob storage", "blobserviceclient"]},
    {"label": "Microsoft Entra ID (PKCE/OIDC)", "resume_kw": ["entra", "pkce", "oidc", "msal", "workload identity", "workload.identity"],
                                                                                                              "exts": [".py", ".ts", ".js", ".yml", ".yaml"], "content": ["entra", "pkce", "oidc", "msal", "workload.identity"]},
    {"label": "AKS / Azure Kubernetes",      "resume_kw": ["aks", "azure kubernetes"],                       "exts": [".sh", ".yml", ".yaml"], "content": ["az aks", "aks"]},
    {"label": "Azure Functions",             "resume_kw": ["azure functions"],                               "exts": [".py", ".ts", ".js", ".yml"], "content": ["azure.functions", "azure function"]},
    # ── Cloud — AWS ────────────────────────────────────────────────────────────
    {"label": "AWS",                         "resume_kw": ["aws", "amazon web services"],                    "exts": [".py", ".ts", ".js", ".go", ".tf", ".yml", ".yaml", ".sh"], "content": ["boto3", "aws-sdk", "amazonaws", "@aws-sdk"]},
    {"label": "AWS Lambda",                  "resume_kw": ["aws lambda", "serverless"],                      "exts": [".py", ".ts", ".js", ".go"], "content": ["lambda_handler", "aws_lambda"]},
    {"label": "AWS S3",                      "resume_kw": ["s3", "aws s3"],                                  "exts": [".py", ".ts", ".js"], "content_all": ["s3", "boto3"]},
    {"label": "AWS CDK / CloudFormation",    "resume_kw": ["cdk", "cloudformation"],                         "exts": [".py", ".ts", ".yml", ".yaml"], "content": ["aws-cdk", "cloudformation", "cdk.stack"]},
    # ── Cloud — GCP ────────────────────────────────────────────────────────────
    {"label": "Google Cloud (GCP)",          "resume_kw": ["google cloud", "gcp"],                           "exts": [".py", ".ts", ".js", ".go", ".tf", ".yml"], "content": ["google.cloud", "googleapis", "gcloud", "firebase"]},
    # ── Containers & orchestration ─────────────────────────────────────────────
    {"label": "Docker",                      "resume_kw": ["docker"],                                        "filenames": ["dockerfile", "docker-compose.yml", "docker-compose.yaml"]},
    {"label": "Docker",                      "resume_kw": ["docker"],                                        "exts": [".py", ".sh", ".yml", ".yaml"], "content": ["docker"]},
    {"label": "Docker Compose",              "resume_kw": ["docker compose"],                                "filenames": ["docker-compose.yml", "docker-compose.yaml"]},
    {"label": "Kubernetes (K8s)",            "resume_kw": ["kubernetes", "k8s"],                             "exts": [".yaml", ".yml", ".sh", ".py"], "content": ["kubectl", "kubernetes", "kind: deployment", "kind: service", "apiversion: apps"]},
    {"label": "Helm",                        "resume_kw": ["helm"],                                          "exts": [".yaml", ".yml"],     "content": ["helm.sh", "helmchart", "chart.yaml"]},
    {"label": "ArgoCD",                      "resume_kw": ["argocd", "argo cd"],                             "exts": [".yaml", ".yml"],     "content": ["argocd", "argoproj"]},
    # ── Infrastructure as Code ─────────────────────────────────────────────────
    {"label": "Terraform IaC",               "resume_kw": ["terraform"],                                     "exts": [".tf", ".tfvars"]},
    {"label": "Pulumi",                      "resume_kw": ["pulumi"],                                        "exts": [".py", ".ts"],        "content": ["pulumi"]},
    {"label": "Ansible",                     "resume_kw": ["ansible"],                                       "exts": [".yml", ".yaml"],     "content": ["ansible"]},  # require 'ansible' keyword; '- hosts:' alone fires on K8s ingress
    {"label": "GitHub Actions",              "resume_kw": ["github actions"],                                "exts": [".yml", ".yaml"],     "content": ["github.com/actions", "runs-on:"]},
    # ── Messaging & streaming ──────────────────────────────────────────────────
    {"label": "Apache Kafka",                "resume_kw": ["kafka"],                                         "exts": [".py", ".java", ".go", ".ts", ".yml", ".yaml"], "content": ["kafka"]},
    {"label": "RabbitMQ",                    "resume_kw": ["rabbitmq"],                                      "exts": [".py", ".ts", ".go"], "content": ["rabbitmq", "amqp"]},
    {"label": "AWS SQS / SNS",               "resume_kw": ["sqs", "sns"],                                    "exts": [".py", ".ts", ".go"], "content": ["sqs", "sns"]},
    # ── AI / ML ────────────────────────────────────────────────────────────────
    {"label": "RAG / semantic search",       "resume_kw": ["rag", "faiss", "sentence_transformers", "text-embedding"],
                                                                                                              "exts": [".py"],               "content": ["faiss", "sentence_transformers", "text-embedding"]},
    {"label": "LangChain",                   "resume_kw": ["langchain"],                                     "exts": [".py", ".ts"],        "content": ["from langchain import", "import langchain", "langchain_"]},  # require import-level usage
    {"label": "OpenAI API",                  "resume_kw": ["openai"],                                        "exts": [".py", ".ts", ".js"], "content": ["openai"]},
    {"label": "Anthropic / Claude API",      "resume_kw": ["anthropic", "claude"],                           "exts": [".py", ".ts", ".js"], "content": ["anthropic", "claude"]},
    {"label": "Hugging Face / Transformers", "resume_kw": ["hugging face", "huggingface", "transformers"],   "exts": [".py"],               "content": ["transformers", "from_pretrained", "huggingface"]},
    {"label": "PyTorch",                     "resume_kw": ["pytorch"],                                       "exts": [".py"],               "content": ["import torch", "torch.nn"]},
    {"label": "TensorFlow / Keras",          "resume_kw": ["tensorflow", "keras"],                           "exts": [".py"],               "content": ["tensorflow", "keras"]},
    {"label": "scikit-learn",                "resume_kw": ["scikit", "sklearn"],                             "exts": [".py"],               "content": ["from sklearn import", "import sklearn", "sklearn."]},  # require import-level usage
    {"label": "Model Context Protocol (MCP)","resume_kw": ["model context protocol", "mcp server", "fastmcp"],
                                                                                                              "exts": [".py"],               "content": ["fastmcp", "mcp.tool"]},
    {"label": "FastMCP",                     "resume_kw": ["fastmcp"],                                       "exts": [".py"],               "content": ["fastmcp"]},
    # ── Observability ──────────────────────────────────────────────────────────
    {"label": "Prometheus / Grafana",        "resume_kw": ["prometheus", "grafana"],                         "exts": [".py", ".yml", ".yaml"], "content": ["prometheus", "grafana"]},
    {"label": "OpenTelemetry",               "resume_kw": ["opentelemetry", "otel"],                         "exts": [".py", ".ts", ".go"], "content": ["opentelemetry", "otel"]},
    {"label": "Datadog",                     "resume_kw": ["datadog"],                                       "exts": [".py", ".ts", ".yml"],"content": ["datadog", "ddtrace"]},
    {"label": "Sentry",                      "resume_kw": ["sentry"],                                        "exts": [".py", ".ts", ".js"], "content": ["sentry"]},
    # ── Auth & security ────────────────────────────────────────────────────────
    {"label": "JWT authentication",          "resume_kw": ["jwt"],                                           "exts": [".py", ".ts", ".js", ".go"], "content": ["jwt", "bearer"]},
    {"label": "OAuth 2.0",                   "resume_kw": ["oauth"],                                         "exts": [".py", ".ts", ".js", ".go"], "content": ["oauth2", " oauth"]},
    {"label": "Auth0",                       "resume_kw": ["auth0"],                                         "exts": [".py", ".ts", ".js"], "content": ["auth0"]},
    # ── Protocols & patterns ───────────────────────────────────────────────────
    {"label": "gRPC",                        "resume_kw": ["grpc"],                                          "exts": [".proto"]},
    {"label": "gRPC",                        "resume_kw": ["grpc"],                                          "exts": [".py", ".go", ".java", ".ts"], "content": ["grpc"]},
    {"label": "GraphQL",                     "resume_kw": ["graphql"],                                       "exts": [".py", ".ts", ".js"], "content": ["graphql"]},
    {"label": "HTTP Range requests",         "resume_kw": ["range request", "http range"],                   "exts": [".py"],               "content_all": ["range", "http"]},
    {"label": "Automated retention policies","resume_kw": ["retention"],                                     "exts": [".py"],               "content": ["retention"]},
    # ── Hardware / embedded / Linux ────────────────────────────────────────────
    {"label": "Raspberry Pi GPIO",           "resume_kw": ["gpio"],                                          "exts": [".py"],               "content": ["gpio", "rpi"]},
    {"label": "Servo / Adafruit HAT",        "resume_kw": ["servo"],                                         "exts": [".py"],               "content": ["servo", "adafruit"]},
    {"label": "systemd / Linux services",    "resume_kw": ["systemd"],                                       "exts": [".py", ".sh"],        "content": ["systemd"]},
    # ── Document generation ────────────────────────────────────────────────────
    {"label": "WeasyPrint / PDF generation", "resume_kw": ["weasyprint"],                                    "exts": [".py"],               "content": ["weasyprint"]},
    {"label": "LaTeX / Tectonic",            "resume_kw": ["latex", "tectonic"],                             "exts": [".tex", ".py", ".sh"],"content": ["latex", "tectonic", "\\documentclass"]},
]

# Derived resume-keyword lookup (used in scan_project_for_skills)
_RESUME_KW: dict[str, list[str]] = {}
for _e in _TECH_REGISTRY:
    if _e["label"] not in _RESUME_KW:
        _RESUME_KW[_e["label"]] = _e["resume_kw"]


def _file_matches_tech(entry: dict, ext: str, fname_lower: str, text: str) -> bool:
    """Return True if this file satisfies the detection rule for an entry."""
    filenames = entry.get("filenames", [])
    exts = entry.get("exts", [])
    content_any = entry.get("content", [])
    content_all = entry.get("content_all", [])

    # Exact filename → immediate match, no content check needed
    if fname_lower in filenames:
        return True

    # Extension gate
    if exts and ext not in exts:
        return False

    # Content checks (only reached when file passed ext gate)
    if content_any and not any(kw in text for kw in content_any):
        return False
    if content_all and not all(kw in text for kw in content_all):
        return False

    return True


def _scan_folder(folder: Path) -> tuple[set[str], int]:
    """Scan a single project folder and return (tech_found, file_count)."""
    tech_found: set[str] = set()
    file_count = 0
    skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv", "env", ".expo", "build", "dist"}
    skip_exts = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz",
                 ".db", ".lock", ".whl", ".pyc", ".ico", ".ttf", ".woff", ".woff2"}
    # Skip files that list technology names as template/demo strings rather than using them.
    # project_scanner.py has _TECH_REGISTRY; gen_demo_docs.py has hardcoded tech-name strings.
    skip_files = {"project_scanner.py", "gen_demo_docs.py"}

    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

        for fname in files:
            if fname.lower() in skip_files:
                continue
            fpath = Path(root) / fname
            ext = fpath.suffix.lower()
            fname_lower = fname.lower()
            file_count += 1

            if ext in skip_exts:
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore").lower()
            except Exception:
                continue

            for entry in _TECH_REGISTRY:
                if entry["label"] in tech_found:
                    continue  # already detected — skip remaining checks for this label
                if _file_matches_tech(entry, ext, fname_lower, text):
                    tech_found.add(entry["label"])

    return tech_found, file_count


def scan_project_for_skills() -> str:
    """Scan all configured side-project directories (side_project_folders in config.json) and detect technologies used. Pulls latest changes from git before scanning each. Reports newly detected skills not yet on the master resume so they can be added."""
    folders = config.SIDE_PROJECT_FOLDERS
    repos = getattr(config, "SIDE_PROJECT_REPOS", [])

    if not folders and not repos:
        return "No side project folders or repos configured. Add 'side_project_folders' or 'side_project_repos' to config.json."

    missing = [str(f) for f in folders if not f.exists()]
    if missing and not repos:
        return "Side project folder(s) not found:\n" + "\n".join(f"  {m}" for m in missing)

    all_tech: set[str] = set()
    per_project: list[tuple[str, set[str], int, str]] = []  # (name, tech, file_count, pull_status)
    tmp_dirs: list[Path] = []

    try:
        for folder in folders:
            if not folder.exists():
                per_project.append((folder.name, set(), 0, "skipped: folder not found"))
                continue
            pull_status = _git_pull(folder)
            tech, file_count = _scan_folder(folder)
            all_tech |= tech
            per_project.append((folder.name, tech, file_count, pull_status))

        for entry in repos:
            if isinstance(entry, dict):
                url = entry.get("url", "")
                branch = entry.get("branch", "")
            else:
                url = entry
                branch = ""
            repo_name = url.rstrip("/").split("/")[-1]
            label = f"{repo_name}@{branch}" if branch else repo_name
            tmp = Path(tempfile.mkdtemp(prefix=f"jcmcp_scan_{repo_name}_"))
            tmp_dirs.append(tmp)
            clone_status = _clone_repo(url, tmp, branch)
            if clone_status.startswith(("skipped", "warning")):
                per_project.append((label, set(), 0, clone_status))
                continue
            tech, file_count = _scan_folder(tmp)
            all_tech |= tech
            per_project.append((label, tech, file_count, clone_status))

    finally:
        for tmp in tmp_dirs:
            shutil.rmtree(tmp, ignore_errors=True)

    resume_text = _load_master_context().lower()

    def _on_resume(tech: str) -> bool:
        keywords = _RESUME_KW.get(tech, [tech.lower()])
        return any(kw in resume_text for kw in keywords)

    already_on_resume = {t for t in all_tech if _on_resume(t)}
    new_skills = sorted(all_tech - already_on_resume)

    lines = ["═══ SIDE PROJECT SKILL SCAN ═══", ""]

    for name, tech, file_count, pull_status in per_project:
        lines.append(f"── {name} ({file_count} files, git pull: {pull_status}) ──")
        for t in sorted(tech):
            marker = "  ✓" if t in already_on_resume else "  ★ NEW"
            lines.append(f"{marker}  {t}")
        lines.append("")

    lines += ["── New Skills Not Yet on Master Resume (across all projects) ──"]
    lines += [f"  • {s}" for s in new_skills] or ["  (none — master resume is up to date)"]

    lines += [
        "",
        "── Suggested Resume Bullets ──",
    ]

    if "Raspberry Pi GPIO" in all_tech:
        lines.append("  • Built production IoT camera system integrating Raspberry Pi hardware, "
                     "servo HAT, Python/FastAPI backend, and React Native mobile app")
    if "Pydantic" in all_tech:
        lines.append("  • Designed type-safe API layer with FastAPI + Pydantic models")
    if "Python async/await" in all_tech:
        lines.append("  • Implemented async Python services for concurrent hardware + network I/O")
    if "Azure Blob Storage" in all_tech:
        lines.append("  • Integrated Azure Blob Storage with automated 7-day retention management")
    if "HTTP Range requests" in all_tech:
        lines.append("  • Enabled on-demand video streaming via HTTP Range request support")
    if "systemd / Linux services" in all_tech:
        lines.append("  • Configured systemd service for reliable auto-start on embedded Linux")
    if "WebSockets" in all_tech:
        lines.append("  • Delivered real-time camera stream via WebSocket connections")
    if "JWT authentication" in all_tech:
        lines.append("  • Secured API endpoints with JWT bearer-token authentication")
    if "Model Context Protocol (MCP)" in all_tech:
        lines.append("  • Built production MCP server enabling persistent AI context across job search sessions "
                     "via FastMCP (Python) with 30+ tools, RAG semantic search, and PDF generation")
    if "WeasyPrint / PDF generation" in all_tech:
        lines.append("  • Implemented PDF generation pipeline from plain .txt via WeasyPrint HTML/CSS templates")
    if "RAG / semantic search" in all_tech:
        lines.append("  • Built RAG semantic search layer over resume materials using text embeddings")
    if "SQLite / aiosqlite" in all_tech:
        lines.append("  • Replaced JSON flat-file storage with SQLite (aiosqlite) for concurrent-safe, "
                     "multi-user data persistence in production")
    if "Microsoft Entra ID (PKCE/OIDC)" in all_tech:
        lines.append("  • Implemented Microsoft Entra ID PKCE/OIDC authentication with per-user data isolation, "
                     "B2B guest invitations, and workload identity on AKS")
    if "Kubernetes (K8s)" in all_tech or "AKS / Azure Kubernetes" in all_tech:
        lines.append("  • Deployed containerized services on Kubernetes (AKS) with rolling updates, "
                     "health probes, persistent volume claims, and workload identity")
    if "GitHub Actions" in all_tech:
        lines.append("  • Built CI/CD pipeline with GitHub Actions: Docker build → ACR push → AKS rolling deploy")
    if "PostgreSQL" in all_tech:
        lines.append("  • Designed relational schema with PostgreSQL; optimized queries and managed migrations")
    if "Redis" in all_tech:
        lines.append("  • Implemented Redis caching and pub/sub for session management and real-time events")
    if "Apache Kafka" in all_tech:
        lines.append("  • Built event-driven pipeline with Apache Kafka for async, fault-tolerant service communication")
    if "LangChain" in all_tech:
        lines.append("  • Built LLM-powered workflows with LangChain: tool chains, memory, and retrieval augmentation")
    if "OpenAI API" in all_tech:
        lines.append("  • Integrated OpenAI API for generative AI features with structured outputs and function calling")
    if "Anthropic / Claude API" in all_tech:
        lines.append("  • Integrated Anthropic Claude API for AI assistant features in production applications")
    if "gRPC" in all_tech:
        lines.append("  • Designed high-performance inter-service communication with gRPC and Protocol Buffers")
    if "GraphQL" in all_tech:
        lines.append("  • Built flexible GraphQL API layer replacing REST endpoints for complex data queries")
    if "Terraform IaC" in all_tech:
        lines.append("  • Provisioned and managed cloud infrastructure as code with Terraform")
    if "Prometheus / Grafana" in all_tech:
        lines.append("  • Instrumented services with Prometheus metrics and built Grafana dashboards for observability")
    if "LaTeX / Tectonic" in all_tech:
        lines.append("  • Automated LaTeX/Tectonic document compilation pipeline for professional PDF generation")

    return "\n".join(lines)


def register(mcp) -> None:
    mcp.tool()(scan_project_for_skills)
