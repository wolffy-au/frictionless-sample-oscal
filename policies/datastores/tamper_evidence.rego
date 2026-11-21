# METADATA
# title: Data at rest is tamper-evident
# description: >-
#   Every data store in the inventory must report tamper_evidence.enabled = true,
#   i.e. changes are cryptographically recorded so unauthorized modification is
#   detectable. A missing or non-boolean value is non-compliant.
#   Input contract: policies/schemas/datastore-inventory.schema.json
# custom:
#   check_id: tamper_evidence
package datastores.tamper_evidence

import rego.v1

deny contains result if {
	some ds in input.datastores
	not ds.tamper_evidence.enabled == true
	result := {
		"id": ds.id,
		"msg": sprintf("datastore %q: tamper evidence is not enabled", [ds.id]),
	}
}

# Malformed input must not pass silently. A helper rule is used because
# `not is_array(input.datastores)` is undefined (not true) when the field is missing.
deny contains result if {
	not has_datastores_array
	result := {
		"id": "",
		"msg": "input has no datastores array",
	}
}

has_datastores_array if is_array(input.datastores)
