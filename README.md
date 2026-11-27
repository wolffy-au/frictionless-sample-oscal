# frictionless-sample-oscal

A thin, end-to-end [OSCAL](https://pages.nist.gov/OSCAL/) steel thread for one
control and one enhancement, NIST SP 800-53 **SC-28** (protection of
information at rest) and **SC-28(1)** (cryptographic protection). It runs
from the NIST catalog through to a plan of action and milestones (POA&M),
for two example systems:

- [frictionless-sample-azure](https://github.com/wolffy-au/frictionless-sample-azure):
  Azure Static Web App + Azure SQL Database
- [frictionless-sample-gcp](https://github.com/wolffy-au/frictionless-sample-gcp):
  Firebase Hosting + Cloud Firestore

The checks are written once, technology-agnostic, in OPA/Rego. A small
adapter per platform turns each sample's infrastructure definition (Bicep or
Terraform) into a neutral datastore inventory, and C2P-style scripts turn the
OPA results into OSCAL assessment results.

Built with [compliance-trestle](https://github.com/oscal-compass/compliance-trestle)
5.2.1 (OSCAL 1.2.1) and [Open Policy Agent](https://www.openpolicyagent.org/).

## The thread

The overview diagram is [oscal-diagrams/steel-thread.puml](oscal-diagrams/steel-thread.puml)
(PlantUML).

| Step | OSCAL model | Path | Holds |
| --- | --- | --- | --- |
| 1 | Catalog | `catalogs/nist-800-53-sc28` | SC-28 and SC-28(1), extracted from the NIST catalog by deletion only |
| 2a | Profile | `profiles/sc28-moderate` | The NIST MODERATE baseline, extracted the same way |
| 2b | Profile | `profiles/sc28-org` | Organisation decisions: parameter values, a constraint, added guidance |
| 3a | Component definition | `component-definitions/datastore-checks` | Technology-agnostic rules and their OPA checks (`Rule_Id` -> `Check_Id`) |
| 3b | Component definition | `component-definitions/azure-sql-sc28` | How Azure SQL Database meets the controls, reusing 3a's rules |
| 3c | Component definition | `component-definitions/gcp-firestore-sc28` | The same for Cloud Firestore |
| 4 | System security plan | `system-security-plans/sample-{azure,gcp}` | The system's selections, inventory and implementation status |
| 5 | Assessment plan | `assessment-plans/sample-{azure,gcp}-sc28` | Which rules are tested, and which objectives each result counts for |
| 6 | Assessment results | `assessment-results/sample-{azure,gcp}-sc28` | Generated from an OPA run, with evidence in `evidence/` |
| 7 | POA&M | `plan-of-action-and-milestones/sample-{azure,gcp}` | The open risk and what is being done about it |

Each decision lives in exactly one layer: NIST's text in 1 and 2a,
organisation-wide values in 2b, platform behaviour in 3b/3c, system choices in
the SSP, test methods in the assessment plan, and check logic only in the Rego.

## Results

Both systems give the same result: data is encrypted at rest
(`sc-28.1_obj-1` satisfied), but stored data is not tamper-evident, so
`sc-28.1_obj-2` and `sc-28_obj` are not satisfied. Their POA&Ms differ:

- **sample-azure**: planned fix, recreate the database as an Azure SQL ledger
  database.
- **sample-gcp**: Firestore has no tamper-evidence feature, and the sample's
  data is fixed public demo data, so the risk is accepted (deviation
  requested, pending approval).

## Repository layout

| Path | Contents |
| --- | --- |
| `catalogs/`, `profiles/`, `component-definitions/`, `system-security-plans/`, `assessment-plans/`, `assessment-results/`, `plan-of-action-and-milestones/` | The OSCAL models (a trestle workspace) |
| `policies/` | Rego checks and their tests, the datastore inventory schema, example inventories |
| `automation/` | Platform adapters and the C2P-style pipeline; see [automation/README.md](automation/README.md) |
| `evidence/` | Evidence the assessment results link to |
| `oscal-diagrams/` | PlantUML diagrams of the thread and of individual OSCAL models, plus two generic OSCAL resolution-mechanics diagrams (`nist-baseline-resolution`, `fedramp-combined-resolution`: baseline tailoring and FedRAMP combining, not tied to SC-28 specifically) — moved here from `sample-data/oscal/` in frictionless-architect, then from `diagrams/` to `oscal-diagrams/` (ADR-0052, frictionless-architect) to make room for the generator-owned ArchiMate model below |
| `architecture/` | A standalone ArchiMate model (ADR-0052, frictionless-architect, not part of this repository's own OSCAL thread), kept in its own subdirectory so it's not confused with the OSCAL/trestle content above: `elements.yaml`/`relationships.yaml`/`views.yaml`, the common structure shared by `sample-azure`/`sample-gcp` plus NIST SC-28(1) modeled against it with the Open Group's risk-and-security-overlay stereotypes. Its `diagrams/` is entirely generator-owned (`modelling_specification.cli render`'s orphan-sweep deletes anything under it not produced from `views.yaml` — see `architecture/ARCHIMATE.md`) |

## Getting started

Prerequisites: Python 3.12+ and [Poetry](https://python-poetry.org/);
[OPA](https://www.openpolicyagent.org/docs/latest/#running-opa) (place it at
`tools/opa.exe` or put `opa` on PATH; see `.gitignore` for the version and
checksum); for Azure, the [Bicep CLI](https://learn.microsoft.com/azure/azure-resource-manager/bicep/install).
Terraform is not needed: the GCP adapter parses `main.tf` with python-hcl2.

```
poetry install
git clone https://github.com/wolffy-au/frictionless-sample-azure ../sample-azure
git clone https://github.com/wolffy-au/frictionless-sample-gcp ../sample-gcp

poetry run trestle validate -a              # validate every OSCAL model
opa test policies/datastores                # run the Rego unit tests
poetry run python automation/run_assessment.py azure   # or: gcp
```

The two sample repositories are expected next to this one, as `sample-azure`
and `sample-gcp` (the layout of `third_party/` in frictionless-architect, where
this repository is `sample-oscal`). `run_assessment.py` reads
`../sample-azure/main.bicep` or `../sample-gcp/main.tf` by default; pass another path as the second argument. Each run writes new
assessment results (new uuids and timestamps), so commit them only when you
mean to record a run. It ends with a POA&M status report and never edits the
POA&M; `automation/ar2poam.py` drafts POA&M items for new failures.

## Limitations

- It assesses the **infrastructure definitions**, not deployed resources.
- Only SC-28 and SC-28(1) are covered; the samples are really Low-impact
  systems, treated as Moderate because that is the first baseline with SC-28.
- Risk ratings, dates and owners in the POA&Ms are placeholders.

## Licence

[GNU AGPL v3.0](LICENSE), as for the two sample repositories.
