# sample-oscal — ArchiMate model

`elements.yaml` / `relationships.yaml` / `views.yaml` in this directory are a
**standalone** ArchiMate model for `sample-oscal` (ADR-0052's second
extension), built and validated the same way as `sample-azure` / `sample-gcp`:

```bash
cd platform
FRICTIONLESS_MODEL_DIR=../third_party/sample-oscal \
FRICTIONLESS_THIRD_PARTY_DIR=<any existing empty dir> \
  poetry run python -m modelling_specification.cli validate
```

This file (not part of the upstream `sample-oscal` repo before this change —
see `README.md` for that) documents the model's two parts and, in particular,
the pattern for adding more controls without restructuring it.

## `diagrams/` is generator-owned — upstream content lives in `oscal-diagrams/`

`modelling_specification.cli render`'s orphan-sweep deletes anything under
`<FRICTIONLESS_MODEL_DIR>/diagrams/` that isn't produced from `views.yaml` —
`DIAGRAMS = HERE / "diagrams"` is a fixed path, not configurable per-repo. This
submodule's own upstream content (the steel-thread, catalog/profile/
component-definition PlantUML) used to live in `diagrams/` too, from before
this ArchiMate model existed, and a first `render` run here deleted it before
it was restored from git. It was moved to a sibling `oscal-diagrams/` (this
submodule's own flat, plain-noun top-level naming — `catalogs/`, `profiles/`,
`policies/`, `evidence/`, …) so `diagrams/` is now entirely generator-owned,
same as `sample-azure`'s and `sample-gcp`'s always were. **Never put
hand-authored or upstream-vendored content under this directory's
`diagrams/`** — anything that isn't a `views.yaml` output will eventually be
swept away.

## 1. Common core

`sample-azure` and `sample-gcp` are each a complete small web app on a
different cloud, modeled as its own standalone ArchiMate model. Their
`elements.yaml` files overlap almost completely in *structure* — a
static-site-hosting Node serving a Frontend, a managed-database Node holding
one seeded collection/table, the Visitor's browser, and an identical
Business-layer visitor journey (`biz-visitor` → `biz-view-demo-items` →
`biz-website` → `bo-demo-item` → `rep-demo-items-table`, verbatim in both)
— and differ only in provider-specific naming and in one real architectural
difference (Azure routes through a separate Functions API tier; GCP's
Frontend talks to Firestore directly).

The elements in this model's "1. Common core" section are that overlap,
re-abstracted provider-neutral (`node-database` not "Azure SQL Server" /
"Cloud Firestore", `artifact-demo-items-store` not "appdb" / "(default)",
etc.) — not a new, different model, and not a merge of the two: anything
that didn't match between the two samples (the API-tier split, provider SDKs,
Firestore security-rules artifacts) was left out rather than approximated.
This core is what the risk & security overlay below is modeled *against* —
it stands in for "the common part of any small app with a hosted frontend
and a managed datastore", which is also the part most catalog controls that
concern data at rest, transport, or access actually talk about.

## 2. Risk & security overlay, and how to add the next control

Section 2 applies the Open Group's "ArchiMate for Risk and Security Overlay"
stereotypes to existing ArchiMate concepts — **no new element types**, per
pyArchimate's metamodel (there is no native `Risk`/`Vulnerability`/
`ThreatEvent`/`Control` `ArchiType`; only `Requirement` already exists). The
mapping used here, and the legal relationships pyArchimate's relationship
matrix accepts for each (checked against `check_valid_relationship` /
`get_default_rel_type` before anything was written):

| Risk-overlay role | Base ArchiMate type | `props.stereotype` |
|---|---|---|
| Risk | `Driver` | `Risk` |
| Vulnerability | `Assessment` | `Vulnerability` |
| Threat Event | `TechnologyEvent`¹ | `ThreatEvent` |
| Requirement | `Requirement` | — (already native) |
| Control | `CourseOfAction` | `Control` |

¹ Pick the layer `Event` that matches where the threat actually acts — this
model's one threat event (media theft/exfiltration) acts on the Technology
layer; a social-engineering threat event elsewhere would be a
`BusinessEvent` instead. `Triggering` is **not** legal from an `Event` onto
a `Driver`/`Assessment` (it's reserved for behavioural sequencing between
same-layer elements) — the chain below uses `Influence` for
"triggers"/"gives rise to" instead, which *is* legal, and reads the same on
the diagram.

### Two tiers, and why

