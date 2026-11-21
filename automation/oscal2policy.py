"""oscal2policy for OPA, in the style of C2P (compliance-to-policy).

C2P has no OPA plugin, so this does the same job for this repo: it selects the
hand-written policies needed by an assessment plan and stages them for OPA.
It does not write policy logic.

  assessment plan  activities carry Rule_Id props (what to test)
    -> import-ssp  SSP components link to their component definitions
    -> component definitions (and their import-component-definitions)
                   validation components map Rule_Id -> Check_Id (rule_set_NN)
    -> policies/   each Rego file declares `check_id` in its METADATA

Output (in --out):
  rego/         the selected policy files (tests excluded)
  checks.json   [{rule_id, check_id, package, policy}] for result2oscal

Usage: python automation/oscal2policy.py <assessment-plan.json> <out-dir> [policies-dir]
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oscal_common import REPO_ROOT, load_model, prop_values, resolve_href, write_json  # noqa: E402


def component_definitions_for(ssp_path: Path) -> list[Path]:
    """Component definitions linked from SSP components, plus everything they import."""
    _, ssp = load_model(ssp_path)
    todo = [resolve_href(link["href"], ssp_path)
            for comp in ssp["system-implementation"]["components"]
            for link in comp.get("links", []) if link.get("rel") == "component-definition"]
    seen: list[Path] = []
    while todo:
        path = todo.pop(0)
        if path in seen:
            continue
        seen.append(path)
        _, cd = load_model(path)
        todo += [resolve_href(i["href"], path) for i in cd.get("import-component-definitions", [])]
    return seen


def rule_to_check(cd_paths: list[Path]) -> dict[str, str]:
    """Rule_Id -> Check_Id from validation components (props grouped by remarks rule_set_NN)."""
    mapping: dict[str, str] = {}
    for path in cd_paths:
        _, cd = load_model(path)
        for comp in cd.get("components", []):
            if comp["type"] != "validation":
                continue
            sets: dict[str, dict[str, str]] = {}
            for p in comp.get("props", []):
                if p.get("remarks", "").startswith("rule_set_"):
                    sets.setdefault(p["remarks"], {})[p["name"]] = p["value"]
            for s in sets.values():
                if "Rule_Id" in s and "Check_Id" in s:
                    mapping[s["Rule_Id"]] = s["Check_Id"]
    return mapping


def policies_by_check_id(policies_dir: Path) -> dict[str, tuple[Path, str]]:
    """check_id -> (rego file, package) from the METADATA of each non-test policy."""
    found: dict[str, tuple[Path, str]] = {}
    for rego in sorted(policies_dir.rglob("*.rego")):
        if rego.name.endswith("_test.rego"):
            continue
        text = rego.read_text(encoding="utf-8")
        check = re.search(r"^#\s+check_id:\s*(\S+)", text, re.M)
        package = re.search(r"^package\s+(\S+)", text, re.M)
        if check and package:
            found[check.group(1)] = (rego, package.group(1))
    return found


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    ap_path, out_dir = Path(argv[1]).resolve(), Path(argv[2])
    policies_dir = Path(argv[3]) if len(argv) == 4 else REPO_ROOT / "policies"

    _, ap = load_model(ap_path)
    ssp_path = resolve_href(ap["import-ssp"]["href"], ap_path)
    rules = [r for act in ap.get("local-definitions", {}).get("activities", [])
             for r in prop_values(act, "Rule_Id")]
    checks = rule_to_check(component_definitions_for(ssp_path))
    policies = policies_by_check_id(policies_dir)

    selected: list[dict[str, Any]] = []
    for rule in rules:
        if rule not in checks:
            raise SystemExit(f"Rule_Id {rule} has no Check_Id in any linked component definition")
        check = checks[rule]
        if check not in policies:
            raise SystemExit(f"Check_Id {check} (rule {rule}) has no policy in {policies_dir}")
        rego, package = policies[check]
        selected.append({"rule_id": rule, "check_id": check, "package": package,
                         "policy": rego.relative_to(REPO_ROOT).as_posix()})

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "rego").mkdir(parents=True)
    for s in selected:
        shutil.copy2(REPO_ROOT / s["policy"], out_dir / "rego" / Path(s["policy"]).name)
    write_json(out_dir / "checks.json", selected)
    for s in selected:
        print(f"{s['rule_id']} -> {s['check_id']} -> {s['policy']} (data.{s['package']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
