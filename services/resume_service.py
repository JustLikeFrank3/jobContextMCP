"""
ResumeService: multi-step orchestration for tailored resume + cover letter
generation, save, and PDF export.

Wraps the existing tool functions (tools.generate, tools.resume, tools.export)
and emits ProgressEvent markers around each step. The underlying tools already
handle OpenAI calls, file saving, and PDF rendering; this service composes
them into a single named-stage pipeline for SSE streaming.

For single-step calls (just generate context, just export an existing .txt),
callers should import the tool functions directly — no service needed.
"""

from dataclasses import dataclass
from typing import Optional

from services.events import ProgressCallback, _emit
from tools import generate as _generate
from tools import export as _export


@dataclass
class ResumeResult:
    """Structured result of a ResumeService.generate call.

    Attributes:
        success:        True if the LLM call and (if requested) PDF export both
                        produced files. False if any step returned an error
                        string instead of completing.
        company:        Company name passed in.
        role:           Role title passed in.
        kind:           "resume" or "cover_letter".
        content:        Raw text returned by the underlying generate tool. For
                        keyless config this is the context package; for keyed
                        config this is the confirmation summary including the
                        save and export paths embedded in the message.
        pdf_exported:   True if a PDF export step ran and produced a file.
        notes:          Any non-fatal warnings collected during orchestration.
        provenance:     The one-line provenance verdict emitted by the truth
                        gate (lib.provenance.format_provenance_line), split
                        out of `content` so clients can render it as its own
                        element. None when no gate line is present (keyless
                        context-package path).
    """
    success: bool
    company: str
    role: str
    kind: str
    content: str
    pdf_exported: bool = False
    notes: Optional[list[str]] = None
    provenance: Optional[str] = None

    def __post_init__(self):
        if self.notes is None:
            self.notes = []


def _extract_provenance_line(content: str) -> Optional[str]:
    """Pull the gate's one-line verdict out of a confirmation string."""
    for line in (content or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Provenance:"):
            return stripped
    return None


class ResumeService:
    """Orchestrates resume and cover letter generation pipelines."""

    @staticmethod
    def generate(
        company: str,
        role: str,
        job_description: str,
        output_filename: str = "",
        kind: str = "resume",
        export_pipeline: str = "html",
        persona: Optional[str] = None,
        selected_resume: Optional[str] = None,
        resume_template: str = "",
        resume_style: str = "navy",
        cl_template: str = "",
        cl_style: str = "navy",
        on_progress: Optional[ProgressCallback] = None,
    ) -> ResumeResult:
        """Generate a tailored resume or cover letter end-to-end.

        Stages emitted:
            "starting"   — service begins, includes company/role/kind
            "generating" — about to call the underlying generate tool
            "complete"   — pipeline finished, includes content summary

        The underlying generate tool either calls OpenAI directly (saving the
        .txt and exporting the PDF inline) or returns a context package for an
        AI client to complete the work. In both cases this service emits the
        same named stages so SSE consumers see a consistent event stream.

        Args:
            company:         Target company name.
            role:            Target role title.
            job_description: Full JD text.
            output_filename: Optional explicit filename (default: auto-derived).
            kind:            "resume" or "cover_letter".
            selected_resume: Filename of the resume chosen for this job. When it
                             names the MODERN/AI variant the cover-letter header
                             title becomes "AI Full Stack Software Engineer";
                             otherwise it stays "Full Stack Software Engineer".
            on_progress:     Optional callback for streaming progress events.

        Returns:
            ResumeResult with content and success flag.
        """
        if kind not in ("resume", "cover_letter"):
            raise ValueError(f"kind must be 'resume' or 'cover_letter', got {kind!r}")

        # Resolve persona up-front so an invalid name fails fast before any
        # generation work happens. None → "default".
        from services.persona_service import PersonaService
        persona_cfg = PersonaService.get(persona)

        _emit(on_progress, "starting", f"Starting {kind} generation for {role} @ {company}",
              {"company": company, "role": role, "kind": kind, "persona": persona_cfg.name, "export_pipeline": export_pipeline})

        _emit(on_progress, "generating", f"Calling generate tool for {kind}")

        # Persona is appended to the JD as a prompt-bias block. The underlying
        # generate tool concatenates JD into its prompt, so this is the lowest-
        # touch wiring point that works for both keyed and keyless paths.
        jd_with_persona = (
            job_description
            + "\n\n---\n"
            + persona_cfg.to_prompt_block()
        )

        if kind == "resume":
            content = _generate.generate_resume(company, role, jd_with_persona, output_filename, template=resume_template, style=resume_style)
        else:
            # The cover-letter header title tracks the assessment's resume
            # recommendation: the MODERN/AI resume variant earns the "AI"
            # prefix; the generic resume keeps the plain title.
            role_title = (
                "AI Full Stack Software Engineer"
                if selected_resume and "modern" in selected_resume.lower()
                else "Full Stack Software Engineer"
            )
            content = _generate.generate_cover_letter(
                company,
                role,
                jd_with_persona,
                output_filename,
                export_pipeline=export_pipeline,
                role_title=role_title,
                cl_template=cl_template,
                cl_style=cl_style,
            )

        # The tool returns a "✓ ..." confirmation string when it ran the full
        # OpenAI + save + export pipeline; otherwise it returns a context
        # package starting with formatting instructions.
        success = content.startswith("✓")
        pdf_exported = "PDF exported" in content or "PDF saved" in content

        notes = []
        if "⚠" in content:
            notes.append("PDF export warning detected in tool output")

        _emit(on_progress, "complete",
              f"{kind} generation finished" + (" (full pipeline)" if success else " (context package only)"),
              {"success": success, "pdf_exported": pdf_exported})

        return ResumeResult(
            success=success,
            company=company,
            role=role,
            kind=kind,
            content=content,
            pdf_exported=pdf_exported,
            notes=notes,
            provenance=_extract_provenance_line(content),
        )

    @staticmethod
    def export_existing(
        filename: str,
        kind: str = "resume",
        resume_template: str = "",
        resume_style: str = "navy",
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        """Export an already-saved .txt file to PDF.

        Use this when a caller has already written a .txt (e.g. via the keyless
        context-package flow) and now wants the PDF rendered.

        Args:
            filename:        The .txt filename in the appropriate folder.
            kind:            "resume" or "cover_letter".
            resume_template: Visual layout template (for resumes only).
            resume_style:    Color theme (for resumes only).
            on_progress:     Optional progress callback.

        Returns:
            The result string from the underlying export tool.
        """
        if kind not in ("resume", "cover_letter"):
            raise ValueError(f"kind must be 'resume' or 'cover_letter', got {kind!r}")

        _emit(on_progress, "exporting", f"Exporting {kind} {filename} to PDF")

        if kind == "resume":
            result = _export.export_resume_pdf(filename, template=resume_template, style=resume_style or "navy")
        else:
            result = _export.export_cover_letter_pdf(filename, template=resume_template, style=resume_style or "navy")

        _emit(on_progress, "complete", f"{kind} PDF export finished")
        return result
