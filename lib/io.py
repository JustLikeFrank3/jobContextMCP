import json
import datetime
from pathlib import Path


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Error reading {path.name}: {e}]"


def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_master_context() -> str:
    """Read master resume + GM awards + peer feedback as one enriched context block.

    Use this everywhere instead of bare _read(config.MASTER_RESUME) so that
    recognition quotes and peer feedback are always available to the AI when
    drafting resumes, cover letters, fitment assessments, and interview prep.
    """
    from lib import config  # local import avoids circular dependency

    parts = [_read(config.MASTER_RESUME)]

    awards_text = _read(config.GM_AWARDS)
    if not awards_text.startswith("[Error"):
        parts.append(
            "──── GM RECOGNITION AWARDS ────\n"
            "(Peer-written quotes — use exact language in cover letters and fitment assessments)\n"
            + awards_text
        )

    feedback_text = _read(config.FEEDBACK_RECEIVED)
    if not feedback_text.startswith("[Error"):
        parts.append(
            "──── PEER FEEDBACK (verbatim) ────\n"
            "(Direct quotes from managers and colleagues — high-value credibility signals)\n"
            + feedback_text
        )

    return "\n\n".join(parts)
