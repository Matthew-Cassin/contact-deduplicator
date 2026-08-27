"""contact-deduplicator: production-grade CSV contact deduplication.

Detects duplicate contact records by exact email match, exact phone
match, and fuzzy name match (in that priority order), merges each
duplicate group into a single best record by keeping the most complete
field values, and produces a full audit trail of every merge decision.
Integrates with ``email-phone-validator`` for field validation and phone
normalization.

Public API:
    ContactDeduplicator: The main entry point -- load a CSV, find
        duplicates, merge them, save results.
    DeduplicationResult: The full in-memory outcome of a deduplication
        run, including every deduplicated contact.
    MergeReport: The serializable audit-trail view of a
        ``DeduplicationResult`` (what gets written to the JSON report).
    DeduplicationError: Raised for unrecoverable errors (bad
        configuration, an unreadable CSV) as distinct from merely messy
        *data*, which is never an exception -- see its docstring.

Also exported for convenience: ``Contact`` and ``MergeAction`` (the
dataclasses that make up the results above), and ``ContactValidator`` /
``ContactMatcher`` (the lower-level building blocks
``ContactDeduplicator`` is built from).

Example:
    >>> from contact_deduplicator import ContactDeduplicator
    >>> deduplicator = ContactDeduplicator()
    >>> contacts = deduplicator.load_csv("contacts.csv")  # doctest: +SKIP
    >>> result = deduplicator.deduplicate(contacts)  # doctest: +SKIP
"""

from .deduplicator import ContactDeduplicator
from .matcher import ContactMatcher
from .models import (
    Contact,
    DeduplicationError,
    DeduplicationResult,
    MergeAction,
    MergeReport,
)
from .validator import ContactValidator

__version__ = "1.0.3"

__all__ = [
    "Contact",
    "ContactDeduplicator",
    "ContactMatcher",
    "ContactValidator",
    "DeduplicationError",
    "DeduplicationResult",
    "MergeAction",
    "MergeReport",
    "__version__",
]
