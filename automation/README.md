# automation

Scripts that produce the steel thread's **assessment results** (step 6) from the
assessment plan, by evaluating the OPA/Rego checks against the sample Azure
deployment. They also keep the **POA&M** (step 7) in step with those results.

They follow the interface of [C2P (compliance-to-policy)](https://github.com/oscal-compass/compliance-to-policy),
which has no OPA plugin: `oscal2policy` selects the hand-written policies an
assessment needs, and `result2oscal` turns the policy engine's output into
OSCAL. Neither writes policy logic. The Rego in `policies/` is written and
unit-tested by hand.

## Run it

From the repo root:

```
poetry run python automation/run_assessment.py [path/to/main.bicep]
```

The default Bicep file is `../test-azure/main.bicep`, a clone of the
frictionless-sample-azure repo.

Prerequisites:

| Tool | Looked up in this order |
|---|---|
| Bicep CLI | `$BICEP`, `~/.azure/bin/bicep[.exe]` (installed by `az bicep install`), `bicep` on PATH |
| OPA | `$OPA`, `tools/opa.exe` (see `.gitignore` for the download URL and sha256), `opa` on PATH |
| Python | the Poetry environment (`compliance-trestle` is not imported; only the standard library is used) |

Afterwards, check the outputs with:

```
poetry run trestle validate -a
tools/opa.exe test policies/datastores
```

## Pipeline

```
main.bicep
  | 1. bicep build                         evidence/sample-azure-sc28/main.arm.json
  v
ARM JSON
  | 2. azure_arm_inventory.py (adapter)    evidence/sample-azure-sc28/inventory.json
  v
datastore inventory (policies/schemas/datastore-inventory.schema.json)
  |
  |   3. oscal2policy.py                   build/policy/rego/*.rego, build/policy/checks.json
  |      AP activities (Rule_Id)
  |      -> SSP component links -> 3b -> import-component-definitions -> 3a
  |      -> validation component: Rule_Id -> Check_Id
  |      -> policies/**/*.rego whose METADATA declares that check_id
  v
  | 4. opa eval data.<package>.deny        evidence/sample-azure-sc28/opa-results.json
  v
  | 5. result2oscal.py                     assessment-results/sample-azure-sc28/assessment-results.json
  v
OSCAL assessment results
  | 6. ar2poam.py --dry-run                (status report only; writes nothing)
  v
POA&M status: still failing / NEW failure / candidate for closure
```

`run_assessment.py` runs all six steps. The other scripts can also be run on
their own. Run one without arguments to see its usage.

## Keeping the POA&M up to date

A POA&M is mostly decisions: risk ratings, remediations, milestones, owners
and closure. People make those. `ar2poam.py` does only the bookkeeping, and
never changes what people wrote:

```
poetry run python automation/ar2poam.py [--dry-run] \
  assessment-results/sample-azure-sc28/assessment-results.json \
  plan-of-action-and-milestones/sample-azure/plan-of-action-and-milestones.json
```

| Latest result for an objective | POA&M has an open item for it? | What ar2poam does |
|---|---|---|
| not-satisfied | no | **adds a draft**: copies the finding and its observations, adds a risk with status `investigating` and a poam-item, both titled `DRAFT: ...` for a person to complete |
| not-satisfied | yes | reports "still failing", no change |
| satisfied | yes | reports "candidate for closure" once *every* objective the item tracks is satisfied. A person closes it by setting its risk's status to `closed`. |
| satisfied | no | nothing |

Findings are matched by objective (`target-id`), not uuid, because every run
creates new uuids. An item counts as open while any of its risks isn't
`closed`, so a closed item that fails again gets a new draft. Copied
observations keep their uuids. The assessment tool they name is copied into
the POA&M's `local-definitions`, and their links to assessment plan tasks are
dropped, so the POA&M stays self-contained: it imports only the SSP. If the
POA&M file doesn't exist, it's created.

## Scripts

| Script | Role | Technology-specific? |
|---|---|---|
| `run_assessment.py` | Runs the pipeline (the AP task "Run the automated SC-28 checks"). | Only in finding the Bicep CLI. |
| `azure_arm_inventory.py` | **Adapter**: maps ARM JSON to the neutral datastore inventory. For `Microsoft.Sql/servers/databases`: `encryption_at_rest.enabled` is true unless a `transparentDataEncryption` resource sets `state = Disabled`; `tamper_evidence.enabled` is true only if `isLedgerOn = true`. This mapping is also documented in the remarks of `component-definitions/azure-sql-sc28`. | Yes, the only Azure-specific code. |
| `oscal2policy.py` | Selects and stages the policies the assessment plan needs (see the pipeline above). Fails if a Rule_Id has no Check_Id, or a Check_Id has no policy. | No |
| `result2oscal.py` | Builds one result with one **observation** per rule, whose subjects are SSP inventory items with `pass` or `fail: <msg>`, plus links to the evidence files. It also adds one **finding** per objective in the AP's `reviewed-controls`. A finding is `satisfied` only if every observation from an activity testing that objective passed. Findings link to the SSP implemented-requirement for their control. | No |
| `ar2poam.py` | Keeps the POA&M in step with the latest result. See "Keeping the POA&M up to date" above. | No |
| `oscal_common.py` | Shared helpers: `trestle://` href resolution, props lookup, and writing JSON without a BOM (trestle rejects one). | No |

## Where each mapping lives

The scripts hold no compliance knowledge of their own. Every link they follow
comes from an OSCAL document or a policy file:

| Link | Defined in |
|---|---|
| which rules are tested, and which objectives each rule's result counts for | assessment plan: activity `Rule_Id` prop + `related-controls` |
| Rule_Id -> Check_Id | 3a `datastore-checks`: validation component props grouped by `rule_set_NN` |
| Check_Id -> Rego file and package | the policy's own `# METADATA` `custom.check_id` |
| datastore -> SSP inventory item | inventory `source.resource_id` == SSP inventory-item `asset-id` prop |
| objective -> SSP implemented-requirement | the objective id prefix (`sc-28.1_obj-2` -> `sc-28.1`) |

## Outputs and what to commit

| Path | Committed? | Notes |
|---|---|---|
| `assessment-results/sample-azure-sc28/` | yes | The record of one run. UUIDs and timestamps change every run, so re-run only when you mean to. |
| `evidence/sample-azure-sc28/` | yes | Evidence the AR's `relevant-evidence` links to. `opa-results.json` has run timestamps. |
| `build/policy/` | no (git-ignored) | Rebuilt on every run. |

## Limitations

- It assesses the **infrastructure definition**, not deployed resources. The
  "TDE enabled" result relies on Azure's default because the template doesn't
  declare TDE. Checking a running database (for example, verifying ledger
  digests) would be a separate EXAMINE activity.
- The adapter evaluates only the ARM expressions needed to name resources:
  `parameters`, `format`, `concat`, `uniqueString`, `resourceGroup`.
  `uniqueString(...)` is kept as the placeholder `<uniqueString>`, which the
  SSP's `asset-id` uses too. Nested child resources and copy loops aren't
  supported; `bicep build` emits neither for the sample.
- The check scripts take no parameters yet: nothing passes OSCAL parameter
  values (`Parameter_Id`) into the Rego.
- The current POA&M (`plan-of-action-and-milestones/sample-azure`) was
  written by hand before `ar2poam.py` existed. It follows the same rules,
  so `ar2poam.py` recognises its item as tracking `sc-28_obj` and
  `sc-28.1_obj-2`.
- `ar2poam.py` never closes items or changes a risk's status. It also
  ignores `subjects`: one item per objective, whichever datastores fail it.
