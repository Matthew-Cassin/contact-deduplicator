"""Pairwise contact-comparison primitives: exact and fuzzy matching.

:class:`ContactMatcher` provides the low-level building blocks --
:meth:`~ContactMatcher.exact_email_match`,
:meth:`~ContactMatcher.exact_phone_match`, and
:meth:`~ContactMatcher.fuzzy_name_match` -- that
:class:`~contact_deduplicator.deduplicator.ContactDeduplicator` combines
into duplicate-group detection.
"""

from __future__ import annotations

import re

from email_phone_validator import PhoneValidator
from fuzzywuzzy import fuzz

from .models import Contact

__all__ = ["ContactMatcher"]

# The fields that make up a Contact's completeness score. Shared as a
# module-level constant (rather than hardcoded in two places) so
# ContactMatcher.calculate_field_completeness and
# deduplicator.load_csv's completeness calculation at record-construction
# time can never drift apart.
_TRACKED_FIELDS = ("name", "email", "phone", "company", "address")


def calculate_completeness(
    name: str | None,
    email: str | None,
    phone: str | None,
    company: str | None,
    address: str | None,
) -> float:
    """Compute a completeness score from raw field values.

    This is the single source of truth for the completeness calculation.
    :meth:`ContactMatcher.calculate_field_completeness` calls it with a
    :class:`Contact`'s fields; ``deduplicator.load_csv`` calls it
    directly with parsed CSV values, since a ``Contact`` requires a
    ``completeness_score`` at construction time and so can't compute its
    own score after the fact.

    Args:
        name: Contact name, or ``None``.
        email: Contact email, or ``None``.
        phone: Contact phone, or ``None``.
        company: Contact company, or ``None``.
        address: Contact address, or ``None``.

    Returns:
        The fraction (``0.0``-``1.0``) of the five fields that are
        non-null/non-empty.
    """
    values = (name, email, phone, company, address)
    non_null = sum(1 for value in values if value)
    return non_null / len(values)


class ContactMatcher:
    """Pairwise comparison primitives used to detect duplicate contacts.

    Args:
        name_threshold: Minimum fuzzy-match score (``0.0``-``1.0``) for
            :meth:`fuzzy_name_match` to consider two names a match.
            Defaults to ``0.90``.

    Example:
        >>> matcher = ContactMatcher(name_threshold=0.90)
        >>> a = Contact("1", "John Smith", "john@x.com", None, None, None, 0.4)
        >>> b = Contact("2", "John Smith", "john@x.com", None, None, None, 0.4)
        >>> matcher.exact_email_match(a, b)
        True
    """

    def __init__(self, name_threshold: float = 0.90) -> None:
        self.name_threshold = name_threshold
        # exact_phone_match normalizes through PhoneValidator before
        # comparing; check_mx-style network calls don't apply to phone
        # parsing, so there's no offline/online toggle needed here.
        self._phone_validator = PhoneValidator()
        # ContactDeduplicator.find_duplicates compares every pair of
        # contacts, so the same raw phone string can pass through
        # _normalize_phone O(n) times. PhoneValidator.validate() does a
        # full libphonenumber parse, which is cheap once but adds up
        # across n^2 comparisons -- caching by raw string (a pure
        # function of its input) turns that back into O(n) real work.
        self._phone_normalization_cache: dict[str, str | None] = {}

    def exact_email_match(self, contact1: Contact, contact2: Contact) -> bool:
        """Compare two contacts' emails after normalization.

        Args:
            contact1: The first contact.
            contact2: The second contact.

        Returns:
            ``True`` if both have a non-null email and they're equal
            after stripping whitespace and lowercasing. ``False`` if
            either email is ``None`` or they differ.
        """
        email1, email2 = contact1.email, contact2.email
        if not email1 or not email2:
            return False
        return email1.strip().lower() == email2.strip().lower()

    def exact_phone_match(self, contact1: Contact, contact2: Contact) -> bool:
        """Compare two contacts' phone numbers after normalization.

        Numbers are normalized via :class:`~email_phone_validator.PhoneValidator`
        to E.164 when they're valid enough to parse. When a number can't
        be resolved that way (e.g. it's missing an area code, or uses a
        reserved/fictional exchange), this falls back to comparing
        digits-only strings, so that two records with the literal same
        incomplete phone number still match each other -- a very common
        real-world case in messy contact data.

        Args:
            contact1: The first contact.
            contact2: The second contact.

        Returns:
            ``True`` if both have a non-null phone and they resolve to
            the same normalized value. ``False`` if either phone is
            ``None`` or they resolve differently.
        """
        phone1, phone2 = contact1.phone, contact2.phone
        if not phone1 or not phone2:
            return False
        normalized1 = self._normalize_phone(phone1)
        normalized2 = self._normalize_phone(phone2)
        if not normalized1 or not normalized2:
            return False
        return normalized1 == normalized2

    def _normalize_phone(self, raw: str) -> str | None:
        """Normalize a raw phone string for comparison, with caching.

        Args:
            raw: The raw phone number string.

        Returns:
            The E.164 form if ``raw`` parses as a valid number; otherwise
            a digits-only fallback key (or ``None`` if there are no
            digits at all). Cached by ``raw`` since deduplication compares
            every pair of contacts and the same raw string is normalized
            repeatedly.
        """
        if raw in self._phone_normalization_cache:
            return self._phone_normalization_cache[raw]

        result = self._phone_validator.validate(raw)
        if result.is_valid and result.formatted:
            normalized: str | None = result.formatted
        else:
            digits = re.sub(r"\D", "", raw)
            normalized = digits or None

        self._phone_normalization_cache[raw] = normalized
        return normalized

    def fuzzy_name_match(
        self, contact1: Contact, contact2: Contact
    ) -> tuple[bool, float]:
        """Compare two contacts' names by similarity score.

        Args:
            contact1: The first contact.
            contact2: The second contact.

        Returns:
            A ``(is_match, score)`` tuple, where ``score`` is the
            Levenshtein-based similarity ratio (``0.0``-``1.0``) between
            the two normalized names, and ``is_match`` is whether
            ``score >= self.name_threshold``. Returns ``(False, 0.0)``
            when either name is ``None`` or empty.
        """
        name1, name2 = contact1.name, contact2.name
        if not name1 or not name2:
            return False, 0.0
        score = fuzz.ratio(name1.strip().lower(), name2.strip().lower()) / 100.0
        return score >= self.name_threshold, score

    def calculate_field_completeness(self, contact: Contact) -> float:
        """Compute how complete a contact's data is.

        Args:
            contact: The contact to score.

        Returns:
            The fraction (``0.0``-``1.0``) of tracked fields (``name``,
            ``email``, ``phone``, ``company``, ``address``) that are
            non-null/non-empty.
        """
        return calculate_completeness(
            contact.name, contact.email, contact.phone, contact.company, contact.address
        )
