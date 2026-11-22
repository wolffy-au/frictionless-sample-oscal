"""Run the automated SC-28 assessment end to end (assessment plan task).

  1. compile main.bicep to ARM JSON            -> evidence/<name>/main.arm.json
  2. Azure adapter: ARM -> datastore inventory -> evidence/<name>/inventory.json
  3. oscal2policy: select policies from the AP -> build/policy/
  4. OPA: evaluate each selected check          -> evidence/<name>/opa-results.json
  5. result2oscal: OPA results -> OSCAL         -> assessment-results/<name>/assessment-results.json
  6. ar2poam --dry-run: report POA&M status     (writes nothing)

Run from anywhere:  poetry run python automation/run_assessment.py [path/to/main.bicep]

Tools: Bicep CLI ($BICEP, ~/.azure/bin/bicep[.exe] as installed by `az bicep install`,
or bicep on PATH) and OPA ($OPA, tools/opa.exe, or opa on PATH).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oscal_common import REPO_ROOT, write_json  # noqa: E402

NAME = "sample-azure-sc28"
AP = REPO_ROOT / "assessment-plans" / NAME / "assessment-plan.json"
AR = REPO_ROOT / "assessment-results" / NAME / "assessment-results.json"
POAM = REPO_ROOT / "plan-of-action-and-milestones" / "sample-azure" / "plan-of-action-and-milestones.json"
EVIDENCE = REPO_ROOT / "evidence" / NAME
POLICY = REPO_ROOT / "build" / "policy"
DEFAULT_BICEP = REPO_ROOT.parent / "test-azure" / "main.bicep"
HERE = Path(__file__).resolve().parent


def find_tool(env: str, candidates: list[Path], name: str) -> str:
    for c in [Path(os.environ[env])] if env in os.environ else []:
        return str(c)
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which(name)
    if not found:
        raise SystemExit(f"{name} not found: set ${env}")
    return found


def run(*args: str) -> str:
    print(">", " ".join(Path(a).name if i == 0 else a for i, a in enumerate(args)))
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str]) -> int:
    bicep_file = Path(argv[1]) if len(argv) > 1 else DEFAULT_BICEP
    home = Path.home() / ".azure" / "bin"
    bicep = find_tool("BICEP", [home / "bicep.exe", home / "bicep"], "bicep")
    opa = find_tool("OPA", [REPO_ROOT / "tools" / "opa.exe", REPO_ROOT / "tools" / "opa"], "opa")
    py = sys.executable
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    arm, inventory, results = EVIDENCE / "main.arm.json", EVIDENCE / "inventory.json", EVIDENCE / "opa-results.json"
    run(bicep, "build", str(bicep_file), "--outfile", str(arm))
    run(py, str(HERE / "azure_arm_inventory.py"), str(arm), str(inventory))
    print(run(py, str(HERE / "oscal2policy.py"), str(AP), str(POLICY)), end="")

    started = now()
    opa_version = run(opa, "version").splitlines()[0].split(":", 1)[1].strip()
    checks = {}
    for check in json.loads((POLICY / "checks.json").read_text(encoding="utf-8")):
        out = json.loads(run(opa, "eval", "--format", "json", "-d", str(POLICY / "rego"),
                             "-i", str(inventory), f"data.{check['package']}.deny"))
        deny = out["result"][0]["expressions"][0]["value"]
        checks[check["check_id"]] = {"package": check["package"], "deny": sorted(deny, key=lambda d: d["id"])}
    write_json(results, {"opa_version": opa_version, "started": started, "ended": now(), "checks": checks})

    print(run(py, str(HERE / "result2oscal.py"), str(AP), str(POLICY / "checks.json"),
              str(inventory), str(results), str(AR)), end="")
    print(f"wrote {AR.relative_to(REPO_ROOT).as_posix()}")

    # 6. POA&M status only (dry run): run ar2poam.py yourself to add drafts.
    if POAM.exists():
        print(run(py, str(HERE / "ar2poam.py"), "--dry-run", str(AR), str(POAM)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
