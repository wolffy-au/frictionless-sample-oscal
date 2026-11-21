# METADATA
# title: Data at rest is encrypted
# description: >-
#   Every data store in the inventory must report encryption_at_rest.enabled = true.
#   A missing or non-boolean value is non-compliant: the adapter that builds the
#   inventory is responsible for applying platform defaults.
#   Input contract: policies/schemas/datastore-inventory.schema.json
# custom:
#   check_id: encryption_at_rest
package datastores.encryption_at_rest

import rego.v1

# One result per non-compliant data store, keyed by its id so results can be
# turned into per-subject observations.
deny contains result if {
	some ds in input.datastores
	not ds.encryption_at_rest.enabled == true
	result := {
		"id": ds.id,
		"msg": sprintf("datastore %q: encryption at rest is not enabled", [ds.id]),
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
