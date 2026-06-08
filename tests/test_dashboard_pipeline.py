"""Tests for the pipeline dashboard routes.

Target: transport/http/routes/dashboard/pipeline.py — the queue → assess →
resume-choice → cover-letter → apply board. This module shipped with zero
coverage; these tests lock in its HTTP contract and pure synthesis helpers.

Covers:
  - GET  /dashboard/pipeline               (page render)
  - GET  /dashboard/pipeline/data          (payload shape, ordering, derived fields)
  - POST /dashboard/pipeline/evaluate      (404 for missing job)
  - POST /dashboard/pipeline/select-resume (400 missing name / 404 / success)
  - POST /dashboard/pipeline/unqueue       (404 / success resets status)
    - POST /dashboard/pipeline/mark-applied  (success updates queue + application log)
  - POST /dashboard/pipeline/remove        (404 / success deletes row)
  - auth enforcement on the pipeline router
  - pure helpers: _recommend_resume, _normalize_fitment_context,
    _extract_md_section, _extract_bullets, _first_sentence
"""

import json

from lib import config
from lib.io import _load_json
from transport.http.routes.dashboard import pipeline as pl


# Seed helpers

def _seed_jobs(jobs: list[dict]) -> None:
    """Write a job_queue.json into the isolated data dir (post-reconfigure)."""
    config.JOB_QUEUE_FILE.write_text(
        json.dumps({"jobs": jobs}, indent=2), encoding="utf-8"
    )


def _job(**over) -> dict:
    base = {
        "id": 1,
        "company": "Stripe",
        "role": "Staff Engineer",
        "jd": "Build payments infrastructure with Python and distributed systems.",
        "source": "linkedin",
        "status": "pending",
        "added_date": "2026-06-01 10:00",
        "fitment_score": None,
        "decision_notes": None,
        "selected_resume": "",
    }
    base.update(over)
    return base


# Page render

class TestPipelinePage:
    def test_pipeline_page_renders(self, http_client_noauth):
        r = http_client_noauth.get("/dashboard/pipeline")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        # Board scaffolding + client script markers.
        assert "id='list'" in r.text or 'id="list"' in r.text
        assert "/dashboard/pipeline/evaluate" in r.text


# /pipeline/data

class TestPipelineData:
    def test_empty_queue_shape(self, http_client_noauth):
        _seed_jobs([])
        r = http_client_noauth.get("/dashboard/pipeline/data")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["jobs"] == []
        # Resume options fall back to the two locked PDF names when no latex dir.
        assert isinstance(body["resume_options"], list)
        assert len(body["resume_options"]) == 2

    def test_jobs_sorted_newest_first(self, http_client_noauth):
        _seed_jobs([
            _job(id=1, company="Older", added_date="2026-05-01 09:00"),
            _job(id=2, company="Newer", added_date="2026-06-02 09:00"),
        ])
        r = http_client_noauth.get("/dashboard/pipeline/data")
        body = r.json()
        assert body["total"] == 2
        assert [j["company"] for j in body["jobs"]] == ["Newer", "Older"]

    def test_derived_fields_present(self, http_client_noauth):
        _seed_jobs([_job(id=7, status="pending")])
        body = http_client_noauth.get("/dashboard/pipeline/data").json()
        job = body["jobs"][0]
        for key in (
            "id", "company", "role", "status", "assessed",
            "assessment_summary", "assessment_detail",
            "recommended_resume", "selected_resume",
        ):
            assert key in job
        # A pending job is not yet assessed.
        assert job["assessed"] is False
        assert job["status"] == "pending"

    def test_evaluated_job_marked_assessed(self, http_client_noauth):
        _seed_jobs([_job(id=3, status="evaluated")])
        body = http_client_noauth.get("/dashboard/pipeline/data").json()
        assert body["jobs"][0]["assessed"] is True

    def test_applied_job_marked_assessed(self, http_client_noauth):
        _seed_jobs([_job(id=4, status="applied")])
        body = http_client_noauth.get("/dashboard/pipeline/data").json()
        assert body["jobs"][0]["assessed"] is True

    def test_ai_role_recommends_modern_resume(self, http_client_noauth):
        _seed_jobs([_job(
            id=9,
            role="LLM / RAG Platform Engineer",
            jd="Build agentic AI systems with LLM orchestration and prompt tooling.",
        )])
        body = http_client_noauth.get("/dashboard/pipeline/data").json()
        assert "MODERN" in body["jobs"][0]["recommended_resume"].upper()

    def test_payload_includes_optimized_resume_options(self, http_client_noauth):
        opt_dir = config.RESUME_FOLDER / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized")
        opt_dir.mkdir(parents=True, exist_ok=True)
        (opt_dir / "Frank MacBride Resume - Stripe Staff Engineer.txt").write_text("resume", encoding="utf-8")
        _seed_jobs([_job(id=11, company="Stripe", role="Staff Engineer")])

        body = http_client_noauth.get("/dashboard/pipeline/data").json()

        assert "Frank MacBride Resume - Stripe Staff Engineer.txt" in body["optimized_resume_options"]
        assert body["jobs"][0]["suggested_edit_resume"] == "Frank MacBride Resume - Stripe Staff Engineer.txt"

    def test_payload_includes_cover_letter_options(self, http_client_noauth):
        cl_dir = config.RESUME_FOLDER / config._cfg.get("cover_letters_dir", "02-Cover-Letters")
        cl_dir.mkdir(parents=True, exist_ok=True)
        (cl_dir / "Frank MacBride Cover Letter - Stripe Staff Engineer.txt").write_text("letter", encoding="utf-8")
        _seed_jobs([_job(id=13, company="Stripe", role="Staff Engineer")])

        body = http_client_noauth.get("/dashboard/pipeline/data").json()

        assert "Frank MacBride Cover Letter - Stripe Staff Engineer.txt" in body["cover_letter_options"]
        assert body["jobs"][0]["suggested_edit_cover_letter"] == "Frank MacBride Cover Letter - Stripe Staff Engineer.txt"


