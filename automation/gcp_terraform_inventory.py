"""GCP adapter: Terraform (main.tf) -> datastore inventory.

The GCP counterpart of azure_arm_inventory.py, and the only GCP-specific code
in the evidence path. It parses the Terraform configuration with python-hcl2
(no Terraform binary or cloud credentials needed) and writes the
technology-agnostic inventory defined by
policies/schemas/datastore-inventory.schema.json.

Mapping for google_firestore_database (documented in
component-definitions/gcp-firestore-sc28):
  encryption_at_rest.enabled  always true: Firestore encrypts all data before
                              it is written to disk, with no setting to turn
                              it off (Google-managed keys by default; CMEK
                              optional, chosen at database creation)
  tamper_evidence.enabled     always false: Firestore has no cryptographic
                              tamper-evidence (ledger) feature

It analyses the configuration, not deployed resources. Only `${var.x}`
interpolation is evaluated, using variable defaults; a variable without a
default is kept as the placeholder <x>. Modules and for_each/count on
datastore resources are not supported (the sample uses neither for them).

Usage: python automation/gcp_terraform_inventory.py <main.tf> <inventory.json> [<parsed.json>]
  <parsed.json>  optional: also write the parsed configuration (as evidence)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import hcl2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oscal_common import write_json  # noqa: E402

FIRESTORE = "google_firestore_database"


def unquote(value: Any) -> Any:
    """python-hcl2 keeps HCL quoting: '"abc"' -> 'abc'."""
    if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    return value


def blocks(config: dict[str, Any], kind: str) -> list[tuple[str, dict[str, Any]]]:
    """[(name, body)] for variable blocks, or [(type, {name: body})] for resources."""
    return [(unquote(k), v) for entry in config.get(kind, []) for k, v in entry.items()]


def interpolate(value: Any, variables: dict[str, str]) -> Any:
    value = unquote(value)
    if not isinstance(value, str):
        return value
    def var(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in variables:
            raise ValueError(f"interpolation not supported by this adapter: {m.group(0)}")
        return variables[name]
    return re.sub(r"\$\{var\.(\w+)\}", var, value)


def build_inventory(config: dict[str, Any]) -> dict[str, Any]:
    variables = {name: unquote(body["default"]) if "default" in body else f"<{name}>"
                 for name, body in blocks(config, "variable")}
    datastores = []
    for rtype, named in blocks(config, "resource"):
        if rtype != FIRESTORE:
            continue
        for _label, body in named.items():
            db = interpolate(body.get("name", "(default)"), variables)
            datastores.append({
                "id": db,
                "kind": "document-database",
                "encryption_at_rest": {"enabled": True},
                "tamper_evidence": {"enabled": False},
                "source": {
                    "platform": "gcp",
                    "resource_type": FIRESTORE,
                    "resource_id": f"projects/{variables.get('project_id', '<project_id>')}/databases/{db}",
                },
            })
    return {"datastores": sorted(datastores, key=lambda d: d["id"])}


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as f:
        config = hcl2.load(f)
    write_json(Path(argv[2]), build_inventory(config))
    if len(argv) == 4:
        write_json(Path(argv[3]), config)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
