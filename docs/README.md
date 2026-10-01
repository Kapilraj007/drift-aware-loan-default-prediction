# Sprint 1 documentation

These documents define the reproducible data boundary for the drift-aware loan
default project. The primary LendingClub source has now been acquired and
analyzed locally. The default UCI German Credit benchmark is also acquired and
verified; its separate adapter remains part of later model evaluation.

- [`data_provenance.md`](data_provenance.md) records verified source facts,
  licensing caveats, citations, and the acquisition evidence that must be
  captured locally.
- [`source_registry.csv`](source_registry.csv) is the machine-readable source
  registry. Its LendingClub and selected UCI rows link to completed
  acquisitions; blank fields remain only for unselected alternatives.
- [`data_dictionary.md`](data_dictionary.md) explains the logical feature
  schema and leakage controls.
- [`data_dictionary.csv`](data_dictionary.csv) is the machine-readable baseline
  dictionary with the six Sprint 1 columns.
- [`sprint1_data_flow.md`](sprint1_data_flow.md) defines the raw-to-Parquet and
  temporal-split contract used by training, inference, EDA, and drift tests.
- [`sprint1_completion_report.md`](sprint1_completion_report.md) records the
  measured real-data results and verification evidence for the completed run.
- [`sprint1_final_audit.md`](sprint1_final_audit.md) maps every Sprint 1 plan
  requirement to its implementation and evidence, and separates later-sprint
  work from the completion decision.

The documentation deliberately separates facts verified from source pages from
facts established by the local acquisition and real-data run, such as byte
sizes, row counts, download timestamp, and SHA-256 digests.
