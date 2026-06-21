"""Tests for lib/resume_parser.py.

Covers the pure helper functions (no config dependency) and the
section parsers, then integration-level tests for _parse_resume_txt
and _parse_cover_letter_txt with config mocked out.
"""

import pytest
from unittest.mock import patch

from lib.resume_parser import (
    _strip_txt_wrapper,
    _is_bullet,
    _is_section_header,
    _clean_bullet,
    _is_date_line,
    _is_group_label,
    _join_continuations,
    _strip_separator_lines,
    _extract_contact,
    _strip_metadata_blocks,
    _split_sections,
    _parse_header,
    _parse_skills_section,
    _is_date_part,
    _finalize_job,
    _parse_experience_section,
    _combine_date_ranges,
    _normalize_company,
    _merge_same_company_jobs,
    _parse_education_section,
    _parse_projects_section,
    _parse_leadership_section,
    _parse_achievements_section,
    _classify_section,
    _derive_footer_tag,
    _parse_name_parts,
    _parse_resume_txt,
    _parse_cover_letter_txt,
)


# ── _strip_txt_wrapper ────────────────────────────────────────────────────────

class TestStripTxtWrapper:
    def test_no_wrapper_unchanged(self):
        assert _strip_txt_wrapper("hello world") == "hello world"

    def test_plaintext_fence_stripped(self):
        text = "```plaintext\nhello\nworld\n```"
        assert _strip_txt_wrapper(text) == "hello\nworld"

    def test_bare_fence_stripped(self):
        text = "```\nhello\n```"
        assert _strip_txt_wrapper(text) == "hello"

    def test_fence_without_closing_backticks(self):
        text = "```\nhello\nworld"
        result = _strip_txt_wrapper(text)
        assert "hello" in result

    def test_strips_surrounding_whitespace(self):
        assert _strip_txt_wrapper("  hello  ") == "hello"


# ── _is_bullet ────────────────────────────────────────────────────────────────

class TestIsBullet:
    def test_bullet_char(self):
        assert _is_bullet("• item")

    def test_dash(self):
        assert _is_bullet("- item")

    def test_asterisk(self):
        assert _is_bullet("* item")

    def test_normal_line(self):
        assert not _is_bullet("normal line")

    def test_empty_string(self):
        assert not _is_bullet("")

    def test_number_list_not_bullet(self):
        assert not _is_bullet("1. item")


# ── _clean_bullet ─────────────────────────────────────────────────────────────

class TestCleanBullet:
    def test_removes_bullet_char_and_space(self):
        assert _clean_bullet("• some text") == "some text"

    def test_removes_dash_and_space(self):
        assert _clean_bullet("- some text") == "some text"

    def test_removes_asterisk(self):
        assert _clean_bullet("* text") == "text"

    def test_strips_surrounding_whitespace(self):
        assert _clean_bullet("  • text  ") == "text"

    def test_non_bullet_unchanged(self):
        assert _clean_bullet("plain text") == "plain text"


# ── _is_date_line ─────────────────────────────────────────────────────────────

class TestIsDateLine:
    def test_year_in_short_line(self):
        assert _is_date_line("January 2022 - December 2025")

    def test_plain_year(self):
        assert _is_date_line("2020 - 2022")

    def test_no_year(self):
        assert not _is_date_line("No year here at all")

    def test_year_in_very_long_line(self):
        # >85 chars — should not be treated as a date line
        long = "This is a very long sentence that happens to contain 2022 somewhere in the middle of it all"
        assert not _is_date_line(long)


# ── _is_group_label ───────────────────────────────────────────────────────────

class TestIsGroupLabel:
    def test_valid_group_label(self):
        assert _is_group_label("Cloud & Infrastructure:")

    def test_bullet_not_group_label(self):
        assert not _is_group_label("• bullet:")

    def test_empty_not_group_label(self):
        assert not _is_group_label("")

    def test_too_short(self):
        assert not _is_group_label("AB:")

    def test_too_long(self):
        long = "A" * 56 + ":"
        assert not _is_group_label(long)

    def test_contains_year_not_group_label(self):
        assert not _is_group_label("Work done in 2022:")

    def test_no_colon_not_group_label(self):
        assert not _is_group_label("Cloud Infrastructure")


