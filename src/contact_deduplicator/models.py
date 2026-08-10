"""Core data structures for contact-deduplicator.

``Contact`` is the unit of data the whole library operates on.
``MergeAction`` and ``DeduplicationResult`` capture what happened during a
deduplication run; ``MergeReport`` is the serializable audit-trail view of
that run, suitable for writing straight to JSON. ``DeduplicationError`` is
the single exception type the package raises.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "Contact",
    "DeduplicationError",
    "DeduplicationResult",
    "MergeAction",
    "MergeReport",
]


@dataclass
class Contact:
    """A single contact record.

    Attributes:
        id: Unique identifier for this record (e.g. ``"row-3"`` for the
            third data row of a loaded CSV). Stable within a single
            deduplication run.
        name: Full name, or ``None`` if not present in the source data.
        email: Email address, or ``None``.
        phone: Phone number in whatever format the source provided, or
            ``None``.
        company: Company/organization name, or ``None``.
        address: Postal address, or ``None``.
        completeness_score: Fraction (``0.0``-``1.0``) of the five tracked
            fields (``name``, ``email``, ``phone``, ``company``,
            ``address``) that are non-null. ``1.0`` means every field is
            populated. See
            :meth:`~contact_deduplicator.matcher.ContactMatcher.calculate_field_completeness`
            for how this is computed.

    Example:
        >>> contact = Contact(
        ...     id="row-1",
        ...     name="John Smith",
        ...     email="john@example.com",
        ...     phone="555-0123",
        ...     company="Acme Corp",
        ...     address=None,
        ...     completeness_score=0.8,
        ... )
        >>> contact.completeness_score
        0.8
    """

    id: str
    name: str | None
    email: str | None
    phone: str | None
    company: str | None
    address: str | None
    completeness_score: float


@dataclass
class MergeAction:
    """A record of one duplicate group being merged into a single contact.

    Attributes:
        primary_id: The ``id`` of the source record whose identity the
            merged contact took on -- the most complete record in the
            group (see
            :meth:`~contact_deduplicator.deduplicator.ContactDeduplicator.merge_contacts`).
        merged_ids: The ``id``\\ s of the *other* records in the group,
            i.e. everything folded into ``primary_id``. Does not include
            ``primary_id`` itself.
        reason: Why the group was identified as duplicates, e.g.
            ``"exact_email"``, ``"exact_phone"``, or ``"fuzzy_name_92%"``.
            Reflects the strongest signal found between the primary
            record and the rest of the group.
        merged_contact: The resulting :class:`Contact` after merging,
            with ``merged_contact.id == primary_id``.
    """

    primary_id: str
    merged_ids: list[str]
    reason: str
    merged_contact: Contact


@dataclass
class DeduplicationResult:
    """The full outcome of a deduplication run.

    Attributes:
        total_records: Number of contacts given to
            :meth:`~contact_deduplicator.deduplicator.ContactDeduplicator.deduplicate`.
        unique_records: Number of contacts after deduplication --
            ``len(deduplicated_contacts)``.
        duplicates_found: ``total_records - unique_records``: how many
            input records were folded into another record.
        merge_actions: One entry per duplicate group that was merged.
            Records with no duplicate have no corresponding action.
        deduplicated_contacts: The final contact list -- merged contacts
            plus any records that had no duplicates, unchanged.
        errors: Validation error messages collected per record (empty if
            validation was skipped or every record was valid). These are
            informational only; invalid records are still deduplicated
            and included in ``deduplicated_contacts``.
    """

    total_records: int
    unique_records: int
    duplicates_found: int
    merge_actions: list[MergeAction] = field(default_factory=list)
    deduplicated_contacts: list[Contact] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class MergeReport:
    """The serializable audit-trail view of a :class:`DeduplicationResult`.

    Where ``DeduplicationResult`` is the full in-memory result (including
    every deduplicated :class:`Contact`), ``MergeReport`` is specifically
    the *report* artifact: statistics, merge actions, and validation
    errors, timestamped, in a shape ready for
    :meth:`~contact_deduplicator.deduplicator.ContactDeduplicator.save_results`
    to write out as JSON.

    Attributes:
        timestamp: ISO 8601 UTC timestamp of when the report was built.
        total_records: See :attr:`DeduplicationResult.total_records`.
        unique_records: See :attr:`DeduplicationResult.unique_records`.
        duplicates_found: See :attr:`DeduplicationResult.duplicates_found`.
        merge_actions: See :attr:`DeduplicationResult.merge_actions`.
        validation_errors: See :attr:`DeduplicationResult.errors`.
    """

    timestamp: str
    total_records: int
    unique_records: int
    duplicates_found: int
    merge_actions: list[MergeAction] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)

    @classmethod
    def from_result(cls, result: DeduplicationResult) -> MergeReport:
        """Build a :class:`MergeReport` from a :class:`DeduplicationResult`.

        Args:
            result: The result of a completed deduplication run.

        Returns:
            A new ``MergeReport`` timestamped at the moment of the call.
        """
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_records=result.total_records,
            unique_records=result.unique_records,
            duplicates_found=result.duplicates_found,
            merge_actions=result.merge_actions,
            validation_errors=result.errors,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable ``dict`` representation.

        Returns:
            A dict with ``timestamp``, a ``statistics`` sub-dict, the
            list of ``merge_actions`` (each with its ``merged_contact``
            expanded to a plain dict), and ``validation_errors``.
        """
        return {
            "timestamp": self.timestamp,
            "statistics": {
                "total_records": self.total_records,
                "unique_records": self.unique_records,
                "duplicates_found": self.duplicates_found,
                "validation_error_count": len(self.validation_errors),
            },
            "merge_actions": [
                {
                    "primary_id": action.primary_id,
                    "merged_ids": action.merged_ids,
                    "reason": action.reason,
                    "merged_contact": asdict(action.merged_contact),
                }
                for action in self.merge_actions
            ],
            "validation_errors": self.validation_errors,
        }


class DeduplicationError(Exception):
    """Raised when an operation can't be attempted at all, not just when data is messy.

    Messy or duplicate *data* is never an exception -- it's the everyday
    input this library exists to handle, reported through
    :class:`DeduplicationResult` (``errors``) and :class:`MergeAction`
    instead. ``DeduplicationError`` is reserved for cases the caller must
    fix in code, such as:

    * Invalid configuration (e.g. a ``name_similarity_threshold`` outside
      ``0.0``-``1.0``).
    * A CSV file that can't be read at all (missing, empty, unparseable,
      or with no recognizable contact columns) -- as opposed to a CSV
      that reads fine but has messy *values*.
    * Calling a method with the wrong argument type or shape (e.g.
      merging an empty group).

    Example:
        >>> from contact_deduplicator import ContactDeduplicator, DeduplicationError
        >>> try:
        ...     ContactDeduplicator(name_similarity_threshold=1.5)
        ... except DeduplicationError as exc:
        ...     print(exc)
        name_similarity_threshold must be between 0.0 and 1.0, got 1.5
    """
