"""Tests for contact_deduplicator.matcher."""

import pytest

from contact_deduplicator.matcher import ContactMatcher, calculate_completeness
from contact_deduplicator.models import Contact


def make_contact(id_="1", name=None, email=None, phone=None, company=None, address=None):
    return Contact(id_, name, email, phone, company, address, 0.0)


@pytest.fixture
def matcher():
    return ContactMatcher(name_threshold=0.90)


class TestExactEmailMatch:
    """exact_email_match: case-insensitive, whitespace-tolerant, None-safe."""

    def test_identical_emails_match(self, matcher):
        a = make_contact(email="john@example.com")
        b = make_contact(email="john@example.com")
        assert matcher.exact_email_match(a, b) is True

    def test_case_insensitive_match(self, matcher):
        a = make_contact(email="John@Example.COM")
        b = make_contact(email="john@example.com")
        assert matcher.exact_email_match(a, b) is True

    def test_whitespace_is_stripped(self, matcher):
        a = make_contact(email="  john@example.com  ")
        b = make_contact(email="john@example.com")
        assert matcher.exact_email_match(a, b) is True

    def test_different_emails_do_not_match(self, matcher):
        a = make_contact(email="john@example.com")
        b = make_contact(email="jane@example.com")
        assert matcher.exact_email_match(a, b) is False

    def test_one_email_none_does_not_match(self, matcher):
        a = make_contact(email="john@example.com")
        b = make_contact(email=None)
        assert matcher.exact_email_match(a, b) is False

    def test_both_emails_none_does_not_match(self, matcher):
        a = make_contact(email=None)
        b = make_contact(email=None)
        assert matcher.exact_email_match(a, b) is False


class TestExactPhoneMatch:
    """exact_phone_match: E.164 normalization with a digits-only fallback."""

    def test_same_number_different_formatting_matches(self, matcher):
        a = make_contact(phone="+1 415-858-6273")
        b = make_contact(phone="(415) 858-6273")
        assert matcher.exact_phone_match(a, b) is True

    def test_different_valid_numbers_do_not_match(self, matcher):
        a = make_contact(phone="+14158586273")
        b = make_contact(phone="+14155551212")
        assert matcher.exact_phone_match(a, b) is False

    def test_identical_incomplete_numbers_match_via_digit_fallback(self, matcher):
        # Neither "555-0456" resolves to a valid, normalizable number (no
        # area code), so both fall back to a digits-only comparison key.
        a = make_contact(phone="555-0456")
        b = make_contact(phone="555-0456")
        assert matcher.exact_phone_match(a, b) is True

    def test_different_incomplete_numbers_do_not_match(self, matcher):
        # "555-0123" (7 digits) vs "(555) 555-0123" (10 digits) are
        # genuinely different digit sequences, not just formatting.
        a = make_contact(phone="555-0123")
        b = make_contact(phone="(555) 555-0123")
        assert matcher.exact_phone_match(a, b) is False

    def test_one_phone_none_does_not_match(self, matcher):
        a = make_contact(phone="+14158586273")
        b = make_contact(phone=None)
        assert matcher.exact_phone_match(a, b) is False

    def test_both_phones_none_does_not_match(self, matcher):
        assert matcher.exact_phone_match(make_contact(), make_contact()) is False

    def test_junk_phone_does_not_crash_and_does_not_match(self, matcher):
        a = make_contact(phone="@#$%^&*")
        b = make_contact(phone="@#$%^&*")
        # No digits at all in either -> no fallback key -> no match.
        assert matcher.exact_phone_match(a, b) is False


class TestFuzzyNameMatch:
    """fuzzy_name_match: similarity scoring, threshold behavior, None-safety."""

    def test_identical_names_score_1_0(self, matcher):
        is_match, score = matcher.fuzzy_name_match(
            make_contact(name="John Smith"), make_contact(name="John Smith")
        )
        assert is_match is True
        assert score == 1.0

    def test_close_typo_variant_matches_at_default_threshold(self, matcher):
        # fuzz.ratio("john smith", "jon smith") == 95
        is_match, score = matcher.fuzzy_name_match(
            make_contact(name="John Smith"), make_contact(name="Jon Smith")
        )
        assert is_match is True
        assert score == pytest.approx(0.95, abs=0.01)

    def test_dissimilar_names_do_not_match(self, matcher):
        is_match, score = matcher.fuzzy_name_match(
            make_contact(name="John Smith"), make_contact(name="Bob Johnson")
        )
        assert is_match is False
        assert score < 0.90

    def test_below_threshold_abbreviation_does_not_match(self, matcher):
        # fuzz.ratio("jane doe", "j. doe") == 71%, below the 90% default.
        is_match, score = matcher.fuzzy_name_match(
            make_contact(name="Jane Doe"), make_contact(name="J. Doe")
        )
        assert is_match is False
        assert score == pytest.approx(0.71, abs=0.01)

    def test_custom_lower_threshold_allows_the_same_pair_to_match(self):
        loose_matcher = ContactMatcher(name_threshold=0.70)
        is_match, score = loose_matcher.fuzzy_name_match(
            make_contact(name="Jane Doe"), make_contact(name="J. Doe")
        )
        assert is_match is True

    def test_one_name_none_returns_false_and_zero(self, matcher):
        assert matcher.fuzzy_name_match(
            make_contact(name="John Smith"), make_contact(name=None)
        ) == (False, 0.0)

    def test_both_names_none_returns_false_and_zero(self, matcher):
        assert matcher.fuzzy_name_match(make_contact(), make_contact()) == (False, 0.0)

    def test_empty_string_name_treated_like_none(self, matcher):
        is_match, score = matcher.fuzzy_name_match(
            make_contact(name=""), make_contact(name="John")
        )
        assert (is_match, score) == (False, 0.0)

    def test_case_and_whitespace_insensitive(self, matcher):
        is_match, _ = matcher.fuzzy_name_match(
            make_contact(name="  JOHN SMITH  "), make_contact(name="john smith")
        )
        assert is_match is True

    def test_identical_unicode_names_match(self, matcher):
        is_match, score = matcher.fuzzy_name_match(
            make_contact(name="José García"), make_contact(name="José García")
        )
        assert is_match is True
        assert score == 1.0


class TestCalculateFieldCompleteness:
    """calculate_field_completeness and its shared helper calculate_completeness."""

    def test_all_fields_present_is_1_0(self, matcher):
        contact = make_contact(
            name="A", email="a@b.com", phone="123", company="C", address="D"
        )
        assert matcher.calculate_field_completeness(contact) == 1.0

    def test_no_fields_present_is_0_0(self, matcher):
        assert matcher.calculate_field_completeness(make_contact()) == 0.0

    def test_partial_fields_present(self, matcher):
        contact = make_contact(name="A", email="a@b.com")
        assert matcher.calculate_field_completeness(contact) == pytest.approx(0.4)

    def test_matches_module_level_helper(self, matcher):
        contact = make_contact(name="A", email="a@b.com", phone="123")
        via_method = matcher.calculate_field_completeness(contact)
        via_helper = calculate_completeness(
            contact.name, contact.email, contact.phone, contact.company, contact.address
        )
        assert via_method == via_helper


class TestContactMatcherConfiguration:
    def test_default_threshold_is_0_90(self):
        assert ContactMatcher().name_threshold == 0.90

    def test_custom_threshold_is_stored(self):
        assert ContactMatcher(name_threshold=0.75).name_threshold == 0.75
