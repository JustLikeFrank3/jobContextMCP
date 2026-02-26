from pathlib import Path

from lib.io import _load_master_context
from lib import config


def assess_job_fitment(company: str, role: str, job_description: str) -> str:
    """Package Frank's master resume alongside a job description so the AI can assess fit, identify gaps, and recommend which experience to emphasize for this specific role."""
    master = _load_master_context()
    return (
        f"═══ FITMENT ASSESSMENT ═══\n"
        f"Company: {company}\n"
        f"Role:    {role}\n\n"
        f"──── JOB DESCRIPTION ────\n{job_description}\n\n"
        f"──── FRANK'S MASTER RESUME ────\n{master}"
    )


def get_customization_strategy(role_type: str) -> str:
    """Return a resume customization strategy for a given role type. Valid values: testing, cloud, data_engineering, backend, fullstack, ai_innovation, iot. Advises which skills and stories to lead with."""
    strategies = {
        "testing": (
            "Lead with JUnit/Mockito/Selenium expertise, 80%+ coverage metrics, TDD practices. "
            "Feature the 'prevented production defects' story. "
            "Highlight Karma/Jest for frontend testing."
        ),
        "cloud": (
            "Lead with Azure Container Apps, Terraform IaC, zero-downtime PCF→OCF→Azure migration. "
            "Emphasize containerization, CI/CD pipelines, and infrastructure-as-code."
        ),
        "data_engineering": (
            "Lead with IBM DataStage, PySpark ETL pipelines, Oracle→PostgreSQL migration. "
            "Emphasize data modeling, multi-source integration, and warehouse work."
        ),
        "backend": (
            "Lead with microservices architecture, event-driven pub/sub, Spring Boot, "
            "98% SLA compliance on production forecasting app. "
            "Emphasize distributed systems debugging, on-call rotation, observability."
        ),
        "fullstack": (
            "Lead with Java/Spring Boot + Angular/TypeScript full ownership. "
            "Emphasize API design, end-to-end modernization, cross-functional product work."
        ),
        "ai_innovation": (
            "Lead with GitHub Copilot champion story: 35% org adoption, 3.5x target. "
            "Emphasize technical evangelism, AI tooling adoption, and measurable team impact."
        ),
        "iot": (
            "Lead with IoT Engineering degree, RetrosPiCam project (FastAPI + Raspberry Pi + servo HAT), "
            "hardware/software integration, and Azure edge/cloud connectivity. "
            "Tie in LiveVox latency work (2.8ms web, 12.7ms iOS) as embedded-adjacent."
        ),
    }
    result = strategies.get(role_type.lower())
    if result:
        return f"Strategy for '{role_type}':\n\n{result}"
    return f"Unknown role type: '{role_type}'\nAvailable options: {', '.join(strategies)}"


def save_job_assessment(company: str, content: str, filename: str = "") -> str:
    """Save a generated job fitment assessment to the 07-Job-Assessments folder as a .md file. Filename defaults to {Company} - Fitment Assessment.md. Always use this tool to save assessments instead of creating files directly."""
    if not filename:
        slug = company.strip().replace("/", "-")
        filename = f"{slug} - Fitment Assessment.md"
    if not filename.endswith(".md"):
        filename += ".md"

    cleaned = "\n".join(line.rstrip() for line in content.splitlines())

    target = config.JOB_ASSESSMENTS_FOLDER / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(cleaned, encoding="utf-8")
    return f"\u2713 Saved job assessment: {target.name}"


def register(mcp) -> None:
    mcp.tool()(assess_job_fitment)
    mcp.tool()(get_customization_strategy)
    mcp.tool()(save_job_assessment)
