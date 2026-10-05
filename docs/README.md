# Documentation index

## Showcase operation and governance

- [`architecture.md`](architecture.md) maps local browser/API/artifact
  components to Neon pooled and direct endpoints.
- [`rbac.md`](rbac.md) records the role-permission matrix and the migration plus
  seed workflow for catalogue changes.
- [`full_stack_contract.md`](full_stack_contract.md) maps every UI feature to
  its API endpoint, permission, and required evidence.
- [`showcase_walkthrough.md`](showcase_walkthrough.md) is the six-minute,
  role-by-role presentation script and caveat list.
- [`verification_report.md`](verification_report.md) is the evidence log. It is
  the authority for which commands were actually run and which live checks
  remain unverified.
- [`audit_baseline.md`](audit_baseline.md) records findings F1-F13 and their
  planned repair phases.

## Data and research lineage

- [`data_provenance.md`](data_provenance.md) records source facts, licensing
  caveats, citations, and local acquisition evidence.
- [`source_registry.csv`](source_registry.csv) is the machine-readable source
  registry.
- [`data_dictionary.md`](data_dictionary.md) and
  [`data_dictionary.csv`](data_dictionary.csv) define the feature schema and
  leakage controls.
- [`sprint1_data_flow.md`](sprint1_data_flow.md) documents the raw-to-Parquet
  and temporal-split contract used by training, inference, EDA, and drift.

The sprint reports are historical evidence. Where they describe the removed
container topology, their notes point readers to the current local plus Neon
workflow in the repository README.