# /pipeline/select-resume

class TestSelectResume:
    def test_missing_resume_name_returns_400(self, http_client_noauth):
        _seed_jobs([_job(id=1)])
        r = http_client_noauth.post(
            "/dashboard/pipeline/select-resume", json={"job_id": 1, "resume_name": ""}
        )
        assert r.status_code == 400

    def test_unknown_job_returns_404(self, http_client_noauth):
        _seed_jobs([_job(id=1)])
        r = http_client_noauth.post(
            "/dashboard/pipeline/select-resume",
            json={"job_id": 999, "resume_name": "Frank_MacBride_Resume.pdf"},
        )
        assert r.status_code == 404

    def test_select_persists_to_queue(self, http_client_noauth):
        _seed_jobs([_job(id=1, selected_resume="")])
        r = http_client_noauth.post(
            "/dashboard/pipeline/select-resume",
            json={"job_id": 1, "resume_name": "Frank_MacBride_Resume_MODERN.pdf"},
        )
        assert r.status_code == 200
        assert r.json()["selected_resume"] == "Frank_MacBride_Resume_MODERN.pdf"
        saved = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"][0]
        assert saved["selected_resume"] == "Frank_MacBride_Resume_MODERN.pdf"


class TestResumeEditDialog:
    def test_read_resume_returns_optimized_resume_text(self, http_client_noauth):
        opt_dir = config.RESUME_FOLDER / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized")
        opt_dir.mkdir(parents=True, exist_ok=True)
        (opt_dir / "base.txt").write_text("FRANK\nEXPERIENCE", encoding="utf-8")

        r = http_client_noauth.post("/dashboard/pipeline/read-resume", json={"resume_name": "base.txt"})

        assert r.status_code == 200
        assert r.json()["content"] == "FRANK\nEXPERIENCE"

    def test_edit_resume_saves_copy_and_updates_job(self, http_client_noauth, monkeypatch):
        opt_dir = config.RESUME_FOLDER / config._cfg.get("optimized_resumes_dir", "01-Current-Optimized")
        opt_dir.mkdir(parents=True, exist_ok=True)
        (opt_dir / "base.txt").write_text("FRANK\nOLD BULLET", encoding="utf-8")
        _seed_jobs([_job(id=12, company="Stripe", role="Staff Engineer")])

        class FakeMessage:
            content = "FRANK\nNEW BULLET"

        class FakeChoice:
            message = FakeMessage()

        class FakeUsage:
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15

        class FakeResponse:
            choices = [FakeChoice()]
            usage = FakeUsage()

        monkeypatch.setattr(pl.config, "get_llm_client", lambda: (object(), "gpt-test"))
        monkeypatch.setattr(pl, "create_chat_completion", lambda *a, **kw: FakeResponse())
        monkeypatch.setattr(pl, "export_resume_pdf", lambda filename: f"✓ PDF exported: {filename}.pdf")

        r = http_client_noauth.post(
            "/dashboard/pipeline/edit-resume",
            json={
                "job_id": 12,
                "resume_name": "base.txt",
                "instructions": "Replace old bullet with new bullet.",
                "output_filename": "edited-stripe.txt",
                "export_pdf": True,
            },
        )

        assert r.status_code == 200
        body = r.json()
        assert body["edited_resume"] == "edited-stripe.txt"
        assert (opt_dir / "edited-stripe.txt").read_text(encoding="utf-8") == "FRANK\nNEW BULLET"
        saved = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"][0]
        assert saved["last_edited_resume"] == "edited-stripe.txt"


