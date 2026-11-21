"""Azure adapter: ARM template JSON -> datastore inventory.

This is the only Azure-specific code in the evidence path. It reads the ARM
JSON that `az bicep build` produces and writes the technology-agnostic
inventory defined by policies/schemas/datastore-inventory.schema.json, which
the Rego checks evaluate.

Mapping for Microsoft.Sql/servers/databases (documented in
component-definitions/azure-sql-sc28):
  encryption_at_rest.enabled  true unless a .../transparentDataEncryption
                              resource sets properties.state = Disabled
                              (Azure enables TDE by default)
  tamper_evidence.enabled     properties.isLedgerOn == true (off by default)

It analyses the template, not deployed resources. Only the ARM expressions
needed to name resources are evaluated (parameters, format, concat,
uniqueString, resourceGroup); uniqueString(...) is kept as the placeholder
<uniqueString>, because its value is only known at deployment. Not supported:
nested child resources and copy loops (az bicep build emits neither for the
sample).

Usage: python automation/azure_arm_inventory.py <template.json> <inventory.json>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oscal_common import write_json  # noqa: E402

SQL_DB = "microsoft.sql/servers/databases"
SQL_TDE = "microsoft.sql/servers/databases/transparentdataencryption"

_TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?\d+)|(?P<id>[A-Za-z_]\w*)|(?P<op>[(),.\[\]]))")


class ArmExpression:
    """Evaluates the small subset of ARM template expressions used in names."""

    def __init__(self, parameters: dict[str, Any]):
        self.parameters = parameters

    def value(self, raw: Any) -> Any:
        if not isinstance(raw, str):
            return raw
        if raw.startswith("[["):
            return raw[1:]
        if raw.startswith("[") and raw.endswith("]"):
            self.tokens = [m for m in _TOKEN.finditer(raw[1:-1]) if m.group().strip()]
            self.pos = 0
            result = self._expr()
            if self.pos != len(self.tokens):
                raise ValueError(f"unparsed ARM expression: {raw}")
            return result
        return raw

    def _next(self) -> re.Match[str]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _peek(self, op: str) -> bool:
        return self.pos < len(self.tokens) and self.tokens[self.pos].group("op") == op

    def _expr(self) -> Any:
        tok = self._next()
        if tok.group("str") is not None:
            val: Any = tok.group("str")[1:-1].replace("''", "'")
        elif tok.group("num") is not None:
            val = int(tok.group("num"))
        elif tok.group("id") is not None:
            name = tok.group("id")
            self._expect("(")
            args = []
            while not self._peek(")"):
                args.append(self._expr())
                if self._peek(","):
                    self._next()
            self._expect(")")
            val = self._call(name, args)
        else:
            raise ValueError(f"unexpected token {tok.group()!r}")
        while self._peek(".") or self._peek("["):
            if self._next().group("op") == ".":
                key = self._next().group("id")
            else:
                key = self._expr()
                self._expect("]")
            val = val[key]
        return val

    def _expect(self, op: str) -> None:
        if self._next().group("op") != op:
            raise ValueError(f"expected {op!r}")

    def _call(self, name: str, args: list[Any]) -> Any:
        fn = name.lower()
        if fn == "parameters":
            spec = self.parameters[args[0]]
            if "defaultValue" not in spec:
                return f"<{args[0]}>"
            return ArmExpression(self.parameters).value(spec["defaultValue"])
        if fn == "format":
            return re.sub(r"\{(\d+)\}", lambda m: str(args[1 + int(m.group(1))]), args[0])
        if fn == "concat":
            return "".join(str(a) for a in args)
        if fn == "uniquestring":
            return "<uniqueString>"
        if fn == "resourcegroup":
            return {"id": "<resourceGroup().id>", "name": "<resourceGroup().name>", "location": "<resourceGroup().location>"}
        raise ValueError(f"ARM function not supported by this adapter: {name}()")


def build_inventory(template: dict[str, Any]) -> dict[str, Any]:
    arm = ArmExpression(template.get("parameters", {}))
    resources = template.get("resources", [])
    if isinstance(resources, dict):  # languageVersion 2.0 symbolic names
        resources = list(resources.values())

    tde_disabled: set[str] = set()
    for res in resources:
        if res["type"].lower() == SQL_TDE:
            db_name = arm.value(res["name"]).rsplit("/", 1)[0]
            if str(res.get("properties", {}).get("state", "Enabled")).lower() == "disabled":
                tde_disabled.add(db_name)

    datastores = []
    for res in resources:
        if res["type"].lower() != SQL_DB:
            continue
        name = arm.value(res["name"])
        db = name.rsplit("/", 1)[-1]
        if db.lower() == "master":
            continue
        props = res.get("properties", {})
        datastores.append({
            "id": db,
            "kind": "relational-database",
            "encryption_at_rest": {"enabled": name not in tde_disabled},
            "tamper_evidence": {"enabled": props.get("isLedgerOn") is True},
            "source": {
                "platform": "azure",
                "resource_type": "Microsoft.Sql/servers/databases",
                "resource_id": name,
            },
        })
    return {"datastores": sorted(datastores, key=lambda d: d["id"])}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    import json
    template = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    write_json(Path(argv[2]), build_inventory(template))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
