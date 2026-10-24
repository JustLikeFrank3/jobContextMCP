"""Regenerate the architecture overview with Graphviz; no network or packages.

The sequence diagram is maintained directly as SVG. Validate both assets before
writing so the public page never acquires active/external SVG content.
"""
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


FOLDER = Path(__file__).resolve().parents[1] / "transport/http/static/architecture"
_STATIC_TAGS = {
    "svg", "g", "title", "desc", "defs", "marker", "path", "polygon", "polyline",
    "rect", "circle", "ellipse", "line", "text", "tspan",
}


def validate_svg(source: str) -> None:
    root = ET.fromstring(source)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Not an SVG image")
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] not in _STATIC_TAGS:
            raise ValueError("Active or external SVG element")
        for name, value in element.attrib.items():
            if name.rsplit("}", 1)[-1].lower().startswith("on") or name.endswith("href"):
                raise ValueError("SVG event handler or external reference")
            if re.search(r"(?:https?:|javascript:|data:|//)", value, re.IGNORECASE):
                raise ValueError("External SVG resource")
            for target in re.findall(r"url\((.*?)\)", value, re.IGNORECASE):
                if not re.fullmatch(r"#[\w:.-]+", target.strip(" \t\r\n\"'")):
                    raise ValueError("Only internal SVG fragment references are allowed")


if __name__ == "__main__":
    svg = subprocess.run(
        ["dot", "-Tsvg", str(FOLDER / "capability-layer.dot")],
        check=True, capture_output=True, text=True,
    ).stdout
    # Graphviz adds a historical remote SVG DTD. The asset needs no DTD or fetch.
    svg = re.sub(r"<!DOCTYPE[^>]*>\s*", "", svg)
    validate_svg(svg)
    validate_svg((FOLDER / "webmcp-bridge.svg").read_text(encoding="utf-8"))
    (FOLDER / "capability-layer.svg").write_text(svg, encoding="utf-8")
    print("Rendered capability-layer.svg; both SVG assets are inert and valid.")