class TestCoverLetterEditDialog:
    def test_read_cover_letter_returns_cover_letter_text(self, http_client_noauth):
        cl_dir = config.RESUME_FOLDER / config._cfg.get("cover_letters_dir", "02-Cover-Letters")
        cl_dir.mkdir(parents=True, exist_ok=True)
        (cl_dir / "base.txt").write_text("Dear Hiring Manager,\n\nHello.", encoding="utf-8")

        r = http_client_noauth.post(
            "/dashboard/pipeline/read-cover-letter",
            json={"cover_letter_name": "base.txt"},
        )

        assert r.status_code == 200
        assert r.json()["content"] == "Dear Hiring Manager,\n\nHello."

    def test_edit_cover_letter_saves_copy_and_exports_latex(self, http_client_noauth, monkeypatch):
        cl_dir = config.RESUME_FOLDER / config._cfg.get("cover_letters_dir", "02-Cover-Letters")
        cl_dir.mkdir(parents=True, exist_ok=True)
        (cl_dir / "base.txt").write_text("Dear Hiring Manager,\n\nOld body.", encoding="utf-8")
        _seed_jobs([_job(id=14, company="Stripe", role="Staff Engineer")])

        class FakeMessage:
            content = "Dear Hiring Manager,\n\nNew body."

        class FakeChoice:
            message = FakeMessage()

        class FakeUsage:
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15

        class FakeResponse:
            choices = [FakeChoice()]
            usage = FakeUsage()

        called = {}
        monkeypatch.setattr(pl.config, "get_llm_client", lambda: (object(), "gpt-test"))
        monkeypatch.setattr(pl, "create_chat_completion", lambda *a, **kw: FakeResponse())
        monkeypatch.setattr(
            pl,
            "generate_cover_letter_latex",
            lambda **kw: called.setdefault("latex", config.RESUME_FOLDER / "09-Cover-Letter-PDFs" / "edited.pdf"),
        )

        r = http_client_noauth.post(
            "/dashboard/pipeline/edit-cover-letter",
            json={
                "job_id": 14,
                "cover_letter_name": "base.txt",
                "instructions": "Replace old body with new body.",
                "output_filename": "edited-stripe.txt",
                "export_pdf": True,
                "export_pipeline": "latex",
            },
        )

        assert r.status_code == 200
        body = r.json()
        assert body["edited_cover_letter"] == "base.edit1.tmp"
        assert body["draft_name"] == "base.edit1.tmp"
        assert body["draft_href"] == "/dashboard/pipeline/cover-letter-draft/base.edit1.tmp"
        assert body["export_pipeline"] == "latex"
        assert "09-Cover-Letter-PDFs" in body["pdf_result"]
        assert body["pdf_href"] == "/dashboard/materials/file/cover_letter_pdfs/edited.pdf"
        assert called["latex"].name == "edited.pdf"
        assert (cl_dir / "base.txt").read_text(encoding="utf-8") == "Dear Hiring Manager,\n\nOld body."
        assert (cl_dir / "base.edit1.tmp").read_text(encoding="utf-8") == "Dear Hiring Manager,\n\nNew body."
        saved = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"][0]
        assert saved["last_edited_cover_letter"] == "base.txt"

        draft_page = http_client_noauth.get("/dashboard/pipeline/cover-letter-draft/base.edit1.tmp")
        assert draft_page.status_code == 200
        assert "New body" in draft_page.text

    def test_edit_cover_letter_can_export_html(self, http_client_noauth, monkeypatch):
        cl_dir = config.RESUME_FOLDER / config._cfg.get("cover_letters_dir", "02-Cover-Letters")
        cl_dir.mkdir(parents=True, exist_ok=True)
        (cl_dir / "base.txt").write_text("Dear Hiring Manager,\n\nOld body.", encoding="utf-8")
        _seed_jobs([_job(id=15, company="Stripe", role="Staff Engineer")])

        class FakeMessage:
            content = "Dear Hiring Manager,\n\nNew HTML body."

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]
            usage = None

        monkeypatch.setattr(pl.config, "get_llm_client", lambda: (object(), "gpt-test"))
        monkeypatch.setattr(pl, "create_chat_completion", lambda *a, **kw: FakeResponse())
        monkeypatch.setattr(
            pl,
            "export_cover_letter_pdf",
            lambda filename, **kw: f"✓ PDF exported: {config.RESUME_FOLDER / '09-Cover-Letter-PDFs' / kw['output_filename']}",
        )

        r = http_client_noauth.post(
            "/dashboard/pipeline/edit-cover-letter",
            json={
                "job_id": 15,
                "cover_letter_name": "base.txt",
                "instructions": "Make it HTML exportable.",
                "output_filename": "edited-html.txt",
                "export_pdf": True,
                "export_pipeline": "html",
            },
        )

        assert r.status_code == 200
        assert r.json()["export_pipeline"] == "html"
        assert "09-Cover-Letter-PDFs" in r.json()["pdf_result"]
        assert r.json()["draft_name"] == "base.edit1.tmp"
        assert r.json()["pdf_href"] == "/dashboard/materials/file/cover_letter_pdfs/base.edit1.pdf"

    def test_accept_cover_letter_promotes_latest_draft_and_cleans_up(self, http_client_noauth):
        cl_dir = config.RESUME_FOLDER / config._cfg.get("cover_letters_dir", "02-Cover-Letters")
        cl_dir.mkdir(parents=True, exist_ok=True)
        (cl_dir / "base.txt").write_text("original", encoding="utf-8")
        (cl_dir / "base.edit1.tmp").write_text("draft 1", encoding="utf-8")
        (cl_dir / "base.edit2.tmp").write_text("draft 2", encoding="utf-8")

        r = http_client_noauth.post(
            "/dashboard/pipeline/accept-cover-letter-edit",
            json={"cover_letter_name": "base.txt", "draft_name": "base.edit2.tmp"},
        )

        assert r.status_code == 200
        body = r.json()
        assert body["backup_name"] == "base.txt.bak"
        assert body["deleted_drafts"] == 2
        assert (cl_dir / "base.txt").read_text(encoding="utf-8") == "draft 2"
        assert (cl_dir / "base.txt.bak").read_text(encoding="utf-8") == "original"
        assert not (cl_dir / "base.edit1.tmp").exists()
        assert not (cl_dir / "base.edit2.tmp").exists()

    def test_cancel_cover_letter_edit_removes_drafts_without_touching_original(self, http_client_noauth):
        cl_dir = config.RESUME_FOLDER / config._cfg.get("cover_letters_dir", "02-Cover-Letters")
        cl_dir.mkdir(parents=True, exist_ok=True)
        (cl_dir / "base.txt").write_text("original", encoding="utf-8")
        (cl_dir / "base.edit1.tmp").write_text("draft 1", encoding="utf-8")
        (cl_dir / "base.edit2.tmp").write_text("draft 2", encoding="utf-8")

        r = http_client_noauth.post(
            "/dashboard/pipeline/cancel-cover-letter-edit",
            json={"cover_letter_name": "base.txt"},
        )

        assert r.status_code == 200
        assert r.json()["deleted_drafts"] == 2
        assert (cl_dir / "base.txt").read_text(encoding="utf-8") == "original"
        assert not (cl_dir / "base.txt.bak").exists()
        assert not (cl_dir / "base.edit1.tmp").exists()
        assert not (cl_dir / "base.edit2.tmp").exists()

    def test_subsequent_cover_letter_edit_uses_latest_draft(self, http_client_noauth, monkeypatch):
        cl_dir = config.RESUME_FOLDER / config._cfg.get("cover_letters_dir", "02-Cover-Letters")
        cl_dir.mkdir(parents=True, exist_ok=True)
        (cl_dir / "base.txt").write_text("original", encoding="utf-8")
        (cl_dir / "base.edit1.tmp").write_text("draft 1", encoding="utf-8")
        _seed_jobs([_job(id=16, company="Stripe", role="Staff Engineer")])

        captured = {}

        class FakeMessage:
            content = "draft 2"

        class FakeChoice:
            message = FakeMessage()

        class FakeResponse:
            choices = [FakeChoice()]
            usage = None

        def fake_chat(*args, **kwargs):
            captured["prompt"] = kwargs["messages"][1]["content"]
            return FakeResponse()

        monkeypatch.setattr(pl.config, "get_llm_client", lambda: (object(), "gpt-test"))
        monkeypatch.setattr(pl, "create_chat_completion", fake_chat)

        r = http_client_noauth.post(
            "/dashboard/pipeline/edit-cover-letter",
            json={
                "job_id": 16,
                "cover_letter_name": "base.txt",
                "draft_name": "base.edit1.tmp",
                "instructions": "Second pass.",
                "export_pdf": False,
            },
        )

        assert r.status_code == 200
        assert r.json()["draft_name"] == "base.edit2.tmp"
        assert "CURRENT COVER LETTER TEXT:\ndraft 1" in captured["prompt"]
        assert (cl_dir / "base.txt").read_text(encoding="utf-8") == "original"
        assert (cl_dir / "base.edit2.tmp").read_text(encoding="utf-8") == "draft 2"


