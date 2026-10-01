# Data provenance and redistribution policy

## Purpose and decision

Sprint 1 uses the Kaggle LendingClub mirror as the primary research input and
UCI Statlog German Credit as the default secondary benchmark. UCI Statlog
Australian Credit Approval is a documented alternative. Raw files are never
committed to this repository. Every local acquisition must be accompanied by a
timestamp, source locator, source-reported version, exact file name, byte size,
and SHA-256 digest before derived artifacts are treated as reproducible.

This document records source-page facts checked through **2026-09-28 UTC**. The
primary LendingClub archive was acquired on 2026-09-27, and the default UCI
German Credit benchmark was acquired and integrity-checked on 2026-09-28. Its
separate schema adapter remains part of the later cross-dataset model
evaluation. The source registry is [`source_registry.csv`](source_registry.csv),
and the exact local archive/input identities are recorded in
[`../data/raw/acquisition_manifest.csv`](../data/raw/acquisition_manifest.csv).

## Primary source

### LendingClub accepted loans via Kaggle mirror

- **Role:** model development, time-based validation, EDA, and drift-window
  construction.
- **Canonical mirror:** [All Lending Club loan data on Kaggle](https://www.kaggle.com/datasets/wordsforthewise/lending-club).
- **Source-page facts verified:** the page exposes
  `accepted_2007_to_2018Q4.csv.gz` and `rejected_2007_to_2018Q4.csv.gz`, shows
  dataset **Version 3**, and labels the dataset **CC0 Public Domain**. The
  uploader states that the accepted data came from LendingClub and that
  `int_rate` and `revol_util` had percent signs removed and were converted to
  numeric values.
- **Project use:** only the accepted-loan file is in scope. The rejected-loan
  file has no resolved repayment outcome and is not silently combined with the
  supervised target.
- **Outcome contract:** `Charged Off` and `Default` map to `1`; `Fully Paid`
  maps to `0`. All other statuses are excluded from training and counted in the
  run report.
- **Temporal contract:** `issue_d` is parsed as a calendar month and converted
  to a quarter for partitioning and time-ordered evaluation. It is not a model
  input.

**License and lineage caveat.** CC0 is the license label declared by the Kaggle
mirror page. It is not an independent legal determination about every upstream
right in LendingClub-originated records. Kaggle's current
[Terms of Use](https://www.kaggle.com/terms) also govern platform access, and
the mirror author notes that LendingClub download terms changed. Consequently:

1. acquire the archive through Kaggle's official CLI/API workflow after
   reviewing the page and applicable terms, authenticating when Kaggle requires
   it for the selected source;
2. do not redistribute the raw archive or derived row-level extracts from this
   repository without a separate rights review;
3. publish code, schemas, aggregate statistics, and cryptographic hashes rather
   than raw records; and
4. preserve the exact mirror URL and Kaggle version returned at acquisition,
   because a page label observed later is not proof of the downloaded snapshot.

The Sprint 1 archive was downloaded through the public Kaggle CLI dataset flow
with `kaggle-cli 2.2.4`. Kaggle reported **CC0-1.0** and served
`accepted_2007_to_2018Q4.csv.gz` as 392,582,231 bytes. The preserved archive and
decompressed pipeline input have separate SHA-256 digests in the acquisition
manifest. The project plan's approximate row count remains an expectation, not
provenance evidence; the ingest run computes the actual row count and status
inventory.

## Secondary benchmark

### UCI Statlog German Credit Data

- **Role:** default cross-dataset generalization benchmark. It is a separate
  benchmark adapter, not a drop-in replacement for LendingClub columns.
- **Canonical record:** [UCI Statlog German Credit Data](https://archive.ics.uci.edu/dataset/144/statlog+german+credit+data).
- **Persistent identifier and citation:** Hans Hofmann, *Statlog German Credit
  Data*, UCI Machine Learning Repository, 1994,
  [doi:10.24432/C5NC77](https://doi.org/10.24432/C5NC77).
- **Source-page facts verified:** 1,000 observations, 20 features, no missing
  values reported by UCI, files `german.data`, `german.data-numeric`, and
  `german.doc`, and a good/bad credit-risk target with an asymmetric cost
  matrix.
- **License reported by UCI:** [Creative Commons Attribution 4.0
  International](https://creativecommons.org/licenses/by/4.0/) (CC BY 4.0).
  Redistribution or adaptation must retain attribution, the DOI, a license
  link, and an indication of changes.
- **Methodological caveat:** this dataset's target, population, feature meanings,
  and decision costs differ from LendingClub. Results must be labeled as
  transfer/generalization evidence, not pooled training performance. Any label
  remapping must be explicit and tested.

**Acquired snapshot.** The official UCI ZIP was downloaded anonymously from
UCI's static dataset endpoint on 2026-09-28. The ZIP is 29,607 bytes with
SHA-256 `e12d9d5def6845c0622634a1cd2ab87fa470668c4298f1ec52a4e403376a435b`.
The selected `german.data` file is 79,793 bytes with SHA-256
`b21f3d81db8071257d5ff1deaeba1fd4303b62712e6fcc9715c7a86202cb5871`.
Structural validation found 1,000 rows, 20 predictors plus one target column,
no missing fields, and target counts of 700 class `1` and 300 class `2`. These
bytes are staged for later cross-dataset evaluation and are not mixed into the
Sprint 1 LendingClub feature store.

### Optional alternative: UCI Statlog Australian Credit Approval

- **Canonical record:** [UCI Statlog Australian Credit Approval](https://archive.ics.uci.edu/dataset/143/statlog+australian+credit+approval).
- **Persistent identifier and citation:** Ross Quinlan, *Statlog Australian
  Credit Approval*, UCI Machine Learning Repository, 1987,
  [doi:10.24432/C59012](https://doi.org/10.24432/C59012).
- **Source-page facts verified:** 690 observations, 14 features, missing values
  reported by UCI, anonymized attribute names/values, and file
  `australian.dat`.
- **License reported by UCI:** CC BY 4.0, with the same attribution and change
  notice obligations described above.
- **Use constraint:** select this instead of, not in addition to, the German
  benchmark unless the study protocol is amended. Record that choice in the
  experiment metadata before model comparison.

## Optional Kaggle competition source

The plan permits *Give Me Some Credit* as an alternative secondary source. Its
[official Kaggle competition page](https://www.kaggle.com/competitions/GiveMeSomeCredit)
describes prediction of serious financial distress within two years. It is not
the Sprint 1 default because competition data use is governed by the specific
competition rules in addition to Kaggle's Terms. Do not download, redistribute,
or use it until an authorized user records the exact accepted rules/version and
the permitted research and publication uses in `source_registry.csv`.

## Synthetic demo metadata

[Faker](https://faker.readthedocs.io/en/master/) may generate display-only names
and identifiers. Its official documentation describes it as a fake-data Python
package, documents deterministic seeding, warns that outputs can change across
patch versions, and reports an MIT license. The installed patch version, locale,
and seed must therefore be captured with each demo build. Faker values must
never enter training, target construction, temporal partitioning, or model
evaluation, and must never be represented as de-identification of real people.

## Reproducible acquisition record

For each downloaded artifact, add a row to the tracked manifest at
`data/raw/acquisition_manifest.csv` and fill all acquisition fields. Raw dataset
bytes remain ignored; the manifest itself is explicitly retained in version
control. A complete record contains:

- UTC timestamp in ISO 8601 format;
- authenticated source URL or API dataset reference;
- source-reported dataset version or persistent DOI;
- downloaded file name and byte size;
- SHA-256 of the bytes actually consumed by the pipeline;
- the license/rules text or URL reviewed at acquisition;
- acquiring operator or CI job identifier; and
- any extraction, decompression, renaming, or source-side transformation.

If the source page changes, the stored digest and acquisition record remain the
identity of the experiment input. A replacement file receives a new manifest
row and a new derived-data version; it must not overwrite the old identity.

## Citation block for publications

At minimum, cite the Kaggle mirror page and its recorded version for the primary
input. For a UCI benchmark, use the DOI citation supplied by UCI and state the
exact file used. Also cite this repository release or commit, the local source
digest, the preprocessing configuration, and the temporal windows so that an
external reader can reconstruct which bytes and decisions produced the result.
