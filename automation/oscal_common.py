"""Small helpers shared by the steel-thread automation scripts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
TRESTLE_NS = "https://oscal-compass.github.io/compliance-trestle/schemas/oscal"


def resolve_href(href: str, relative_to: Path | None = None) -> Path:
    """Turn an OSCAL href into a local path.

    trestle://x is relative to the trestle workspace (the repo root); other
    hrefs are relative to the referencing document's folder.
    """
    if href.startswith("trestle://"):
        return REPO_ROOT / href[len("trestle://"):]
    base = relative_to.parent if relative_to else REPO_ROOT
    return (base / href).resolve()


def trestle_href(path: Path) -> str:
    return "trestle://" + path.resolve().relative_to(REPO_ROOT).as_posix()


def load_model(path: Path) -> tuple[str, dict[str, Any]]:
    """Return (root key, model body) of an OSCAL JSON document."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    (key, body), = doc.items()
    return key, body


def write_json(path: Path, data: Any) -> None:
    """Write UTF-8 without a BOM (trestle rejects a BOM), indent 2, trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def prop_values(obj: dict[str, Any], name: str, ns: str | None = TRESTLE_NS) -> list[str]:
    return [p["value"] for p in obj.get("props", []) if p["name"] == name and p.get("ns") == ns]


def iter_objective_ids(control_objective_selections: list[dict[str, Any]]) -> Iterator[str]:
    for sel in control_objective_selections:
        for obj in sel.get("include-objectives", []):
            yield obj["objective-id"]
