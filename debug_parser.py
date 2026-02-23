#!/usr/bin/env python3
"""Debug helper: parse a resume .txt file and print the structured result.

Usage:
    python debug_parser.py <path/to/resume.txt>
"""
import sys
sys.path.insert(0, '.')
from pathlib import Path
from tools.export import _parse_resume_txt


def main() -> None:
    if len(sys.argv) < 2:
        script_name = Path(sys.argv[0]).name
        print(f"Usage: {script_name} <resume_text_path>", file=sys.stderr)
        sys.exit(1)

    resume_path = Path(sys.argv[1])
    txt = resume_path.read_text()
    data = _parse_resume_txt(txt)

    print('NAME:', data.get('name'))
    print('SYNOPSIS:', (data.get('synopsis') or '')[:80])
    print()
    for s in data.get('sections', []):
        print('SECTION:', s['title'], '| type:', s.get('type'))
        if s.get('type') == 'skills':
            for item in s.get('items', [])[:5]:
                print('  label:', repr(item.get('label', '')[:50]), '| value:', repr(item.get('value', '')[:60]))
        elif s.get('type') == 'experience':
            for job in s.get('jobs', []):
                print('  JOB:', repr(job.get('title', '')), '|', repr(job.get('company', '')), '|', repr(job.get('dates', '')))
                for g in job.get('groups', []):
                    print('    GROUP label:', repr(g.get('label', '')), '| bullets:', len(g.get('bullets', [])))
                    for b in g.get('bullets', [])[:2]:
                        print('      bullet:', repr(b[:70]))
                if job.get('bullets'):
                    print('    FLAT bullets:', len(job['bullets']))
                    for b in job['bullets'][:2]:
                        print('      bullet:', repr(b[:70]))
        elif s.get('type') in ('projects', 'leadership'):
            for item in s.get('items', [])[:2]:
                print('  ITEM:', repr(item.get('title', '')), '| bullets:', len(item.get('bullets', [])))


if __name__ == "__main__":
    main()