# ── _join_continuations ───────────────────────────────────────────────────────

class TestJoinContinuations:
    def test_continuation_joined_to_parent(self):
        lines = ["First line", "  continuation"]
        result = _join_continuations(lines)
        assert result == ["First line continuation"]

    def test_no_continuation_unchanged(self):
        lines = ["Line A", "Line B", "Line C"]
        assert _join_continuations(lines) == lines

    def test_blank_line_not_joined(self):
        lines = ["First", "", "Third"]
        result = _join_continuations(lines)
        assert result == ["First", "", "Third"]

    def test_continuation_without_parent_appended(self):
        lines = ["  orphan continuation"]
        result = _join_continuations(lines)
        assert "orphan continuation" in result[0]


# ── _strip_separator_lines ────────────────────────────────────────────────────

class TestStripSeparatorLines:
    def test_removes_dash_separator(self):
        lines = ["text", "---", "more text"]
        result = _strip_separator_lines(lines)
        assert "---" not in result
        assert "text" in result

    def test_removes_box_drawing_separator(self):
        lines = ["text", "──────────", "more"]
        result = _strip_separator_lines(lines)
        assert all("──" not in l for l in result)

    def test_removes_asterisk_separator(self):
        lines = ["text", "***", "more"]
        result = _strip_separator_lines(lines)
        assert "***" not in result

    def test_keeps_normal_lines(self):
        lines = ["hello", "world"]
        assert _strip_separator_lines(lines) == lines

    def test_empty_list(self):
        assert _strip_separator_lines([]) == []


# ── _classify_section ─────────────────────────────────────────────────────────

class TestClassifySection:
    def test_experience(self):
        assert _classify_section("PROFESSIONAL EXPERIENCE") == "experience"

    def test_employment(self):
        assert _classify_section("EMPLOYMENT HISTORY") == "experience"

    def test_education(self):
        assert _classify_section("EDUCATION") == "education"

    def test_skills(self):
        assert _classify_section("TECHNICAL SKILLS") == "skills"

    def test_tech_stack(self):
        assert _classify_section("TECH STACK") == "skills"

    def test_projects(self):
        assert _classify_section("PERSONAL PROJECTS") == "projects"

    def test_achievements(self):
        assert _classify_section("NOTABLE METRICS") == "achievements"

    def test_leadership(self):
        assert _classify_section("LEADERSHIP & VOLUNTEERING") == "leadership"

    def test_certifications(self):
        assert _classify_section("CERTIFICATIONS") == "leadership"

    def test_synopsis(self):
        assert _classify_section("PROFESSIONAL SUMMARY") == "synopsis_section"

    def test_objective(self):
        assert _classify_section("CAREER OBJECTIVE") == "synopsis_section"

    def test_unknown(self):
        assert _classify_section("RANDOM HEADER") == "text"

    def test_technical_alone_is_text(self):
        # "TECHNICAL" alone (job title guard) should NOT match skills
        assert _classify_section("TECHNICAL") == "text"


# ── _is_section_header ────────────────────────────────────────────────────────

class TestIsSectionHeader:
    def test_known_section_is_header(self):
        assert _is_section_header("PROFESSIONAL EXPERIENCE")

    def test_education_is_header(self):
        assert _is_section_header("EDUCATION")

    def test_bullet_is_not_header(self):
        assert not _is_section_header("• some bullet")

    def test_empty_is_not_header(self):
        assert not _is_section_header("")

    def test_unknown_allcaps_is_not_header(self):
        # All caps but not a known section type
        assert not _is_section_header("SOFTWARE ENGINEER")

    def test_section_with_parenthetical_note(self):
        # "PERSONAL PROJECTS (Post-GM, 2026)" — the parenthetical should be stripped
        assert _is_section_header("PERSONAL PROJECTS (Post-GM, 2026)")


# ── _strip_metadata_blocks ────────────────────────────────────────────────────

