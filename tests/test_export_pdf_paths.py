from tools import export
from lib import config


def test_resume_and_cover_letter_pdfs_use_separate_folders(monkeypatch, tmp_path):
    resume_folder = tmp_path / "resumes"
    monkeypatch.setattr(config, "RESUME_FOLDER", resume_folder)
    monkeypatch.setattr(export.config, "RESUME_FOLDER", resume_folder)

    opt_dir = resume_folder / "01-Current-Optimized"
    cl_dir = resume_folder / "02-Cover-Letters"
    opt_dir.mkdir(parents=True, exist_ok=True)
    cl_dir.mkdir(parents=True, exist_ok=True)
    (opt_dir / "resume.txt").write_text("resume", encoding="utf-8")
    (cl_dir / "letter.txt").write_text("letter", encoding="utf-8")

    monkeypatch.setattr(export, "_parse_resume_txt", lambda text: {"contact": {}, "jobs": [], "skills": []})
    monkeypatch.setattr(export, "_parse_cover_letter_txt", lambda text: {"contact": {}, "paragraphs": []})
    monkeypatch.setattr(export, "_render_pdf", lambda template, data, path: path.write_bytes(b"%PDF"))

    resume_result = export.export_resume_pdf("resume.txt")
    cover_result = export.export_cover_letter_pdf("letter.txt")

    assert "03-Resume-PDFs" in resume_result
    assert "09-Cover-Letter-PDFs" in cover_result
    assert (resume_folder / "03-Resume-PDFs" / "resume.pdf").exists()
    assert (resume_folder / "09-Cover-Letter-PDFs" / "letter.pdf").exists()
