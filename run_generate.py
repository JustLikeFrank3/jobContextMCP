#!/usr/bin/env python3
"""
CLI runner for generate_cover_letter / generate_resume.
Reads the job description from a file so there are no heredoc/quoting issues.

Usage:
  python run_generate.py cover  <company> <role> [jd_file]
  python run_generate.py resume <company> <role> [jd_file]

If jd_file is omitted, the runner looks in workspace/jds/ for a file whose name
contains the company name (case-insensitive). If exactly one match is found it
is used automatically.

Examples:
  python run_generate.py cover "Meta" "Software Engineer, Infrastructure"
  python run_generate.py cover "Meta" "Software Engineer, Infrastructure" /tmp/jd.txt
  python run_generate.py resume "Meta" "Software Engineer, Infrastructure"
"""
import sys
import pathlib

JDS_DIR = pathlib.Path(__file__).parent / "workspace" / "jds"


def _resolve_jd(company: str, explicit_path: str | None) -> pathlib.Path:
    if explicit_path:
        p = pathlib.Path(explicit_path)
        if not p.exists():
            print(f"ERROR: JD file not found: {p}")
            sys.exit(1)
        return p

    # Auto-resolve from workspace/jds/
    if not JDS_DIR.exists():
        print(f"ERROR: No jd_file given and {JDS_DIR} does not exist.")
        sys.exit(1)

    matches = [f for f in JDS_DIR.iterdir()
               if company.lower() in f.name.lower() and f.suffix in (".txt", ".md")]
    if len(matches) == 1:
        print(f"  Using JD: {matches[0].name}")
        return matches[0]
    elif len(matches) > 1:
        print(f"ERROR: Multiple JD files match '{company}' in {JDS_DIR}:")
        for m in matches:
            print(f"  {m.name}")
        print("Pass an explicit jd_file path to disambiguate.")
        sys.exit(1)
    else:
        print(f"ERROR: No JD file found for '{company}' in {JDS_DIR}")
        print(f"Save one as: {JDS_DIR}/{company} - <role>.txt")
        sys.exit(1)


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    mode    = sys.argv[1].lower()   # "cover" or "resume"
    company = sys.argv[2]
    role    = sys.argv[3]
    explicit_jd = sys.argv[4] if len(sys.argv) >= 5 else None

    jd_file = _resolve_jd(company, explicit_jd)
    jd = jd_file.read_text(encoding="utf-8")

    if mode == "cover":
        from tools.generate import generate_cover_letter
        result = generate_cover_letter(company, role, jd)
    elif mode == "resume":
        from tools.generate import generate_resume
        result = generate_resume(company, role, jd)
    else:
        print(f"ERROR: unknown mode '{mode}'. Use 'cover' or 'resume'.")
        sys.exit(1)

    print(result)

if __name__ == "__main__":
    main()