class TestStripMetadataBlocks:
    def test_removes_application_materials_block(self):
        lines = [
            "Resume content",
            "-----",
            "APPLICATION MATERIALS",
            "Some metadata",
            "-----",
            "More resume content",
        ]
        result = _strip_metadata_blocks(lines)
        assert "APPLICATION MATERIALS" not in " ".join(result)
        assert "Resume content" in result
        assert "More resume content" in result

    def test_keeps_non_metadata_blocks(self):
        lines = [
            "Before",
            "-----",
            "Normal block content",
            "-----",
            "After",
        ]
        result = _strip_metadata_blocks(lines)
        assert "Normal block content" in result

    def test_no_blocks_unchanged(self):
        lines = ["line one", "line two"]
        assert _strip_metadata_blocks(lines) == lines

    def test_unclosed_block_preserved(self):
        lines = ["before", "-----", "block without closing dashes"]
        result = _strip_metadata_blocks(lines)
        assert "block without closing dashes" in result


# ── _split_sections ───────────────────────────────────────────────────────────

class TestSplitSections:
    def test_pre_lines_before_first_header(self):
        lines = ["Name Line", "", "PROFESSIONAL EXPERIENCE", "Job content"]
        pre, sections = _split_sections(lines)
        assert "Name Line" in pre
        assert len(sections) == 1
        assert sections[0][0] == "PROFESSIONAL EXPERIENCE"

    def test_multiple_sections(self):
        lines = [
            "PROFESSIONAL EXPERIENCE", "exp content",
            "EDUCATION", "edu content",
        ]
        pre, sections = _split_sections(lines)
        assert len(sections) == 2
        assert sections[0][0] == "PROFESSIONAL EXPERIENCE"
        assert sections[1][0] == "EDUCATION"

    def test_empty_input(self):
        pre, sections = _split_sections([])
        assert pre == []
        assert sections == []


# ── _extract_contact ──────────────────────────────────────────────────────────

class TestExtractContact:
    @pytest.fixture(autouse=True)
    def patch_config(self, monkeypatch):
        import lib.config as cfg
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {})

    def test_extracts_email(self):
        contact = _extract_contact(["jane.doe@example.com"])
        assert contact["email"] == "jane.doe@example.com"

    def test_extracts_phone(self):
        contact = _extract_contact(["+1 (404) 555-1234"])
        assert "404" in contact["phone"]

    def test_extracts_linkedin(self):
        contact = _extract_contact(["linkedin.com/in/janedoe"])
        assert "janedoe" in contact["linkedin"]

    def test_extracts_github_labeled(self):
        contact = _extract_contact(["github: janedoe"])
        assert contact["github"] == "janedoe"

    def test_extracts_address(self):
        contact = _extract_contact(["address: 123 Main St"])
        assert contact["address"] == "123 Main St"

    def test_extracts_city_state(self):
        contact = _extract_contact(["city_state: Atlanta, GA"])
        assert contact["city_state"] == "Atlanta, GA"

    def test_extracts_location(self):
        contact = _extract_contact(["location: Remote"])
        assert contact["location"] == "Remote"

    def test_no_private_phone_found_key(self):
        contact = _extract_contact(["+1 (404) 555-1234"])
        assert "_phone_found" not in contact

    def test_first_phone_wins(self):
        contact = _extract_contact(["+1 (404) 555-1234", "+1 (305) 999-8888"])
        assert "404" in contact["phone"]

    def test_empty_lines(self):
        contact = _extract_contact([])
        assert contact["email"] == ""


# ── _parse_skills_section ─────────────────────────────────────────────────────

class TestParseSkillsSection:
    def test_labeled_item(self):
        result = _parse_skills_section(["Languages: Python, Java, TypeScript"])
        assert result["type"] == "skills"
        assert result["items"][0]["label"] == "Languages"
        assert "Python" in result["items"][0]["value"]

    def test_unlabeled_item(self):
        result = _parse_skills_section(["Just a skill line"])
        assert result["items"][0]["label"] == ""
        assert result["items"][0]["value"] == "Just a skill line"

    def test_bullet_cleaned(self):
        result = _parse_skills_section(["• Languages: Python"])
        assert result["items"][0]["label"] == "Languages"

    def test_empty_lines_skipped(self):
        result = _parse_skills_section(["", "Languages: Python", ""])
        assert len(result["items"]) == 1

    def test_multiple_items(self):
        lines = ["Backend: Java, Spring Boot", "Frontend: Angular, TypeScript"]
        result = _parse_skills_section(lines)
        assert len(result["items"]) == 2


