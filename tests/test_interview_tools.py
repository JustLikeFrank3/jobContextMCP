"""
Tests for interview and prep tools.
"""

from pathlib import Path

import server as srv


class TestInterviewTools:
    def test_get_interview_quick_reference_reads_file(self, isolated_server):
        result = srv.get_interview_quick_reference()
        assert "[TEST QUICK REFERENCE]" in result

    def test_get_leetcode_cheatsheet_full(self, isolated_server):
        result = srv.get_leetcode_cheatsheet()
        assert "[TEST CHEATSHEET]" in result

    def test_get_leetcode_cheatsheet_section_found(self, isolated_server):
        srv.LEETCODE_CHEATSHEET.write_text(
            "# Arrays\nTwo pointers\n## Notes\nA\n# Trees\nDFS\n",
            encoding="utf-8",
        )
        result = srv.get_leetcode_cheatsheet("arrays")
        assert "Two pointers" in result
        assert "# Arrays" in result

    def test_get_leetcode_cheatsheet_section_not_found_fallback(self, isolated_server):
        srv.LEETCODE_CHEATSHEET.write_text("# Graphs\nBFS\n", encoding="utf-8")
        result = srv.get_leetcode_cheatsheet("dp")
        assert "Section 'dp' not found" in result
        assert "# Graphs" in result

    def test_generate_interview_prep_context_includes_core_fields(self, isolated_server):
        result = srv.generate_interview_prep_context(
            company="Microsoft",
            role="Software Engineer",
            stage="phone_screen",
            job_description="Build scalable backend services",
        )
        assert "Company: Microsoft" in result
        assert "Role:    Software Engineer" in result
        assert "Stage:   phone_screen" in result
        assert "Build scalable backend services" in result
        assert "[TEST MASTER RESUME]" in result
        assert "[TEST QUICK REFERENCE]" in result

    def test_generate_interview_prep_context_without_jd(self, isolated_server):
        result = srv.generate_interview_prep_context(
            company="Ford",
            role="SE",
            stage="onsite",
        )
        assert "Company: Ford" in result
        assert "Stage:   onsite" in result

    def test_get_existing_prep_file_no_match(self, isolated_server):
        result = srv.get_existing_prep_file("NonexistentCo")
        assert "No existing prep files found" in result

    def test_get_existing_prep_file_finds_txt(self, isolated_server, tmp_path):
        prep = srv.RESUME_FOLDER / "FanDuel Senior Software Engineer - Interview Prep.txt"
        prep.write_text("FanDuel prep content", encoding="utf-8")
        result = srv.get_existing_prep_file("FanDuel")
        assert "Found 1 prep file" in result
        assert "FanDuel prep content" in result

    def test_get_existing_prep_file_finds_md_recursive(self, isolated_server):
        nested = srv.RESUME_FOLDER / "nested" / "MICROSOFT_INTERVIEW_PREP.md"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_text("MS prep", encoding="utf-8")

        result = srv.get_existing_prep_file("microsoft")
        assert "MICROSOFT_INTERVIEW_PREP.md" in result
        assert "MS prep" in result

    def test_get_existing_prep_file_ignores_non_prep_names(self, isolated_server):
        f = srv.RESUME_FOLDER / "Microsoft Notes.txt"
        f.write_text("not a prep file by naming rules", encoding="utf-8")

        result = srv.get_existing_prep_file("Microsoft")
        assert "No existing prep files found" in result
