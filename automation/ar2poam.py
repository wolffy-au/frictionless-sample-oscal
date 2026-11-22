"""ar2poam: keep a POA&M in step with the latest assessment results.

Does the automatable half of POA&M maintenance and never changes what people
wrote (risk ratings, remediations, milestones, status):

  objective not-satisfied, no open POA&M item for it
      -> add a DRAFT: copy the finding and its observations, add a risk with
         status "investigating" and a poam-item, both titled "DRAFT: ..."
  objective not-satisfied, open item exists  -> report "still failing"
  objective satisfied, open item exists      -> report "candidate for closure"
                                               (a person closes the risk)

Findings are matched on their objective (target-id), not on uuids, because
every assessment run creates new uuids. An item is open while any of its
related risks has a status other than "closed".

The POA&M stays self-contained: copied observations keep their uuids, the
assessment tool they name is copied into local-definitions, and their
references to assessment-plan tasks are dropped (the POA&M does not import
the AP). If the POA&M file does not exist it is created, importing the SSP.

Usage: python automation/ar2poam.py [--dry-run] <assessment-results.json> <poam.json>
"""
from __future__ import annotations

import copy
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oscal_common import load_model, resolve_href, write_json  # noqa: E402


def new_poam(ar_path: Path, ap_path: Path, ap: dict[str, Any]) -> dict[str, Any]:
    ssp_path = resolve_href(ap["import-ssp"]["href"], ap_path)
    _, ssp = load_model(ssp_path)
    name = ssp["system-characteristics"]["system-name"]
    return {
        "uuid": str(uuid.uuid4()),
        "metadata": {
            "title": f"POA&M: {name}",
            "last-modified": now(),
            "version": "0.1.0",
            "oscal-version": "1.2.1",
            "remarks": f"Created by automation/ar2poam.py from {ar_path.name}. Complete the DRAFT risks and items by hand.",
        },
        "import-ssp": copy.deepcopy(ap["import-ssp"]),
        "system-id": ssp["system-characteristics"]["system-ids"][0],
        "poam-items": [],
    }


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_items_by_objective(poam: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    findings = {f["uuid"]: f for f in poam.get("findings", [])}
    risks = {r["uuid"]: r for r in poam.get("risks", [])}
    result: dict[str, list[dict[str, Any]]] = {}
    for item in poam.get("poam-items", []):
        statuses = [risks[r["risk-uuid"]]["status"] for r in item.get("related-risks", []) if r["risk-uuid"] in risks]
        if statuses and all(s == "closed" for s in statuses):
            continue
        for rf in item.get("related-findings", []):
            if rf["finding-uuid"] in findings:
                result.setdefault(findings[rf["finding-uuid"]]["target"]["target-id"], []).append(item)
    return result


def add_draft(poam: dict[str, Any], finding: dict[str, Any], result: dict[str, Any], ap: dict[str, Any]) -> str:
    objective = finding["target"]["target-id"]
    risk_uuid, item_uuid = str(uuid.uuid4()), str(uuid.uuid4())

    obs_by_uuid = {o["uuid"]: o for o in result.get("observations", [])}
    have_obs = {o["uuid"] for o in poam.get("observations", [])}
    obs_uuids = [r["observation-uuid"] for r in finding.get("related-observations", [])]
    for ou in obs_uuids:
        if ou in have_obs:
            continue
        obs = copy.deepcopy(obs_by_uuid[ou])
        for origin in obs.get("origins", []):
            origin.pop("related-tasks", None)
            for actor in origin.get("actors", []):
                copy_tool(poam, ap, actor["actor-uuid"])
        poam.setdefault("observations", []).append(obs)

    # Reuse the finding if this run's copy is already in the POA&M (e.g. the same
    # AR applied again after its risk was closed); uuids must stay unique.
    f = next((x for x in poam.get("findings", []) if x["uuid"] == finding["uuid"]), None)
    if f is None:
        f = copy.deepcopy(finding)
        f["related-risks"] = []
        poam.setdefault("findings", []).append(f)
    f.setdefault("related-risks", []).append({"risk-uuid": risk_uuid})

    poam.setdefault("risks", []).append({
        "uuid": risk_uuid,
        "title": f"DRAFT: {objective} not satisfied",
        "description": finding["description"],
        "statement": "DRAFT: describe the risk to this system if the objective stays unmet.",
        "status": "investigating",
        "related-observations": [{"observation-uuid": ou} for ou in obs_uuids],
    })
    poam["poam-items"].append({
        "uuid": item_uuid,
        "title": f"DRAFT: remediate {objective}",
        "description": f"Opened automatically from finding '{finding['title']}'. Add the remediation, milestones and deadline.",
        "related-findings": [{"finding-uuid": f["uuid"]}],
        "related-observations": [{"observation-uuid": ou} for ou in obs_uuids],
        "related-risks": [{"risk-uuid": risk_uuid}],
    })
    return item_uuid


def copy_tool(poam: dict[str, Any], ap: dict[str, Any], actor_uuid: str) -> None:
    comps = poam.setdefault("local-definitions", {}).setdefault("components", [])
    if any(c["uuid"] == actor_uuid for c in comps):
        return
    for c in ap.get("assessment-assets", {}).get("components", []):
        if c["uuid"] == actor_uuid:
            comps.append(copy.deepcopy(c))


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    args = [a for a in argv[1:] if a != "--dry-run"]
    if len(args) != 2:
        print(__doc__)
        return 2
    ar_path, poam_path = Path(args[0]).resolve(), Path(args[1]).resolve()

    _, ar = load_model(ar_path)
    ap_path = resolve_href(ar["import-ap"]["href"], ar_path)
    _, ap = load_model(ap_path)
    result = ar["results"][-1]  # the latest result

    if poam_path.exists():
        _, poam = load_model(poam_path)
    else:
        poam = new_poam(ar_path, ap_path, ap)

    open_items = open_items_by_objective(poam)
    state_of = {f["target"]["target-id"]: f["target"]["status"]["state"] for f in result.get("findings", [])}
    changed = False
    for finding in result.get("findings", []):
        objective = finding["target"]["target-id"]
        items = open_items.get(objective, [])
        titles = ", ".join(f"'{i['title']}'" for i in items)
        if state_of[objective] == "not-satisfied" and items:
            print(f"{objective}: still failing, tracked by {titles}")
        elif state_of[objective] == "not-satisfied":
            item = add_draft(poam, finding, result, ap)
            changed = True
            print(f"{objective}: NEW failure, added draft poam-item {item}")
        elif items:
            print(f"{objective}: satisfied, tracked by {titles}")
        else:
            print(f"{objective}: satisfied, nothing to do")

    # An open item is a closure candidate when every objective it tracks was
    # assessed in this run and is now satisfied.
    tracked: dict[str, tuple[str, set[str]]] = {}
    for objective, items in open_items.items():
        for i in items:
            tracked.setdefault(i["uuid"], (i["title"], set()))[1].add(objective)
    for title, objectives in tracked.values():
        if all(state_of.get(o) == "satisfied" for o in objectives):
            print(f"candidate for closure: '{title}' ({', '.join(sorted(objectives))} now satisfied)")

    if changed and not dry_run:
        poam["metadata"]["last-modified"] = now()
        write_json(poam_path, {"plan-of-action-and-milestones": poam})
        print(f"wrote {poam_path}")
    elif changed:
        print("dry run: POA&M not written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