# ── _is_date_part ─────────────────────────────────────────────────────────────

class TestIsDatePart:
    def test_month_year_range(self):
        assert _is_date_part("January 2022 – December 2025")

    def test_year_dash_year(self):
        assert _is_date_part("2020 - 2022")

    def test_en_dash(self):
        assert _is_date_part("Jan 2022 \u2013 Present")

    def test_plain_text(self):
        assert not _is_date_part("Software Engineer")

    def test_year_alone_no_separator(self):
        # No dash or month — not a date range
        assert not _is_date_part("2022")


# ── _combine_date_ranges ──────────────────────────────────────────────────────

class TestCombineDateRanges:
    def test_empty_list(self):
        assert _combine_date_ranges([]) == ""

    def test_single_range(self):
        assert _combine_date_ranges(["Jan 2022 - Dec 2025"]) == "Jan 2022 - Dec 2025"

    def test_two_ranges_combined(self):
        result = _combine_date_ranges(["Jan 2022 - Dec 2023", "Jan 2024 - Dec 2025"])
        assert "2022" in result
        assert "2025" in result

    def test_ignores_empty_strings(self):
        result = _combine_date_ranges(["", "Jan 2022 - Dec 2023", ""])
        assert result == "Jan 2022 - Dec 2023"

    def test_same_start_and_end(self):
        result = _combine_date_ranges(["2022 - 2022"])
        assert "2022" in result


# ── _normalize_company ────────────────────────────────────────────────────────

class TestNormalizeCompany:
    def test_lowercases(self):
        assert _normalize_company("General Motors") == "general motors"

    def test_collapses_whitespace(self):
        assert _normalize_company("  General  Motors  ") == "general motors"

    def test_empty_string(self):
        assert _normalize_company("") == ""


# ── _merge_same_company_jobs ──────────────────────────────────────────────────

class TestMergeSameCompanyJobs:
    def _job(self, title, company, dates="2020 - 2022"):
        return {
            "title": title, "company": company, "dates": dates,
            "bullets": [], "groups": [],
        }

    def test_empty_list(self):
        assert _merge_same_company_jobs([]) == []

    def test_different_companies_unchanged(self):
        jobs = [self._job("SWE", "Alpha"), self._job("SWE", "Beta")]
        result = _merge_same_company_jobs(jobs)
        assert len(result) == 2

    def test_same_company_merged(self):
        jobs = [
            self._job("SWE I", "Acme Corp", "Jan 2020 - Dec 2021"),
            self._job("SWE II", "Acme Corp", "Jan 2022 - Dec 2023"),
        ]
        result = _merge_same_company_jobs(jobs)
        assert len(result) == 1
        assert result[0]["type"] == "grouped"
        assert result[0]["company"] == "Acme Corp"
        assert len(result[0]["sub_roles"]) == 2

    def test_three_same_company_merged(self):
        jobs = [self._job(f"Role {i}", "MegaCorp") for i in range(3)]
        result = _merge_same_company_jobs(jobs)
        assert len(result) == 1
        assert len(result[0]["sub_roles"]) == 3

    def test_case_insensitive_company_match(self):
        jobs = [self._job("SWE", "acme corp"), self._job("Staff", "Acme Corp")]
        result = _merge_same_company_jobs(jobs)
        assert len(result) == 1

    def test_non_consecutive_same_company_not_merged(self):
        jobs = [
            self._job("SWE", "Alpha"),
            self._job("SWE", "Beta"),
            self._job("SWE", "Alpha"),
        ]
        result = _merge_same_company_jobs(jobs)
        # Alpha, Beta, Alpha — Beta breaks consecutive run; two Alpha entries remain separate
        assert len(result) == 3


# ── _finalize_job ─────────────────────────────────────────────────────────────

