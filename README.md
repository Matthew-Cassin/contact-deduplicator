# Contact Deduplicator

[![CI](https://github.com/Matthew-Cassin/contact-deduplicator/actions/workflows/ci.yml/badge.svg)](https://github.com/Matthew-Cassin/contact-deduplicator/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Types](https://img.shields.io/badge/types-mypy%20strict-brightgreen)

A Python library and CLI for detecting and merging duplicate contact records in CSV files, with a full audit trail of every merge decision.

## Installation

```bash
# Install directly from GitHub
pip install git+https://github.com/Matthew-Cassin/contact-deduplicator.git

# Or clone and install locally for development
git clone https://github.com/Matthew-Cassin/contact-deduplicator.git
cd contact-deduplicator
pip install -e .
```

This pulls in [`email-phone-validator`](https://github.com/Matthew-Cassin/email-phone-validator) automatically, which contact-deduplicator uses for email/phone validation and phone normalization.

## Quick Start

### 1. Basic Python usage

```python
from contact_deduplicator import ContactDeduplicator

deduplicator = ContactDeduplicator()
contacts = deduplicator.load_csv("contacts.csv")
result = deduplicator.deduplicate(contacts)

print(f"{result.total_records} records -> {result.unique_records} unique "
      f"({result.duplicates_found} duplicates merged)")

deduplicator.save_results(result, output_csv="deduplicated.csv", report_json="merge_report.json")
```

Against this repo's own [`tests/fixtures/sample_contacts.csv`](tests/fixtures/sample_contacts.csv) (5 rows: two "John Smith" entries, two "Jane Doe" / "J. Doe" entries, one standalone), this prints:

```
5 records -> 3 unique (2 duplicates merged)
```

### 2. CLI usage

```bash
contact-deduplicator tests/fixtures/sample_contacts.csv
```

```
Total records:     5
Duplicates found:  2
Unique contacts:   3
Validation issues: 5 (see merge_report.json)

Saved deduplicated contacts to deduplicated.csv
Saved merge report to merge_report.json
```

(The 5 validation issues are expected here -- every phone number in the sample data is missing its area code, e.g. `555-0123`, so none of them are *valid, complete* phone numbers on their own, even though two of them are exact duplicates of each other. See [Limitations](#limitations).)

With custom paths and options:

```bash
contact-deduplicator contacts.csv --output clean.csv --report audit.json --threshold 0.85 --verbose
```

### 3. Configuring the similarity threshold

`name_similarity_threshold` (Python) / `--threshold` (CLI) controls how similar two names must be, from `0.0` to `1.0`, to count as a fuzzy match. It only affects name matching -- exact email and exact phone matches are unaffected by it:

```python
from contact_deduplicator import ContactDeduplicator

# Looser: "Jane Doe" / "J. Doe" (71% similar) now counts as a match too
loose = ContactDeduplicator(name_similarity_threshold=0.65)

# Stricter: only near-identical names match
strict = ContactDeduplicator(name_similarity_threshold=0.98)
```

### 4. Reading the merge report

`merge_report.json` is the audit trail: every group that got merged, why, and the full statistics. From the sample data above:

```json
{
  "timestamp": "2026-08-07T21:18:10.765682+00:00",
  "statistics": {
    "total_records": 5,
    "unique_records": 3,
    "duplicates_found": 2,
    "validation_error_count": 5
  },
  "merge_actions": [
    {
      "primary_id": "row-1",
      "merged_ids": ["row-2"],
      "reason": "exact_email",
      "merged_contact": {
        "id": "row-1",
        "name": "John Smith",
        "email": "john@example.com",
        "phone": "(555) 555-0123",
        "company": "Acme Corp",
        "address": "123 Main Street",
        "completeness_score": 1.0
      }
    },
    {
      "primary_id": "row-3",
      "merged_ids": ["row-4"],
      "reason": "exact_phone",
      "merged_contact": {
        "id": "row-3",
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "phone": "555-0456",
        "company": "Tech Corp",
        "address": "456 Oak Avenue",
        "completeness_score": 1.0
      }
    }
  ],
  "validation_errors": ["row-1: Invalid phone: Invalid phone number for its region", "..."]
}
```

```python
import json

with open("merge_report.json") as f:
    report = json.load(f)

for action in report["merge_actions"]:
    print(f"Merged {action['merged_ids']} into {action['primary_id']} ({action['reason']})")
```

## How It Works

**Deduplication priority.** Every pair of contacts is checked in this order, and the first match wins:

1. **Exact email match** (case-insensitive, whitespace-stripped) -- the strongest signal.
2. **Exact phone match** -- normalized to E.164 via `email-phone-validator` when possible; falls back to comparing digits-only strings when a number can't be fully normalized (e.g. it's missing an area code), so two records with the literal same incomplete number still match.
3. **Fuzzy name match** -- a Levenshtein similarity ratio (via `fuzzywuzzy`) against `name_similarity_threshold`.

Matches are **transitive**: if contact A matches B by email, and B matches C by phone, all three end up in one group together, even though A and C were never directly compared as matching by the same method. This guarantees every contact belongs to exactly one final group, which is what makes merging safe -- no source record can be split across two different outputs.

**Merge strategy.** For each field (name, email, phone, company, address), the *longest* non-null value among the group wins. This is a simple, predictable heuristic for "most complete" -- not a guarantee of "most correct" (a longer value could just as easily be a typo). See [Limitations](#limitations). The merged record's `id` is inherited from whichever original record had the highest `completeness_score` (fraction of non-null fields).

**Tuning the threshold.** `0.90` (the default) catches close variants like `"Jon Smith"` / `"John Smith"` (95% similar) but not loose abbreviations like `"Jane Doe"` / `"J. Doe"` (71% similar) on their own. Lower the threshold to catch more name variants at the cost of more false positives; raise it to be more conservative. Since exact email/phone matches don't go through this threshold at all, lowering it mainly helps when contacts share *no* other identifying field.

## API Reference

### `ContactDeduplicator`

```python
ContactDeduplicator(name_similarity_threshold: float = 0.90, skip_validation: bool = False)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name_similarity_threshold` | `float` | `0.90` | Minimum fuzzy name-match score, `0.0`-`1.0`. |
| `skip_validation` | `bool` | `False` | Skip per-record email/phone validation entirely (faster; no validator instances created). |

| Method | Description |
|---|---|
| `load_csv(filepath) -> List[Contact]` | Read a CSV into `Contact` records, auto-detecting columns and assigning stable IDs. |
| `find_duplicates(contacts) -> List[List[Contact]]` | Group contacts that are duplicates of each other (size >= 2 groups only). |
| `merge_contacts(group) -> Contact` | Merge one duplicate group into a single best `Contact`. |
| `deduplicate(contacts) -> DeduplicationResult` | Full workflow: validate, find duplicate groups, merge each, return the audit trail. |
| `save_results(result, output_csv, report_json)` | Write the deduplicated contacts to CSV and the audit trail to JSON. |

### Dataclasses

**`Contact`** -- `id`, `name`, `email`, `phone`, `company`, `address` (all `Optional[str]` except `id`), `completeness_score: float` (fraction of the five fields that are non-null).

**`MergeAction`** -- one per merged group: `primary_id`, `merged_ids: List[str]`, `reason: str` (`"exact_email"`, `"exact_phone"`, or `"fuzzy_name_92%"`), `merged_contact: Contact`.

**`DeduplicationResult`** -- `total_records`, `unique_records`, `duplicates_found`, `merge_actions: List[MergeAction]`, `deduplicated_contacts: List[Contact]`, `errors: List[str]` (validation errors, informational only -- invalid records are still deduplicated and included in the output).

**`MergeReport`** -- the serializable audit-trail view of a `DeduplicationResult` (what `save_results` writes to JSON). Build one directly with `MergeReport.from_result(result)`, then `.to_dict()`.

### Configuration options

| Option | Effect |
|---|---|
| `name_similarity_threshold` | See [Tuning the threshold](#how-it-works) above. |
| `skip_validation=True` | Skip validation for speed, or when you don't need the `errors` list / don't want `EmailValidator`/`PhoneValidator` instances created at all. |

## CLI Reference

```
contact-deduplicator INPUT_CSV [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--output PATH` | `deduplicated.csv` | Where to write the deduplicated contacts CSV. |
| `--report PATH` | `merge_report.json` | Where to write the JSON audit report. |
| `--threshold FLOAT` | `0.90` | Fuzzy name-match similarity threshold, `0.0`-`1.0`. |
| `--skip-validation` | off | Skip email/phone validation. |
| `--verbose` | off | Enable INFO-level console logging. |

```bash
contact-deduplicator contacts.csv
contact-deduplicator contacts.csv --output clean.csv --report audit.json
contact-deduplicator contacts.csv --threshold 0.80 --skip-validation
contact-deduplicator contacts.csv --verbose
```

A missing file or an out-of-range `--threshold` exits with status `1` and a plain `Error: ...` message -- no Python traceback.

## Output Files

**Deduplicated CSV** -- one row per unique contact after merging, columns: `id, name, email, phone, company, address, completeness_score`.

**Merge report JSON** -- `timestamp` (ISO 8601 UTC), a `statistics` block (`total_records`, `unique_records`, `duplicates_found`, `validation_error_count`), the full `merge_actions` list (each with its `merged_contact` expanded), and `validation_errors` (one string per field problem, prefixed with the record's `id`).

## Performance

Benchmarked on a synthetic CSV with a small name pool (heavy realistic collision) and a 25% injected exact-duplicate rate, on a standard laptop:

| Records | Time |
|---|---|
| 100 | 0.03s |
| 500 | 0.23s |
| 1,000 | 0.77s |
| 2,000 | 2.8s |

Duplicate detection compares every pair of contacts (**O(n²)**), so time roughly quadruples each time the record count doubles -- as the numbers above show. Expect noticeably longer runs beyond ~5,000-10,000 records. Phone normalization is cached per unique raw value so it's only ever computed once per distinct number, regardless of how many comparisons it's involved in; the remaining cost is dominated by the fuzzy name comparisons.

For much larger datasets, the practical approach is *blocking*: pre-group records by a cheap key (e.g. postal code, or the first few letters of a name) and only compare within each block. This library doesn't do that today -- see Limitations.

## Limitations

- **O(n²) matching, no blocking.** See Performance above. Not suitable as-is for very large files (hundreds of thousands of rows) without pre-partitioning the data yourself.
- **"Longest wins" isn't "most correct."** The merge strategy has no way to know that a longer value is actually *better* -- it could be a typo, a stale value, or an over-verbose entry. Review the merge report before trusting merged output for anything consequential.
- **Phone matching needs a `+` prefix or a US-shaped number.** `ContactMatcher` normalizes phones against a fixed US default (it doesn't take a country hint). A number like `"020 7031 3000"` (valid local UK format, no `+`) won't be recognized as the same number as `"+442070313000"` -- only numbers that already include their country code, or that happen to parse under the US default, normalize reliably. Prefer `+`-prefixed numbers in source data where possible.
- **Fuzzy name matching is single-field and order-sensitive.** It compares the `name` field as a whole string; it doesn't split first/last names, so `"Smith, John"` won't fuzzy-match `"John Smith"` as well as you might expect.
- **No deduplication across multiple files.** `load_csv` handles one file per call; combining multiple sources is left to the caller (e.g. concatenate `Contact` lists before calling `deduplicate`).
- **English-oriented column detection.** `load_csv`'s header auto-detection covers common English aliases (`"phone"`, `"telephone"`, `"tel"`, ...) only.

## License

MIT -- see [LICENSE](LICENSE) for the full text.

## Contributing

Contributions are welcome. Please open an issue to discuss a change before submitting a pull request, and make sure `pytest` and `flake8` are clean.
