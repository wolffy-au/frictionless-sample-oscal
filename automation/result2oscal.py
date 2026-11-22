"""result2oscal for OPA, in the style of C2P: OPA results -> OSCAL assessment results.

Inputs
  assessment plan   activities: Rule_Id -> objectives tested; reviewed-controls;
                    the OPA assessment asset; import-ssp
  SSP               inventory-items (asset-id) and implemented-requirements
  checks.json       from oscal2policy.py: rule_id <-> check_id
  inventory.json    the datastore inventory OPA evaluated
  opa-results.json  {started, ended, opa_version, checks: {check_id: {package, deny}}}
  adapter input     optional: the infrastructure definition the adapter read
                    (compiled ARM JSON, parsed Terraform), linked as evidence so
                    the chain runs definition -> inventory -> OPA results

Output: one assessment-results document with one result containing
  - one observation per rule, with a subject per inventory item (pass/fail in remarks)
    and relevant-evidence links to the adapter input, inventory and OPA results
  - one finding per objective in reviewed-controls: satisfied if every
    observation for an activity that tests the objective passed, else not-satisfied

Usage: python automation/result2oscal.py <assessment-plan.json> <checks.json>
           <inventory.json> <opa-results.json> <assessment-results.json> [<adapter-input>]
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oscal_common import (TRESTLE_NS, iter_objective_ids, load_model, prop_values,  # noqa: E402
                          resolve_href, trestle_href, write_json)


def rel_href(target: Path, from_doc: Path) -> str:
    return Path(os.path.relpath(target.resolve(), from_doc.resolve().parent)).as_posix()


def control_of(objective_id: str) -> str:
    """sc-28.1_obj-2 -> sc-28.1"""
    return objective_id.split("_obj")[0]


def main(argv: list[str]) -> int:
    if len(argv) not in (6, 7):
        print(__doc__)
        return 2
    ap_path, checks_path, inv_path, opa_path, out_path = (Path(a).resolve() for a in argv[1:6])
    source_path = Path(argv[6]).resolve() if len(argv) == 7 else None

    _, ap = load_model(ap_path)
    ssp_path = resolve_href(ap["import-ssp"]["href"], ap_path)
    _, ssp = load_model(ssp_path)
    checks = {c["rule_id"]: c for c in json.loads(checks_path.read_text(encoding="utf-8"))}
    inventory = json.loads(inv_path.read_text(encoding="utf-8"))
    opa = json.loads(opa_path.read_text(encoding="utf-8"))

    assets_by_id = {next(iter(prop_values(i, "asset-id", None)), None): i["uuid"]
                    for i in ssp["system-implementation"].get("inventory-items", [])}
    ir_by_control = {ir["control-id"]: ir["uuid"]
                     for ir in ssp["control-implementation"]["implemented-requirements"]}
    opa_tool = next(c["uuid"] for c in ap["assessment-assets"]["components"]
                    if c["title"] == "Open Policy Agent")
    task_by_activity = {a["activity-uuid"]: t["uuid"] for t in ap.get("tasks", [])
                        for a in t.get("associated-activities", [])}
    evidence = [
        {"href": rel_href(source_path, out_path),
         "description": "Infrastructure definition as read by the platform adapter (adapter input)."},
    ] if source_path else []
    evidence += [
        {"href": rel_href(inv_path, out_path),
         "description": "Datastore inventory produced by the platform adapter from the infrastructure definition."},
        {"href": rel_href(opa_path, out_path),
         "description": f"Raw OPA {opa['opa_version']} deny results, per check."},
    ]

    observations: list[dict[str, Any]] = []
    failed_by_objective: dict[str, list[str]] = {}
    obs_by_objective: dict[str, list[str]] = {}
    for act in ap["local-definitions"]["activities"]:
        for rule in prop_values(act, "Rule_Id"):
            check = checks[rule]
            deny = {d["id"]: d["msg"] for d in opa["checks"][check["check_id"]]["deny"]}
            if "" in deny:  # the policy rejected the inventory as a whole
                raise SystemExit(f"check {check['check_id']}: {deny['']}")
            subjects = []
            for ds in inventory["datastores"]:
                asset_id = ds.get("source", {}).get("resource_id", ds["id"])
                if asset_id not in assets_by_id:
                    raise SystemExit(f"datastore {ds['id']} ({asset_id}) is not an inventory-item in the SSP")
                subjects.append({
                    "subject-uuid": assets_by_id[asset_id],
                    "type": "inventory-item",
                    "title": ds["id"],
                    "remarks": f"fail: {deny[ds['id']]}" if ds["id"] in deny else "pass",
                })
            obs_uuid = str(uuid.uuid4())
            n_fail = len(deny)
            observations.append({
                "uuid": obs_uuid,
                "title": f"{rule} (check {check['check_id']})",
                "description": (f"OPA evaluated data.{check['package']}.deny over {len(inventory['datastores'])} "
                                f"datastore(s): {n_fail} non-compliant."),
                "props": [
                    {"name": "Rule_Id", "ns": TRESTLE_NS, "value": rule},
                    {"name": "Check_Id", "ns": TRESTLE_NS, "value": check["check_id"]},
                ],
                "methods": prop_values(act, "method", None) or ["TEST"],
                "types": ["control-objective"],
                "origins": [{
                    "actors": [{"type": "tool", "actor-uuid": opa_tool}],
                    "related-tasks": [{"task-uuid": task_by_activity[act["uuid"]]}],
                }],
                "subjects": subjects,
                "relevant-evidence": evidence,
                "collected": opa["ended"],
            })
            for objective in iter_objective_ids(act["related-controls"].get("control-objective-selections", [])):
                obs_by_objective.setdefault(objective, []).append(obs_uuid)
                failed_by_objective.setdefault(objective, [])
                failed_by_objective[objective] += [f"{rule}: {m}" for m in deny.values()]

    findings: list[dict[str, Any]] = []
    for objective in iter_objective_ids(ap["reviewed-controls"].get("control-objective-selections", [])):
        if objective not in obs_by_objective:
            continue  # no automated activity tests this objective
        failures = failed_by_objective[objective]
        state = "not-satisfied" if failures else "satisfied"
        finding: dict[str, Any] = {
            "uuid": str(uuid.uuid4()),
            "title": f"{objective}: {state}",
            "description": ("; ".join(failures) if failures
                            else "All automated checks for this objective passed."),
            "target": {
                "type": "objective-id",
                "target-id": objective,
                "status": {"state": state},
            },
            "related-observations": [{"observation-uuid": u} for u in obs_by_objective[objective]],
        }
        if control_of(objective) in ir_by_control:
            finding["implementation-statement-uuid"] = ir_by_control[control_of(objective)]
        findings.append(finding)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ar = {"assessment-results": {
        "uuid": str(uuid.uuid4()),
        "metadata": {
            "title": f"Assessment Results: {ssp['system-characteristics']['system-name']}, SC-28 + SC-28(1) automated checks",
            "last-modified": now,
            "version": now,
            "oscal-version": "1.2.1",
            "remarks": "Generated by automation/result2oscal.py; regenerate with automation/run_assessment.py. UUIDs and timestamps change on every run.",
        },
        "import-ap": {"href": trestle_href(ap_path)},
        "results": [{
            "uuid": str(uuid.uuid4()),
            "title": "Automated SC-28 checks of the infrastructure definition",
            "description": ("OPA policies selected by the assessment plan, evaluated against the datastore "
                            "inventory produced from the infrastructure definition."),
            "start": opa["started"],
            "end": opa["ended"],
            "reviewed-controls": ap["reviewed-controls"],
            "observations": observations,
            "findings": findings,
        }],
    }}
    write_json(out_path, ar)
    for f in findings:
        print(f["title"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
