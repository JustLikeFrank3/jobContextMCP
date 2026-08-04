"""Tests for scripts/rename_unrepresentable_files.py — the one-off cleanup for
pre-sanitize filenames sitting in a cloud partition.

This script is run by hand against production via `kubectl exec`, so the
behaviour that matters is: it never overwrites, it never edits content, and
its rename rule does not drift from the one the application applies at
creation.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rename_unrepresentable_files.py"

# The fixtures below create files named `Coke <html>.md` — which Windows
# refuses to create at all. That refusal *is* the bug this script cleans up
# after, so the filesystem tests only mean anything on a POSIX filesystem
# (CI and the AKS pod are both Linux). The rule-parity test is pure string
# work and runs everywhere.
posix_only = pytest.mark.skipif(
    os.name == "nt",
    reason="these filenames cannot exist on Windows — that is the condition under test",
)


def _load_script():
    spec = importlib.util.spec_from_file_location("_rename_script", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_rename_script"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


class TestRuleMatchesApplication:
    def test_sanitize_matches_lib_helpers_exactly(self, script):
        """The script inlines the rule so it can run standalone in the pod.
        If lib.helpers ever changes, this fails and the script must follow."""
        from lib.helpers import sanitize_filename as app_sanitize

        cases = [
            r'a<b>c:d"e/f\g|h?i*j',
            "Coke <html> - Fitment Assessment.md",
            "Home, RI URL Source: https://jobs.example.com - Fitment Assessment.md",
            "Coke Senior Software Engineer | Atlanta, GA US - Fitment Assessment.md",
            "report\x07.",
            "name.md ",
            "a   b",
            "   ",
            "...",
            "already-fine.md",
        ]
        for name in cases:
            assert script.sanitize_filename(name) == app_sanitize(name), name


class TestPlanRenames:
    """The planner is pure, so the logic that could destroy data is verified
    on every platform — including Windows, where these names cannot exist."""

    def test_leaves_representable_names_alone(self, script):
        assert script.plan_renames(["fine.md", "also - fine.md"]) == []

    def test_maps_the_real_production_names(self, script):
        """The twelve stuck files are these shapes."""
        names = [
            "Coke <html> - Fitment Assessment.md",
            "Ga <html> - Fitment Assessment.md",
            "Coke Senior Software Engineer | Atlanta, GA US - Fitment Assessment.md",
            "Home, Rhode Island, URL Source: https://x.com - Fitment Assessment.md",
        ]
        planned = dict((old, new) for old, new, _c in script.plan_renames(names))

        assert planned["Coke <html> - Fitment Assessment.md"] == (
            "Coke -html- - Fitment Assessment.md")
        assert planned["Ga <html> - Fitment Assessment.md"] == (
            "Ga -html- - Fitment Assessment.md")
        assert planned[
            "Coke Senior Software Engineer | Atlanta, GA US - Fitment Assessment.md"
        ] == "Coke Senior Software Engineer - Atlanta, GA US - Fitment Assessment.md"
        assert planned[
            "Home, Rhode Island, URL Source: https://x.com - Fitment Assessment.md"
        ] == "Home, Rhode Island, URL Source- https---x.com - Fitment Assessment.md"
        for new in planned.values():
            assert not set('<>:"/\\|?*') & set(new), new

    def test_existing_clean_file_is_not_targeted(self, script):
        """The sanitized name is already on disk with different content —
        suffix rather than plan a rename that would clobber it."""
        planned = script.plan_renames([
            "Coke -html-.md",          # innocent bystander, already clean
            "Coke <html>.md",          # sanitizes onto the bystander
        ])

        assert planned == [("Coke <html>.md", "Coke -html- (2).md", True)]

    def test_two_bad_names_collapsing_to_one_target_get_distinct_names(self, script):
        planned = script.plan_renames(["Coke <html>.md", "Coke |html|.md"])

        targets = [new for _o, new, _c in planned]
        assert len(planned) == 2
        assert len(set(targets)) == 2, f"both planned the same target: {targets}"
        assert "Coke -html-.md" in targets
        assert "Coke -html- (2).md" in targets

    def test_three_way_collision_all_distinct(self, script):
        planned = script.plan_renames(["a<b>.md", "a|b|.md", "a?b*.md"])

        targets = [new for _o, new, _c in planned]
        assert sorted(targets) == ["a-b- (2).md", "a-b- (3).md", "a-b-.md"]

    def test_extensionless_name_suffixes_correctly(self, script):
        planned = script.plan_renames(["a-b", "a<b"])
        assert planned == [("a<b", "a-b (2)", True)]

    def test_no_target_ever_equals_another_source(self, script):
        """A target that collides with a file still waiting to be renamed
        would be overwritten when its turn came."""
        names = ["x<1>.md", "x-1-.md", "x|1|.md", "keep.md"]
        planned = script.plan_renames(names)

        targets = {new for _o, new, _c in planned}
        sources = {old for old, _n, _c in planned}
        untouched = set(names) - sources
        assert not (targets & sources), targets & sources
        assert not (targets & untouched), targets & untouched


class TestMainOrchestrationOnAnyPlatform:
    """Drives main() over a faked walk so the dry-run/apply contract is
    verified on Windows too — the real filesystem tests below cannot run here."""

    @pytest.fixture
    def fake_tree(self, script, monkeypatch, tmp_path):
        walked = [(
            str(tmp_path / "07-Job-Assessments" / "run_job_assessment"),
            [],
            ["Coke <html> - Fitment Assessment.md", "fine.md"],
        )]
        monkeypatch.setattr(script.os, "walk", lambda _root: iter(walked))

        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            script.os, "rename", lambda src, dst: calls.append((str(src), str(dst))))
        return calls

    def test_dry_run_renames_nothing(self, script, fake_tree, tmp_path, capsys):
        rc = script.main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert rc == 0
        assert fake_tree == [], "dry run must not call rename"
        assert "DRY RUN" in out
        assert "files needing rename: 1" in out

    def test_dry_run_prints_before_and_after(self, script, fake_tree, tmp_path, capsys):
        script.main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert "Coke <html> - Fitment Assessment.md" in out
        assert "Coke -html- - Fitment Assessment.md" in out
        assert "fine.md" not in out, "untouched files should not be listed"

    def test_apply_renames_only_the_bad_name(self, script, fake_tree, tmp_path, capsys):
        rc = script.main(["--root", str(tmp_path), "--apply"])
        out = capsys.readouterr().out

        assert rc == 0
        assert len(fake_tree) == 1
        src, dst = fake_tree[0]
        assert src.endswith("Coke <html> - Fitment Assessment.md")
        assert dst.endswith("Coke -html- - Fitment Assessment.md")
        assert "renamed: 1    skipped: 0    failed: 0" in out

    def test_output_is_ascii_only(self, script, fake_tree, tmp_path, capsys):
        """A non-ASCII character in the output raises UnicodeEncodeError on a
        non-UTF-8 stdout, which under --apply aborts the run *after* some
        files have already been renamed. Found by a live run, not by a unit
        test — keep it locked down."""
        script.main(["--root", str(tmp_path), "--apply"])
        out = capsys.readouterr().out

        # The filenames themselves may be non-ASCII; the script's own
        # decoration must not be.
        decoration = out.replace("Coke <html> - Fitment Assessment.md", "")
        decoration = decoration.replace("Coke -html- - Fitment Assessment.md", "")
        decoration.encode("ascii")  # raises if the script added a fancy glyph

    def test_rename_failure_is_reported_and_exits_nonzero(
        self, script, monkeypatch, fake_tree, tmp_path, capsys
    ):
        def _boom(src, dst):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(script.os, "rename", _boom)
        rc = script.main(["--root", str(tmp_path), "--apply"])
        out = capsys.readouterr().out

        assert rc == 1
        assert "FAILED" in out
        assert "read-only filesystem" in out


@posix_only
class TestDuplicateDetection:
    """Every one of the twelve production files turned out to have a
    clean-named twin beside it: the same assessment re-saved after the July
    sanitize fix, orphaning the old copy. Renaming those just duplicates
    them, so identical content is left alone unless forced."""

    def test_identical_twin_is_skipped_not_renamed(self, script, tmp_path):
        (tmp_path / "Coke -html-.md").write_text("SAME BYTES")
        (tmp_path / "Coke <html>.md").write_text("SAME BYTES")

        rc = script.main(["--root", str(tmp_path), "--apply"])

        assert rc == 0
        assert (tmp_path / "Coke <html>.md").exists(), "duplicate should be left in place"
        assert not (tmp_path / "Coke -html- (2).md").exists(), "should not have duplicated"

    def test_identical_twin_is_reported_as_such(self, script, tmp_path, capsys):
        (tmp_path / "Coke -html-.md").write_text("SAME BYTES")
        (tmp_path / "Coke <html>.md").write_text("SAME BYTES")

        script.main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert "byte-identical" in out
        assert "SKIPPED" in out
        assert "--force-duplicates" in out

    def test_differing_twin_is_still_renamed(self, script, tmp_path):
        """Different content is real data - suffix it and keep both."""
        (tmp_path / "Coke -html-.md").write_text("VERSION A")
        (tmp_path / "Coke <html>.md").write_text("VERSION B")

        rc = script.main(["--root", str(tmp_path), "--apply"])

        assert rc == 0
        assert (tmp_path / "Coke -html-.md").read_text() == "VERSION A"
        assert (tmp_path / "Coke -html- (2).md").read_text() == "VERSION B"
        assert not (tmp_path / "Coke <html>.md").exists()

    def test_differing_twin_is_flagged_loudly(self, script, tmp_path, capsys):
        (tmp_path / "Coke -html-.md").write_text("VERSION A")
        (tmp_path / "Coke <html>.md").write_text("VERSION B")

        script.main(["--root", str(tmp_path)])

        assert "DIFFERENT content" in capsys.readouterr().out

    def test_force_duplicates_renames_identical_twin(self, script, tmp_path):
        (tmp_path / "Coke -html-.md").write_text("SAME BYTES")
        (tmp_path / "Coke <html>.md").write_text("SAME BYTES")

        rc = script.main(
            ["--root", str(tmp_path), "--apply", "--force-duplicates"])

        assert rc == 0
        assert (tmp_path / "Coke -html- (2).md").read_text() == "SAME BYTES"
        assert not (tmp_path / "Coke <html>.md").exists()

    def test_no_twin_at_all_renames_normally(self, script, tmp_path):
        """The non-collision path must be unaffected by duplicate checking."""
        (tmp_path / "Coke <html>.md").write_text("ONLY COPY")

        rc = script.main(["--root", str(tmp_path), "--apply"])

        assert rc == 0
        assert (tmp_path / "Coke -html-.md").read_text() == "ONLY COPY"


@posix_only
class TestFindRenames:
    def test_flags_only_unrepresentable_names(self, script, tmp_path):
        (tmp_path / "fine.md").write_text("ok")
        (tmp_path / "Coke <html> - Fitment Assessment.md").write_text("bad")

        planned = script.find_renames(tmp_path)

        assert len(planned) == 1
        source, target, collided = planned[0]
        assert source.name == "Coke <html> - Fitment Assessment.md"
        assert target.name == "Coke -html- - Fitment Assessment.md"
        assert collided is False

    def test_walks_nested_assessment_folders(self, script, tmp_path):
        for parent in ("07-Job-Assessments", "workspace/07-Job-Assessments"):
            nested = tmp_path / parent / "run_job_assessment"
            nested.mkdir(parents=True)
            (nested / "Ga <html> - Fitment Assessment.md").write_text("x")

        planned = script.find_renames(tmp_path)

        assert len(planned) == 2
        assert all("<" not in t.name for _s, t, _c in planned)

    def test_skips_machine_local_dirs(self, script, tmp_path):
        db = tmp_path / "db"
        db.mkdir()
        (db / "weird:name.sqlite").write_text("x")

        assert script.find_renames(tmp_path) == []


@posix_only
class TestCollisionHandling:
    def test_suffixes_instead_of_overwriting(self, script, tmp_path):
        (tmp_path / "Coke -html- - Fitment Assessment.md").write_text("EXISTING")
        (tmp_path / "Coke <html> - Fitment Assessment.md").write_text("INCOMING")

        rc = script.main(["--root", str(tmp_path), "--apply"])

        assert rc == 0
        assert (tmp_path / "Coke -html- - Fitment Assessment.md").read_text() == "EXISTING"
        assert (tmp_path / "Coke -html- - Fitment Assessment (2).md").read_text() == "INCOMING"

    def test_two_bad_names_collapsing_to_one_target_both_survive(self, script, tmp_path):
        (tmp_path / "Coke <html>.md").write_text("first")
        (tmp_path / "Coke |html|.md").write_text("second")

        rc = script.main(["--root", str(tmp_path), "--apply"])

        assert rc == 0
        contents = sorted(p.read_text() for p in tmp_path.glob("*.md"))
        assert contents == ["first", "second"], "a file was overwritten"
        assert len(list(tmp_path.glob("*.md"))) == 2


@posix_only
class TestDryRunAndOutput:
    def test_dry_run_changes_nothing_and_prints_mapping(self, script, tmp_path, capsys):
        bad = tmp_path / "Coke <html> - Fitment Assessment.md"
        bad.write_text("content")

        rc = script.main(["--root", str(tmp_path)])
        out = capsys.readouterr().out

        assert rc == 0
        assert bad.exists(), "dry run must not rename"
        assert "DRY RUN" in out
        assert "Coke <html> - Fitment Assessment.md" in out
        assert "Coke -html- - Fitment Assessment.md" in out

    def test_apply_preserves_content_and_mtime(self, script, tmp_path):
        bad = tmp_path / "Home, RI Source: x.md"
        bad.write_text("PRECIOUS ASSESSMENT TEXT")
        import os
        os.utime(bad, (1_600_000_000, 1_600_000_000))

        script.main(["--root", str(tmp_path), "--apply"])

        survivors = list(tmp_path.glob("*.md"))
        assert len(survivors) == 1
        assert survivors[0].read_text() == "PRECIOUS ASSESSMENT TEXT"
        assert survivors[0].stat().st_mtime == 1_600_000_000

    def test_clean_tree_reports_nothing_to_do(self, script, tmp_path, capsys):
        (tmp_path / "fine.md").write_text("ok")

        rc = script.main(["--root", str(tmp_path)])

        assert rc == 0
        assert "Nothing to do" in capsys.readouterr().out

    def test_missing_root_is_an_error(self, script, tmp_path):
        assert script.main(["--root", str(tmp_path / "nope")]) == 2