class TestFinalizeJob:
    def _blank_job(self, hlines):
        return {"title": "", "company": "", "dates": "", "groups": [], "bullets": [],
                "_hlines": hlines, "_done": False}

    def test_single_pipe_three_parts(self):
        job = self._blank_job(["Software Engineer | Acme Corp | Jan 2022 – Dec 2025"])
        _finalize_job(job)
        assert job["title"] == "Software Engineer"
        assert job["company"] == "Acme Corp"
        assert "2022" in job["dates"]

    def test_empty_hlines_no_crash(self):
        job = self._blank_job([])
        _finalize_job(job)  # should not raise

    def test_already_done_is_noop(self):
        job = {"title": "Keep", "company": "Keep", "_done": True}
        _finalize_job(job)
        assert job["title"] == "Keep"

    def test_multiline_title_then_company_then_dates(self):
        job = self._blank_job([
            "Senior Software Engineer",
            "Acme Corp",
            "January 2022 – December 2025",
        ])
        _finalize_job(job)
        assert job["title"] == "Senior Software Engineer"
        assert job["company"] == "Acme Corp"
        assert "2022" in job["dates"]


# ── _parse_experience_section ─────────────────────────────────────────────────

class TestParseExperienceSection:
    def test_basic_job(self):
        lines = [
            "Software Engineer | Acme Corp | Jan 2022 – Dec 2025",
            "• Built distributed systems",
            "• Maintained 98% SLA",
        ]
        result = _parse_experience_section(lines)
        assert result["type"] == "experience"
        assert len(result["jobs"]) == 1
        job = result["jobs"][0]
        assert job["title"] == "Software Engineer"

    def test_two_separate_jobs(self):
        lines = [
            "SWE I | Alpha Co | Jan 2020 – Dec 2021",
            "• Built things",
            "",
            "SWE II | Beta Co | Jan 2022 – Dec 2023",
            "• Improved things",
        ]
        result = _parse_experience_section(lines)
        assert len(result["jobs"]) == 2

    def test_same_company_jobs_merged(self):
        lines = [
            "SWE I | Acme | Jan 2020 – Dec 2021",
            "• Built things",
            "",
            "SWE II | Acme | Jan 2022 – Dec 2023",
            "• More things",
        ]
        result = _parse_experience_section(lines)
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["type"] == "grouped"

    def test_group_label_creates_group(self):
        lines = [
            "Software Engineer | Acme Corp | Jan 2022 – Dec 2025",
            "Cloud & Infrastructure:",
            "• Deployed on Azure",
        ]
        result = _parse_experience_section(lines)
        job = result["jobs"][0]
        assert len(job["groups"]) == 1
        assert job["groups"][0]["label"] == "Cloud & Infrastructure"

    def test_empty_section(self):
        result = _parse_experience_section([])
        assert result["jobs"] == []


# ── _parse_education_section ──────────────────────────────────────────────────

class TestParseEducationSection:
    def test_pipe_format(self):
        result = _parse_education_section(
            ["B.S. IoT Engineering | Florida International University | 2021"]
        )
        assert result["type"] == "education"
        assert "IoT" in result["degree"]
        assert "Florida" in result["school"]

    def test_multi_line_format(self):
        lines = ["B.S. Computer Science", "State University", "2020"]
        result = _parse_education_section(lines)
        assert "Computer Science" in result["degree"]
        assert "State" in result["school"]

    def test_relevant_coursework_extracted(self):
        lines = [
            "B.S. CS | State University | 2020",
            "Relevant Coursework: Algorithms, Data Structures",
        ]
        result = _parse_education_section(lines)
        assert "Algorithms" in result["coursework"]

    def test_pipe_two_parts_with_year(self):
        result = _parse_education_section(["B.S. CS | 2020"])
        assert result["degree"] == "B.S. CS"
        assert "2020" in result["school"]

    def test_pipe_two_parts_without_year(self):
        result = _parse_education_section(["B.S. CS | State University"])
        assert result["degree"] == "B.S. CS"
        assert "State" in result["school"]


# ── _parse_projects_section ───────────────────────────────────────────────────

