"""Run the automated SC-28 assessment end to end (assessment plan task).

  1. read the infrastructure definition         -> evidence/<name>/main.arm.json (azure)
                                                   evidence/<name>/main.tf.json  (gcp)
  2. platform adapter -> datastore inventory    -> evidence/<name>/inventory.json
  3. oscal2policy: select policies from the AP -> build/policy/
  4. OPA: evaluate each selected check          -> evidence/<name>/opa-results.json
  5. result2oscal: OPA results -> OSCAL         -> assessment-results/<name>/assessment-results.json
  6. ar2poam --dry-run: report POA&M status     (writes nothing)

Steps 3-6 are the same for every platform; only steps 1-2 differ.

Run from anywhere:  poetry run python automation/run_assessment.py [azure|gcp] [path/to/main.bicep|main.tf]
  azure (default)  ../test-azure/main.bicep -> sample-azure-sc28
  gcp              ../test-gcp/main.tf      -> sample-gcp-sc28

Tools: OPA ($OPA, tools/opa.exe, or opa on PATH); for azure also the Bicep CLI
($BICEP, ~/.azure/bin/bicep[.exe] as installed by `az bicep install`, or bicep on PATH).
gcp needs no extra tool: main.tf is parsed with python-hcl2.
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

HERE = Path(__file__).resolve().parent
POLICY = REPO_ROOT / "build" / "policy"
SYSTEMS = {
    "azure": {"system": "sample-azure", "source": REPO_ROOT.parent / "test-azure" / "main.bicep"},
    "gcp": {"system": "sample-gcp", "source": REPO_ROOT.parent / "test-gcp" / "main.tf"},
}


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


def build_inventory(platform: str, source: Path, evidence: Path, py: str) -> tuple[Path, Path]:
    """Steps 1-2, the only platform-specific part. Returns (adapter input, inventory)."""
    inventory = evidence / "inventory.json"
    if platform == "azure":
        home = Path.home() / ".azure" / "bin"
        bicep = find_tool("BICEP", [home / "bicep.exe", home / "bicep"], "bicep")
        adapter_input = evidence / "main.arm.json"
        run(bicep, "build", str(source), "--outfile", str(adapter_input))
        run(py, str(HERE / "azure_arm_inventory.py"), str(adapter_input), str(inventory))
    else:
        adapter_input = evidence / "main.tf.json"
        run(py, str(HERE / "gcp_terraform_inventory.py"), str(source), str(inventory), str(adapter_input))
    return adapter_input, inventory


def main(argv: list[str]) -> int:
    args = argv[1:]
    platform = args.pop(0) if args and args[0] in SYSTEMS else "azure"
    system = SYSTEMS[platform]["system"]
    source = Path(args[0]) if args else SYSTEMS[platform]["source"]
    name = f"{system}-sc28"
    ap = REPO_ROOT / "assessment-plans" / name / "assessment-plan.json"
    ar = REPO_ROOT / "assessment-results" / name / "assessment-results.json"
    poam = REPO_ROOT / "plan-of-action-and-milestones" / system / "plan-of-action-and-milestones.json"
    evidence = REPO_ROOT / "evidence" / name

    opa = find_tool("OPA", [REPO_ROOT / "tools" / "opa.exe", REPO_ROOT / "tools" / "opa"], "opa")
    py = sys.executable
    evidence.mkdir(parents=True, exist_ok=True)

    adapter_input, inventory = build_inventory(platform, source, evidence, py)
    print(run(py, str(HERE / "oscal2policy.py"), str(ap), str(POLICY)), end="")

    results = evidence / "opa-results.json"
    started = now()
    opa_version = run(opa, "version").splitlines()[0].split(":", 1)[1].strip()
    checks = {}
    for check in json.loads((POLICY / "checks.json").read_text(encoding="utf-8")):
        out = json.loads(run(opa, "eval", "--format", "json", "-d", str(POLICY / "rego"),
                             "-i", str(inventory), f"data.{check['package']}.deny"))
        deny = out["result"][0]["expressions"][0]["value"]
        checks[check["check_id"]] = {"package": check["package"], "deny": sorted(deny, key=lambda d: d["id"])}
    write_json(results, {"opa_version": opa_version, "started": started, "ended": now(), "checks": checks})

    print(run(py, str(HERE / "result2oscal.py"), str(ap), str(POLICY / "checks.json"),
              str(inventory), str(results), str(ar), str(adapter_input)), end="")
    print(f"wrote {ar.relative_to(REPO_ROOT).as_posix()}")

    # 6. POA&M status only (dry run): run ar2poam.py yourself to add drafts.
    if poam.exists():
        print(run(py, str(HERE / "ar2poam.py"), "--dry-run", str(ar), str(poam)), end="")
    else:
        print(f"no POA&M yet: run automation/ar2poam.py {ar.relative_to(REPO_ROOT).as_posix()} "
              f"{poam.relative_to(REPO_ROOT).as_posix()} to create one")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
