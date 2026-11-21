package datastores.tamper_evidence_test

import rego.v1

import data.datastores.tamper_evidence

ds(id, te) := {
	"id": id,
	"kind": "relational-database",
	"encryption_at_rest": {"enabled": true},
	"tamper_evidence": {"enabled": te},
}

test_tamper_evident_passes if {
	results := tamper_evidence.deny with input as {"datastores": [ds("db1", true)]}
	count(results) == 0
}

test_not_tamper_evident_fails if {
	results := tamper_evidence.deny with input as {"datastores": [ds("db1", false)]}
	results == {{"id": "db1", "msg": "datastore \"db1\": tamper evidence is not enabled"}}
}

test_missing_enabled_fails if {
	inp := {"datastores": [{"id": "db1", "kind": "relational-database", "tamper_evidence": {}}]}
	results := tamper_evidence.deny with input as inp
	{r.id | some r in results} == {"db1"}
}

test_missing_tamper_evidence_object_fails if {
	inp := {"datastores": [{"id": "db1", "kind": "relational-database"}]}
	results := tamper_evidence.deny with input as inp
	{r.id | some r in results} == {"db1"}
}

test_non_boolean_fails if {
	results := tamper_evidence.deny with input as {"datastores": [ds("db1", 1)]}
	{r.id | some r in results} == {"db1"}
}

test_only_noncompliant_reported if {
	inp := {"datastores": [ds("good", true), ds("bad", false)]}
	results := tamper_evidence.deny with input as inp
	{r.id | some r in results} == {"bad"}
}

test_empty_inventory_passes if {
	results := tamper_evidence.deny with input as {"datastores": []}
	count(results) == 0
}

test_missing_datastores_array_fails if {
	results := tamper_evidence.deny with input as {}
	results == {{"id": "", "msg": "input has no datastores array"}}
}