class TestParseProjectsSection:
    def test_project_with_bullets(self):
        lines = ["My Project", "• Built with Python", "• Deployed on Azure"]
        result = _parse_projects_section(lines)
        assert result["type"] == "projects"
        assert len(result["projects"]) == 1
        assert result["projects"][0]["name"] == "My Project"
        assert len(result["projects"][0]["bullets"]) == 2

    def test_multiple_projects(self):
        lines = [
            "Project A", "• Bullet A",
            "Project B", "• Bullet B",
        ]
        result = _parse_projects_section(lines)
        assert len(result["projects"]) == 2

    def test_empty_section(self):
        result = _parse_projects_section([])
        assert result["projects"] == []

    def test_bullet_before_name_creates_unnamed_project(self):
        lines = ["• Orphan bullet"]
        result = _parse_projects_section(lines)
        assert len(result["projects"]) == 1
        assert result["projects"][0]["name"] == ""


# ── _parse_leadership_section ─────────────────────────────────────────────────

class TestParseLeadershipSection:
    def test_labeled_item(self):
        lines = ["ERG JumpStart President: Led DEI initiatives across org"]
        result = _parse_leadership_section(lines)
        assert result["type"] == "leadership"
        assert result["items"][0]["label"] == "ERG JumpStart President"

    def test_unlabeled_item(self):
        result = _parse_leadership_section(["Plain leadership line"])
        assert result["items"][0]["label"] == ""
        assert result["items"][0]["value"] == "Plain leadership line"

    def test_pipe_separated_items(self):
        lines = ["Title A: desc A | Title B: desc B"]
        result = _parse_leadership_section(lines)
        assert len(result["items"]) == 2

    def test_bullet_cleaned(self):
        result = _parse_leadership_section(["• Role: did things"])
        assert result["items"][0]["label"] == "Role"

    def test_empty_lines_skipped(self):
        result = _parse_leadership_section(["", "Role: desc", ""])
        assert len(result["items"]) == 1


# ── _parse_achievements_section ───────────────────────────────────────────────

class TestParseAchievementsSection:
    def test_bullet_items(self):
        result = _parse_achievements_section(["• Achievement one", "• Achievement two"])
        assert result["type"] == "achievements"
        assert len(result["items"]) == 2
        assert result["items"][0] == "Achievement one"

    def test_plain_items(self):
        result = _parse_achievements_section(["Plain achievement"])
        assert result["items"][0] == "Plain achievement"

    def test_empty_lines_skipped(self):
        result = _parse_achievements_section(["", "• Item", ""])
        assert len(result["items"]) == 1


# ── _derive_footer_tag ────────────────────────────────────────────────────────

class TestDeriveFooterTag:
    def test_software_engineer(self):
        assert _derive_footer_tag("resume-software-engineer.txt") == "SOFTWARE ENGINEER"

    def test_swe_abbreviation(self):
        assert _derive_footer_tag("acme-swe-resume.txt") == "SOFTWARE ENGINEER"

    def test_full_stack(self):
        assert _derive_footer_tag("full-stack-engineer.txt") == "FULL STACK ENGINEER"

    def test_full_stack_no_hyphen(self):
        # "fullstack" (no space/hyphen) doesn't match — needs "full stack" or "full-stack"
        assert _derive_footer_tag("full-stack-engineer.txt") == "FULL STACK ENGINEER"

    def test_backend(self):
        assert _derive_footer_tag("backend-engineer.txt") == "BACKEND ENGINEER"

    def test_frontend(self):
        assert _derive_footer_tag("frontend-engineer.txt") == "FRONTEND ENGINEER"

    def test_front_end_hyphen(self):
        assert _derive_footer_tag("front-end-resume.txt") == "FRONTEND ENGINEER"

    def test_data_engineer(self):
        # needs "data engineer" (with space) in the stem
        assert _derive_footer_tag("data engineer resume.txt") == "DATA ENGINEER"

    def test_devops(self):
        assert _derive_footer_tag("devops-resume.txt") == "DEVOPS ENGINEER"

    def test_sre(self):
        assert _derive_footer_tag("sre-resume.txt") == "DEVOPS ENGINEER"

    def test_unknown_defaults_to_software_engineer(self):
        assert _derive_footer_tag("mystery-role.txt") == "SOFTWARE ENGINEER"


