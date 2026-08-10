"""Core orchestration: load a CSV, find duplicate contacts, merge them, save results.

:class:`ContactDeduplicator` is the library's main entry point. It uses
:class:`~contact_deduplicator.matcher.ContactMatcher` for pairwise
comparisons and (unless ``skip_validation=True``)
:class:`~contact_deduplicator.validator.ContactValidator` for per-record
field validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from email_phone_validator import EmailValidator, PhoneValidator

from .logger import get_logger
from .matcher import ContactMatcher, calculate_completeness
from .models import (
    Contact,
    DeduplicationError,
    DeduplicationResult,
    MergeAction,
    MergeReport,
)
from .validator import ContactValidator

logger = get_logger("deduplicator")

__all__ = ["ContactDeduplicator"]

_TRACKED_FIELDS: tuple[str, ...] = ("name", "email", "phone", "company", "address")

# Column-header aliases for auto-detection during load_csv, matched
# case-insensitively after stripping whitespace. Not exhaustive -- a
# short, common-sense list rather than an attempt to cover every
# possible header a source system might use.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "full name", "fullname", "contact name", "contact"),
    "email": ("email", "e-mail", "email address", "emailaddress"),
    "phone": ("phone", "phone number", "phonenumber", "telephone", "tel", "mobile", "cell"),
    "company": ("company", "organization", "organisation", "employer", "company name"),
    "address": ("address", "street address", "mailing address", "location"),
}

# Match-method priority, highest first: exact email > exact phone > fuzzy
# name. Used both to pick which reason to report for a group and to
# short-circuit pairwise comparisons once the strongest possible reason
# (exact_email) has already been found.
_EXACT_EMAIL_PRIORITY = 2
_EXACT_PHONE_PRIORITY = 1
_FUZZY_NAME_PRIORITY = 0


class ContactDeduplicator:
    """Loads, deduplicates, and saves contact records from CSV files.

    Duplicate detection considers three signals, in priority order:
    exact email match, exact phone match, then fuzzy name match. Any two
    contacts connected by *any* of these (directly or transitively
    through other contacts) end up in the same duplicate group; see
    :meth:`find_duplicates`.

    Args:
        name_similarity_threshold: Minimum similarity score (``0.0``-``1.0``)
            for two names to be considered a fuzzy match. Defaults to
            ``0.90``.
        skip_validation: If ``True``, :meth:`deduplicate` skips per-record
            field validation entirely (faster; no email/phone validator
            instances are created). Defaults to ``False``.

    Raises:
        DeduplicationError: If ``name_similarity_threshold`` is outside
            ``0.0``-``1.0``.

    Example:
        >>> deduplicator = ContactDeduplicator(name_similarity_threshold=0.90)
        >>> contacts = deduplicator.load_csv("contacts.csv")  # doctest: +SKIP
        >>> result = deduplicator.deduplicate(contacts)  # doctest: +SKIP
        >>> result.duplicates_found  # doctest: +SKIP
        2
    """

    def __init__(
        self, name_similarity_threshold: float = 0.90, skip_validation: bool = False
    ) -> None:
        if not 0.0 <= name_similarity_threshold <= 1.0:
            raise DeduplicationError(
                "name_similarity_threshold must be between 0.0 and 1.0, "
                f"got {name_similarity_threshold}"
            )
        self.name_similarity_threshold = name_similarity_threshold
        self.skip_validation = skip_validation
        self._matcher = ContactMatcher(name_threshold=name_similarity_threshold)
        self._validator: ContactValidator | None = None
        if not skip_validation:
            self._validator = ContactValidator(EmailValidator(check_mx=False), PhoneValidator())

    # -- Loading ------------------------------------------------------

    def load_csv(self, filepath: str) -> list[Contact]:
        """Load contacts from a CSV file.

        Column names are matched case-insensitively against a short list
        of common aliases per field (see the module's ``_COLUMN_ALIASES``);
        columns that don't match any known field are ignored, and fields
        with no matching column are left ``None`` on every record. Each
        record gets a stable id (``"row-1"``, ``"row-2"``, ...) matching
        its 1-indexed position among the CSV's data rows.

        Args:
            filepath: Path to the CSV file.

        Returns:
            One :class:`Contact` per data row, in file order.

        Raises:
            DeduplicationError: If the file doesn't exist, is empty,
                can't be parsed as CSV, or has no recognizable contact
                columns at all.
        """
        path = Path(filepath)
        if not path.exists():
            raise DeduplicationError(f"CSV file not found: {filepath}")

        try:
            frame = pd.read_csv(filepath, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError as exc:
            raise DeduplicationError(f"CSV file is empty: {filepath}") from exc
        except pd.errors.ParserError as exc:
            raise DeduplicationError(f"Could not parse CSV file {filepath}: {exc}") from exc

        column_map = self._detect_columns(list(frame.columns))
        if not any(column_map.values()):
            raise DeduplicationError(
                "No recognizable contact columns (name/email/phone/company/address) "
                f"found in {filepath}. Columns present: {list(frame.columns)}"
            )

        detected_columns = {source for source in column_map.values() if source}
        ignored = [c for c in frame.columns if c not in detected_columns]
        if ignored:
            logger.info("Ignoring unrecognized column(s) in %s: %s", filepath, ignored)

        rename_map = {source: field for field, source in column_map.items() if source}
        frame = frame[list(detected_columns)].rename(columns=rename_map)

        contacts: list[Contact] = []
        records = frame.to_dict(orient="records")
        for row_index, raw in enumerate(records, start=1):
            values = {
                field_name: self._normalize_field(field_name, raw.get(field_name, ""))
                for field_name in _TRACKED_FIELDS
            }
            score = calculate_completeness(**values)
            contacts.append(Contact(id=f"row-{row_index}", completeness_score=score, **values))

        logger.info("Loaded %d contact(s) from %s", len(contacts), filepath)
        return contacts

    def _detect_columns(self, columns: list[str]) -> dict[str, str | None]:
        """Map each canonical field to a matching source column, if any.

        Args:
            columns: The CSV's header row, in order.

        Returns:
            A dict with one entry per field in ``_TRACKED_FIELDS``,
            mapping to the matching column name from ``columns``, or
            ``None`` if none of that field's aliases were found.
        """
        available = {col.strip().lower(): col for col in columns}
        result: dict[str, str | None] = {}
        for field_name, aliases in _COLUMN_ALIASES.items():
            match = next((available[alias] for alias in aliases if alias in available), None)
            result[field_name] = match
        return result

    def _normalize_field(self, field_name: str, raw_value: str) -> str | None:
        """Strip whitespace, lowercase email/phone, and blank out empty values."""
        value = (raw_value or "").strip()
        if not value:
            return None
        if field_name in ("email", "phone"):
            value = value.lower()
        return value

    # -- Matching -------------------------------------------------------

    def find_duplicates(self, contacts: list[Contact]) -> list[list[Contact]]:
        """Group contacts that are duplicates of each other.

        Every pair of contacts is compared by exact email, then exact
        phone, then fuzzy name (see
        :class:`~contact_deduplicator.matcher.ContactMatcher`). Any match
        by any method connects that pair; connections are then resolved
        *transitively* -- if A matches B (say, by email) and B matches C
        (say, by phone), A, B, and C all end up in one group together,
        even though A and C were never directly compared as matching by
        the same method. This is what makes the result usable for
        merging: every contact belongs to exactly one group, so merging
        each group can never split or duplicate a source record.

        Args:
            contacts: The contacts to compare, in any order.

        Returns:
            One list per duplicate group found, each containing two or
            more contacts, in their original relative order. Contacts
            with no duplicate are omitted entirely (not returned as
            singleton groups).

        Raises:
            DeduplicationError: If ``contacts`` is not a list.
        """
        if not isinstance(contacts, list):
            raise DeduplicationError(f"contacts must be a list, got {type(contacts).__name__}")

        count = len(contacts)
        if count < 2:
            return []

        parent = list(range(count))

        def find_root(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(index_a: int, index_b: int) -> None:
            root_a, root_b = find_root(index_a), find_root(index_b)
            if root_a != root_b:
                parent[root_b] = root_a

        for i in range(count):
            for j in range(i + 1, count):
                if self._pair_reason(contacts[i], contacts[j])[1] >= 0:
                    union(i, j)

        groups: dict[int, list[Contact]] = {}
        for index in range(count):
            groups.setdefault(find_root(index), []).append(contacts[index])

        return [group for group in groups.values() if len(group) > 1]

    def _pair_reason(self, contact1: Contact, contact2: Contact) -> tuple[str, int]:
        """The match reason and priority for one pair of contacts.

        Returns:
            A ``(reason, priority)`` tuple. ``priority`` is ``-1`` if the
            pair doesn't match at all; otherwise higher means a stronger
            signal (exact email > exact phone > fuzzy name).
        """
        if self._matcher.exact_email_match(contact1, contact2):
            return "exact_email", _EXACT_EMAIL_PRIORITY
        if self._matcher.exact_phone_match(contact1, contact2):
            return "exact_phone", _EXACT_PHONE_PRIORITY
        is_match, score = self._matcher.fuzzy_name_match(contact1, contact2)
        if is_match:
            return f"fuzzy_name_{round(score * 100)}%", _FUZZY_NAME_PRIORITY
        return "", -1

    def _group_reason(self, group: list[Contact]) -> str:
        """The single strongest match reason found anywhere within a group.

        Groups can form transitively (see :meth:`find_duplicates`), so
        this checks every pair in the group rather than assuming any one
        member -- including the primary -- is directly matched to every
        other member.
        """
        best_reason, best_priority = "", -1
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                reason, priority = self._pair_reason(group[i], group[j])
                if priority > best_priority:
                    best_reason, best_priority = reason, priority
                if best_priority == _EXACT_EMAIL_PRIORITY:
                    return best_reason
        return best_reason or "unknown"

    def _pick_primary(self, group: list[Contact]) -> Contact:
        """The most complete contact in a group (ties go to the earliest)."""
        return max(group, key=lambda contact: contact.completeness_score)

    # -- Merging ----------------------------------------------------------

    def merge_contacts(self, duplicate_group: list[Contact]) -> Contact:
        """Merge a group of duplicate contacts into a single best contact.

        For each field, the longest non-null value among the group wins
        (ties go to whichever contact appears earliest in
        ``duplicate_group``) -- a simple, predictable heuristic for
        "most complete," though not infallible (see the README's
        Limitations section). The merged contact's ``id`` is taken from
        whichever input contact has the highest ``completeness_score``.

        Args:
            duplicate_group: Two or more contacts believed to be the same
                person/organization. A single-element list is returned
                unchanged.

        Returns:
            A new :class:`Contact` combining the group's best available
            data, with a freshly computed ``completeness_score``.

        Raises:
            DeduplicationError: If ``duplicate_group`` is empty.
        """
        if not duplicate_group:
            raise DeduplicationError("Cannot merge an empty group of contacts")
        if len(duplicate_group) == 1:
            return duplicate_group[0]

        merged_values: dict[str, str | None] = {}
        for field_name in _TRACKED_FIELDS:
            candidates = [
                getattr(contact, field_name)
                for contact in duplicate_group
                if getattr(contact, field_name)
            ]
            merged_values[field_name] = max(candidates, key=len) if candidates else None

        primary = self._pick_primary(duplicate_group)
        score = calculate_completeness(**merged_values)
        return Contact(id=primary.id, completeness_score=score, **merged_values)

    # -- Orchestration ------------------------------------------------

    def deduplicate(self, contacts: list[Contact]) -> DeduplicationResult:
        """Run the full deduplication workflow: validate, group, merge.

        Args:
            contacts: The contacts to deduplicate, typically from
                :meth:`load_csv`.

        Returns:
            A :class:`DeduplicationResult` with the merged contact list
            and a full audit trail of what was merged and why. Handles
            an empty ``contacts`` list and a single-record list as
            trivial cases (zero and zero duplicates respectively).

        Raises:
            DeduplicationError: If ``contacts`` is not a list.
        """
        if not isinstance(contacts, list):
            raise DeduplicationError(f"contacts must be a list, got {type(contacts).__name__}")

        total = len(contacts)
        errors: list[str] = []
        if self._validator is not None:
            for contact in contacts:
                is_valid, contact_errors = self._validator.validate_contact(contact)
                if not is_valid:
                    errors.extend(f"{contact.id}: {message}" for message in contact_errors)

        if total == 0:
            return DeduplicationResult(
                total_records=0,
                unique_records=0,
                duplicates_found=0,
                merge_actions=[],
                deduplicated_contacts=[],
                errors=errors,
            )

        groups = self.find_duplicates(contacts)
        grouped_ids = {contact.id for group in groups for contact in group}

        deduplicated: list[Contact] = []
        merge_actions: list[MergeAction] = []
        for group in groups:
            merged = self.merge_contacts(group)
            primary = self._pick_primary(group)
            merged_ids = [contact.id for contact in group if contact.id != primary.id]
            merge_actions.append(
                MergeAction(
                    primary_id=primary.id,
                    merged_ids=merged_ids,
                    reason=self._group_reason(group),
                    merged_contact=merged,
                )
            )
            deduplicated.append(merged)

        for contact in contacts:
            if contact.id not in grouped_ids:
                deduplicated.append(contact)

        logger.info(
            "Deduplication complete: %d record(s) -> %d unique (%d group(s) merged)",
            total,
            len(deduplicated),
            len(merge_actions),
        )

        return DeduplicationResult(
            total_records=total,
            unique_records=len(deduplicated),
            duplicates_found=total - len(deduplicated),
            merge_actions=merge_actions,
            deduplicated_contacts=deduplicated,
            errors=errors,
        )

    # -- Output -------------------------------------------------------

    def save_results(
        self, result: DeduplicationResult, output_csv: str, report_json: str
    ) -> None:
        """Write the deduplicated contacts to CSV and the audit trail to JSON.

        Args:
            result: The result of a call to :meth:`deduplicate`.
            output_csv: Path to write the deduplicated contacts to,
                columns ``id, name, email, phone, company, address,
                completeness_score``.
            report_json: Path to write the JSON audit report to (see
                :meth:`~contact_deduplicator.models.MergeReport.to_dict`
                for its structure).
        """
        rows = [
            {
                "id": contact.id,
                "name": contact.name or "",
                "email": contact.email or "",
                "phone": contact.phone or "",
                "company": contact.company or "",
                "address": contact.address or "",
                "completeness_score": round(contact.completeness_score, 2),
            }
            for contact in result.deduplicated_contacts
        ]
        columns = ["id", "name", "email", "phone", "company", "address", "completeness_score"]
        pd.DataFrame(rows, columns=columns).to_csv(output_csv, index=False)

        report = MergeReport.from_result(result)
        with open(report_json, "w", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, indent=2)

        logger.info(
            "Saved %d contact(s) to %s and report to %s",
            len(result.deduplicated_contacts),
            output_csv,
            report_json,
        )