- **Risk-overlay core — scenario-based, standard-agnostic.** One
  `Vulnerability` (`vuln-unprotected-data-at-rest`, shared), but a
  confidentiality and an integrity concern each get their *own* `ThreatEvent`
  and `Risk` (`threat-media-theft-exfiltration` /
  `risk-unauthorized-disclosure-data-at-rest`, and
  `threat-raw-storage-tampering` /
  `risk-unauthorized-modification-data-at-rest`): they're genuinely
  different threat actions (reading vs. tampering) with different
  mitigation status in practice, even though one vulnerability (no
  cryptographic protection at all) gives rise to both. Each is
  `Association`/`Influence`-linked to the common-core asset(s) it concerns.
  These model the *real-world* risk, independent of which catalog's
  control addresses it. **Reuse these across controls and standards** — a
  later APRA CPS 234 requirement about encryption of data at rest mitigates
  the *same* Risk(s), it does not get its own copy. A control that only
  addresses one concern (e.g. a confidentiality-only encryption mandate
  with no integrity provision) should only `Influence` the matching Risk,
  not both — see SC-28(1) below for a control that legitimately addresses
  both, and what to do when real-world evidence says one side isn't
  actually achieved yet.
- **Per-control — one `Requirement` + one `Control` per catalog control.**
  `req-nist80053-sc-28-1` / `control-nist80053-sc-28-1` here. The `Control`
  `Realization`s its `Requirement`, `Influence`s (mitigates) each `Risk` its
  control text actually addresses, and is `Realization`-ed by whichever
  common-core element actually implements it (`sys-database-engine` here,
  since encryption at rest is implemented at the database-engine layer).
  The `Requirement` is `Association`-ed to the common-core asset(s) it
  applies to. If a control's real-world implementation only partly closes
  a `Risk` it mitigates, say so on the relationship itself — label it
  `"mitigates (partial)"` and record why in `props.status` — rather than
  modeling it the same as a `Risk` the control fully closes. SC-28(1) here
  does exactly that: it mitigates the integrity `Risk` only partially,
  because (per sample-oscal's own README.md "Results") neither sample
  system's storage is actually tamper-evident yet.

### Naming and tagging convention

- Risk-overlay core ids are scenario-based, no standard prefix:
  `risk-<scenario-slug>`, `vuln-<scenario-slug>`, `threat-<scenario-slug>`.
- Per-control ids carry the source standard: `req-<std-slug>-<control-id-kebab>`,
  `control-<std-slug>-<control-id-kebab>` — e.g. `req-nist80053-sc-28-1`,
  and (for a future APRA control) `req-cps234-<control-id-kebab>`.
- Every per-control `Requirement` and `Control` carries
  `props.source-standard` (a short machine-stable catalog name, e.g.
  `"NIST-SP-800-53-Rev5"`, `"APRA-CPS-234"`) and `props.control-id` (the
  catalog's own id/label verbatim, e.g. `"SC-28(1)"`) — not encoded only in
  the kebab id, so a view, a report, or a future `conventions.yaml` rule can
  group or filter by standard without parsing ids.

### Adding another control

1. **Does an existing Risk/Vulnerability/Threat Event already describe the
   scenario this control addresses?** If so, reuse those ids — do not create
   new ones. Most controls in a given family (e.g. every SC-28 enhancement)
   mitigate variations on the same handful of underlying risks.
2. If genuinely new, add one `Driver`/`Assessment`/`TechnologyEvent` (or
   other-layer `*Event`) triple following the pattern above, `Association`-
   or `Influence`-linked to whichever common-core element(s) it concerns.
3. Add the `Requirement` + `CourseOfAction` pair for the control itself,
   tagged with its `source-standard` / `control-id`, `Realization`-linked to
   each other, `Influence`-linked (mitigates) to the Risk, and
   `Association`-linked to the asset(s) it applies to.
4. `Realization`-link whichever common-core (or, for a provider-specific
   control, a provider-specific) element actually implements the control.
5. Re-run `validate.py` (`check_valid_relationship` will reject an illegal
   relationship type before it ever reaches the written model) and
   `check_derived.py`.
6. If the new control's `Requirement`/`Control` pair should show on the risk
   overlay view, nothing needs to change there — `view-sample-oscal-risk-overlay`
   sweeps by `include_types` (`Driver`, `Assessment`, `TechnologyEvent`,
   `Requirement`, `CourseOfAction`, plus the common-core technology types),
   not by an explicit member list, so a correctly-typed new element appears
   on it automatically.

### A note on the control actually modeled here

**SC-28(1) Cryptographic Protection** is the control modeled — the one
`sample-oscal`'s own vendored `catalogs/nist-800-53-sc28/catalog.json` slice
already scopes (it carries `sc-28` and `sc-28.1`, nothing further of SC-28's
three enhancements), and its statement explicitly covers both confidentiality
(disclosure) and integrity (modification), reflected in this model's two
Risks rather than one. A different control family — say, `MP-8` Media
Downgrading — would need its own Risk-overlay core (its own
vulnerability/threat scenario, not the at-rest-encryption one modeled here),
added per the pattern above.
