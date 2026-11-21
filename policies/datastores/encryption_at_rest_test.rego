package datastores.encryption_at_rest_test

import rego.v1

import data.datastores.encryption_at_rest

ds(id, enc) := {
	"id": id,
	"kind": "relational-database",
	"encryption_at_rest": {"enabled": enc},
	"tamper_evidence": {"enabled": true},
}

test_encrypted_passes if {
	results := encryption_at_rest.deny with input as {"datastores": [ds("db1", true)]}
	count(results) == 0
}

test_not_encrypted_fails if {
	results := encryption_at_rest.deny with input as {"datastores": [ds("db1", false)]}
	results == {{"id": "db1", "msg": "datastore \"db1\": encryption at rest is not enabled"}}
}

test_missing_enabled_fails if {
	inp := {"datastores": [{"id": "db1", "kind": "relational-database", "encryption_at_rest": {}}]}
	results := encryption_at_rest.deny with input as inp
	{r.id | some r in results} == {"db1"}
}

test_missing_encryption_object_fails if {
	inp := {"datastores": [{"id": "db1", "kind": "relational-database"}]}
	results := encryption_at_rest.deny with input as inp
	{r.id | some r in results} == {"db1"}
}

test_non_boolean_fails if {
	results := encryption_at_rest.deny with input as {"datastores": [ds("db1", "true")]}
	{r.id | some r in results} == {"db1"}
}

test_only_noncompliant_reported if {
	inp := {"datastores": [ds("good", true), ds("bad", false)]}
	results := encryption_at_rest.deny with input as inp
	{r.id | some r in results} == {"bad"}
}

test_empty_inventory_passes if {
	results := encryption_at_rest.deny with input as {"datastores": []}
	count(results) == 0
}

test_missing_datastores_array_fails if {
	results := encryption_at_rest.deny with input as {}
	results == {{"id": "", "msg": "input has no datastores array"}}
}