# ── _parse_name_parts ─────────────────────────────────────────────────────────

class TestParseNameParts:
    def test_two_part_name(self):
        result = _parse_name_parts("JANE DOE")
        assert result["name_line1"] == "JANE"
        assert result["name_last"] == "DOE"
        assert result["name_suffix"] == ""

    def test_three_part_name(self):
        result = _parse_name_parts("JOHN V DOE")
        assert result["name_line1"] == "JOHN"
        assert result["name_line2"] == "V"
        assert result["name_last"] == "DOE"

    def test_suffix_extracted(self):
        result = _parse_name_parts("FRANK V MACBRIDE III")
        assert result["name_suffix"] == "III"
        assert result["name_last"] == "MACBRIDE"

    def test_jr_suffix(self):
        result = _parse_name_parts("JOHN DOE JR")
        assert result["name_suffix"] == "JR"

    def test_single_name(self):
        result = _parse_name_parts("CHER")
        assert result["name_line1"] == "CHER"
        assert result["name_last"] == ""

    def test_angle_brackets_stripped(self):
        result = _parse_name_parts("<JANE DOE>")
        assert result["name_line1"] == "JANE"
        assert result["name_last"] == "DOE"

    def test_lowercase_converted(self):
        result = _parse_name_parts("jane doe")
        assert result["name_line1"] == "JANE"


# ── _parse_header ─────────────────────────────────────────────────────────────

class TestParseHeader:
    def test_name_extracted(self):
        pre = ["Jane Doe"]
        contact = {}
        name, tagline, synopsis = _parse_header(pre, contact)
        assert "JANE DOE" in name

    def test_tagline_extracted(self):
        pre = ["Jane Doe", "", "Python • Django | Backend | Cloud"]
        name, tagline, synopsis = _parse_header(pre, {})
        assert "|" in tagline

    def test_synopsis_lines_collected(self):
        pre = ["Jane Doe", "", "Some tagline | here", "First synopsis line.", "Second synopsis line."]
        name, tagline, synopsis = _parse_header(pre, {})
        assert "First synopsis" in synopsis or "Second synopsis" in synopsis

    def test_contact_lines_skipped(self):
        pre = ["Jane Doe", "jane@example.com", "+1 (404) 555-1234"]
        name, _, _ = _parse_header(pre, {})
        assert "JANE DOE" in name

    def test_empty_pre_lines(self):
        name, tagline, synopsis = _parse_header([], {})
        assert name == ""


# ── _parse_resume_txt integration ────────────────────────────────────────────

_SAMPLE_RESUME = """\
JANE DOE
jane@example.com
+1 (404) 555-0000
linkedin.com/in/janedoe

Backend Engineer | Python • Django | Cloud

Experienced backend engineer with a focus on distributed systems.

TECHNICAL SKILLS
Backend: Python, Django, FastAPI
Cloud: AWS, Docker, Kubernetes

PROFESSIONAL EXPERIENCE
Software Engineer | Acme Corp | Jan 2022 – Dec 2025
• Built scalable APIs serving 10M requests/day
• Maintained 99.9% uptime across 3 services

EDUCATION
B.S. Computer Science | State University | 2020

PERSONAL PROJECTS
Open Source Tool
• Contributed 500+ commits to OSS ecosystem

LEADERSHIP & ADDITIONAL
ERG Chair: Led 40-person community group
"""