# ──────────────────────────────────────────────────────────────────────────────
# /pipeline/unqueue + /pipeline/remove
# ──────────────────────────────────────────────────────────────────────────────

class TestUnqueueAndRemove:
    def test_unqueue_resets_status_to_pending(self, http_client_noauth):
        _seed_jobs([_job(id=1, status="added", fitment_score="8/10",
                         decision_notes="queued")])
        r = http_client_noauth.post("/dashboard/pipeline/unqueue", json={"job_id": 1})
        assert r.status_code == 200
        assert r.json()["status"] == "pending"
        saved = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"][0]
        assert saved["status"] == "pending"
        assert saved["fitment_score"] is None
        assert saved["decision_notes"] is None

    def test_unqueue_unknown_job_returns_404(self, http_client_noauth):
        _seed_jobs([_job(id=1)])
        r = http_client_noauth.post("/dashboard/pipeline/unqueue", json={"job_id": 42})
        assert r.status_code == 404

    def test_mark_applied_updates_queue_and_application(self, http_client_noauth):
        _seed_jobs([_job(id=1, status="added", company="Afresh", role="Engineer")])
        r = http_client_noauth.post(
            "/dashboard/pipeline/mark-applied",
            json={"job_id": 1, "notes": "Submitted manually."},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "applied"
        saved = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"][0]
        assert saved["status"] == "applied"
        assert saved["decision_notes"] == "Submitted manually."

        status_data = _load_json(config.STATUS_FILE, {"applications": []})
        app = status_data["applications"][0]
        assert app["company"] == "Afresh"
        assert app["role"] == "Engineer"
        assert app["status"] == "applied"
        assert app["events"][-1]["type"] == "applied"

    def test_mark_applied_unknown_job_returns_404(self, http_client_noauth):
        _seed_jobs([_job(id=1)])
        r = http_client_noauth.post("/dashboard/pipeline/mark-applied", json={"job_id": 42})
        assert r.status_code == 404

    def test_remove_deletes_row(self, http_client_noauth):
        _seed_jobs([_job(id=1), _job(id=2, company="Keep")])
        r = http_client_noauth.post("/dashboard/pipeline/remove", json={"job_id": 1})
        assert r.status_code == 200
        assert r.json()["removed_job_id"] == 1
        remaining = _load_json(config.JOB_QUEUE_FILE, {"jobs": []})["jobs"]
        assert [j["id"] for j in remaining] == [2]

    def test_remove_unknown_job_returns_404(self, http_client_noauth):
        _seed_jobs([_job(id=1)])
        r = http_client_noauth.post("/dashboard/pipeline/remove", json={"job_id": 999})
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# /pipeline/evaluate — 404 path (success path hits the LLM service; covered by
# JobAnalysisService tests). Here we only assert the not-found contract.
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateNotFound:
    def test_evaluate_unknown_job_returns_404(self, http_client_noauth):
        _seed_jobs([_job(id=1)])
        r = http_client_noauth.post("/dashboard/pipeline/evaluate", json={"job_id": 5})
        assert r.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Request validation
# ──────────────────────────────────────────────────────────────────────────────

class TestPipelineValidation:
    def test_job_id_must_be_positive(self, http_client_noauth):
        r = http_client_noauth.post("/dashboard/pipeline/unqueue", json={"job_id": 0})
        assert r.status_code == 422

    def test_export_pipeline_enum_enforced(self, http_client_noauth):
        _seed_jobs([_job(id=1)])
        r = http_client_noauth.post(
            "/dashboard/pipeline/select-resume",
            json={"job_id": 1, "resume_name": "x.pdf", "export_pipeline": "docx"},
        )
        assert r.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# Auth enforcement (pipeline router depends on require_api_key)
# ──────────────────────────────────────────────────────────────────────────────

class TestPipelineAuth:
    def test_pipeline_data_requires_auth_when_enabled(self, http_client_authed):
        r = http_client_authed.get("/dashboard/pipeline/data")
        assert r.status_code == 401

    def test_pipeline_data_accepts_bearer(self, http_client_authed):
        r = http_client_authed.get(
            "/dashboard/pipeline/data",
            headers={"Authorization": "Bearer test-key"},
        )
        assert r.status_code == 200

    def test_pipeline_data_accepts_session_cookie(self, http_client_authed):
        http_client_authed.cookies.set("jc_session", "test-key")
        r = http_client_authed.get("/dashboard/pipeline/data")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# Pure helpers — no server fixture needed
# ──────────────────────────────────────────────────────────────────────────────

class TestPipelineHelpers:
    def test_recommend_resume_empty_options(self):
        assert pl._recommend_resume("Engineer", "jd", []) == "Generate new resume"

    def test_recommend_resume_ai_picks_modern(self):
        opts = ["Frank_MacBride_Resume.pdf", "Frank_MacBride_Resume_MODERN.pdf"]
        out = pl._recommend_resume("AI Engineer", "llm rag agents", opts)
        assert "modern" in out.lower()

    def test_recommend_resume_non_ai_picks_classic(self):
        opts = ["Frank_MacBride_Resume.pdf", "Frank_MacBride_Resume_MODERN.pdf"]
        out = pl._recommend_resume("Backend Engineer", "python apis databases", opts)
        assert out == "Frank_MacBride_Resume.pdf"

    def test_normalize_fitment_context_strips_wrapper(self):
        raw = "✓ Assessment complete\ntokens: 100\n## FITMENT SCORE\n8/10"
        out = pl._normalize_fitment_context(raw)
        assert out.startswith("## FITMENT SCORE")
        assert "Assessment complete" not in out

    def test_normalize_fitment_context_no_marker_passthrough(self):
        assert pl._normalize_fitment_context("  plain text  ") == "plain text"

    def test_extract_md_section(self):
        md = "## FITMENT SCORE\n8/10\n\n## RECOMMENDATION\nApply aggressively."
        assert pl._extract_md_section(md, "FITMENT SCORE") == "8/10"
        assert pl._extract_md_section(md, "RECOMMENDATION") == "Apply aggressively."

    def test_extract_bullets_respects_limit(self):
        section = "- alpha\n- beta\n- gamma"
        assert pl._extract_bullets(section, limit=2) == ["alpha", "beta"]

    def test_first_sentence(self):
        assert pl._first_sentence("Hello world. Next thing.") == "Hello world."

    def test_first_sentence_truncates(self):
        out = pl._first_sentence("x" * 500, max_len=32)
        assert len(out) <= 32
