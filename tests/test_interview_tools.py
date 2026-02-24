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

    def test_get_existing_prep_file_finds_md_in_leetcode_folder(self, isolated_server):
        prep = srv.LEETCODE_FOLDER / "FANDUEL_INTERVIEW_PREP.md"
        prep.write_text("FanDuel LeetCode prep", encoding="utf-8")

        result = srv.get_existing_prep_file("fanduel")
        assert "FANDUEL_INTERVIEW_PREP.md" in result
        assert "FanDuel LeetCode prep" in result

    def test_get_existing_prep_file_finds_in_both_folders(self, isolated_server):
        # Same company with prep files in both folders — both should be returned
        (srv.RESUME_FOLDER / "ACME_INTERVIEW_PREP.md").write_text("resume-folder prep", encoding="utf-8")
        (srv.LEETCODE_FOLDER / "ACME_INTERVIEW_PREP.md").write_text("leetcode-folder prep", encoding="utf-8")

        result = srv.get_existing_prep_file("acme")
        assert "Found 2 prep file(s)" in result
        assert "resume-folder prep" in result
        assert "leetcode-folder prep" in result


class TestSaveInterviewPrep:
    def test_saves_to_leetcode_folder_default_filename(self, isolated_server):
        result = srv.save_interview_prep("FanDuel", "# FanDuel Prep\nBe ready.")
        assert "FANDUEL_INTERVIEW_PREP.md" in result
        saved = srv.LEETCODE_FOLDER / "FANDUEL_INTERVIEW_PREP.md"
        assert saved.exists()
        assert "# FanDuel Prep" in saved.read_text(encoding="utf-8")

    def test_saves_with_custom_filename(self, isolated_server):
        result = srv.save_interview_prep("Airbnb", "Airbnb content", filename="Airbnb_HM_Prep")
        assert "Airbnb_HM_Prep.md" in result
        saved = srv.LEETCODE_FOLDER / "Airbnb_HM_Prep.md"
        assert saved.exists()

    def test_appends_md_extension_if_missing(self, isolated_server):
        srv.save_interview_prep("Ford", "Ford content", filename="FORD_PREP")
        assert (srv.LEETCODE_FOLDER / "FORD_PREP.md").exists()

    def test_does_not_double_extension_if_present(self, isolated_server):
        srv.save_interview_prep("GM", "GM content", filename="GM_PREP.md")
        assert (srv.LEETCODE_FOLDER / "GM_PREP.md").exists()
        assert not (srv.LEETCODE_FOLDER / "GM_PREP.md.md").exists()

    def test_strips_trailing_whitespace(self, isolated_server):
        srv.save_interview_prep("Reddit", "line one   \nline two  \n", filename="REDDIT_PREP.md")
        content = (srv.LEETCODE_FOLDER / "REDDIT_PREP.md").read_text(encoding="utf-8")
        for line in content.splitlines():
            assert line == line.rstrip()

    def test_slug_handles_spaces_and_hyphens(self, isolated_server):
        srv.save_interview_prep("Mercedes-Benz", "content")
        assert (srv.LEETCODE_FOLDER / "MERCEDES_BENZ_INTERVIEW_PREP.md").exists()

    def test_overwrite_existing_file(self, isolated_server):
        srv.save_interview_prep("Netflix", "v1", filename="NETFLIX_PREP.md")
        srv.save_interview_prep("Netflix", "v2 updated", filename="NETFLIX_PREP.md")
        content = (srv.LEETCODE_FOLDER / "NETFLIX_PREP.md").read_text(encoding="utf-8")
        assert "v2 updated" in content
        assert "v1" not in content