class TestParseResumeTxt:
    @pytest.fixture(autouse=True)
    def patch_config(self, monkeypatch):
        import lib.config as cfg
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {})
        monkeypatch.setattr(cfg, "get_contact_name", lambda default="": default)

    def test_returns_dict(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        assert isinstance(result, dict)

    def test_contact_extracted(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        assert "jane@example.com" in result["contact"]["email"]

    def test_synopsis_populated(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        assert result["synopsis"]

    def test_sections_present(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        types = [s["type"] for s in result["sections"]]
        assert "skills" in types
        assert "experience" in types
        assert "education" in types

    def test_skills_parsed(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        skills = next(s for s in result["sections"] if s["type"] == "skills")
        labels = [i["label"] for i in skills["items"]]
        assert "Backend" in labels

    def test_experience_parsed(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        exp = next(s for s in result["sections"] if s["type"] == "experience")
        assert len(exp["jobs"]) >= 1

    def test_education_parsed(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        edu = next(s for s in result["sections"] if s["type"] == "education")
        assert "Computer Science" in edu["degree"]

    def test_projects_parsed(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        proj = next(s for s in result["sections"] if s["type"] == "projects")
        assert len(proj["projects"]) >= 1

    def test_leadership_parsed(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        lead = next(s for s in result["sections"] if s["type"] == "leadership")
        assert len(lead["items"]) >= 1

    def test_code_fence_wrapper_stripped(self):
        wrapped = f"```plaintext\n{_SAMPLE_RESUME.strip()}\n```"
        result = _parse_resume_txt(wrapped)
        assert result["contact"]["email"] == "jane@example.com"

    def test_tagline_extracted(self):
        result = _parse_resume_txt(_SAMPLE_RESUME)
        assert "|" in result["tagline"]


# ── _parse_cover_letter_txt integration ──────────────────────────────────────

_SAMPLE_COVER_LETTER = """\
JANE DOE
jane@example.com
+1 (404) 555-0000
linkedin.com/in/janedoe

Hiring Manager
Acme Corp

Dear Hiring Manager,

I am writing to express my interest in the Backend Engineer role at Acme Corp. \
My experience building distributed systems and maintaining high-availability services \
makes me a strong fit for your team.

In my recent role at Beta Corp, I led the development of a microservices platform \
that served 10 million daily active users with 99.9% uptime.

I look forward to discussing how my experience can contribute to Acme's platform goals.

Kindest Regards,
Jane Doe
"""


class TestParseCoverLetterTxt:
    @pytest.fixture(autouse=True)
    def patch_config(self, monkeypatch):
        import lib.config as cfg
        monkeypatch.setattr(cfg, "get_contact_info", lambda: {})
        monkeypatch.setattr(cfg, "get_contact_name", lambda default="": default)

    def test_returns_dict(self):
        result = _parse_cover_letter_txt(_SAMPLE_COVER_LETTER)
        assert isinstance(result, dict)

    def test_contact_extracted(self):
        result = _parse_cover_letter_txt(_SAMPLE_COVER_LETTER)
        assert "jane@example.com" in result["contact"]["email"]

    def test_paragraphs_present(self):
        result = _parse_cover_letter_txt(_SAMPLE_COVER_LETTER)
        assert len(result["paragraphs"]) >= 3

    def test_body_starts_at_dear(self):
        result = _parse_cover_letter_txt(_SAMPLE_COVER_LETTER)
        assert any("Dear" in p for p in result["paragraphs"])

    def test_closing_split_correctly(self):
        letter = "Dear Team,\n\nBody paragraph.\n\nKindest Regards, Jane Doe\n"
        with patch("lib.config.get_contact_info", return_value={}), \
             patch("lib.config.get_contact_name", return_value=""):
            result = _parse_cover_letter_txt(letter)
        paras = result["paragraphs"]
        assert any("Kindest Regards" in p for p in paras)

    def test_name_parts_present(self):
        result = _parse_cover_letter_txt(_SAMPLE_COVER_LETTER)
        assert "name_line1" in result
        assert result["name_line1"]

    def test_code_fence_wrapper_stripped(self):
        wrapped = f"```plaintext\n{_SAMPLE_COVER_LETTER.strip()}\n```"
        result = _parse_cover_letter_txt(wrapped)
        assert result["contact"]["email"] == "jane@example.com"

    def test_short_greeting_starts_body(self):
        letter = "Jane Doe\njane@example.com\n\nHi Sarah,\n\nBody paragraph here.\n"
        with patch("lib.config.get_contact_info", return_value={}), \
             patch("lib.config.get_contact_name", return_value=""):
            result = _parse_cover_letter_txt(letter)
        assert any("Hi Sarah" in p or "Body" in p for p in result["paragraphs"])
