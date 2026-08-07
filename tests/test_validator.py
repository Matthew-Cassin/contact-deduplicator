"""Tests for contact_deduplicator.validator."""

import pytest
from email_phone_validator import EmailValidator, PhoneValidator

from contact_deduplicator.models import Contact
from contact_deduplicator.validator import ContactValidator


@pytest.fixture
def validator():
    return ContactValidator(EmailValidator(check_mx=False), PhoneValidator())


def make_contact(name="John Smith", email=None, phone=None, company=None, address=None):
    return Contact("1", name, email, phone, company, address, 0.0)


class TestContactValidatorValidContacts:
    """Contacts that should pass validation cleanly."""

    def test_fully_valid_contact(self, validator):
        contact = make_contact(
            name="John Smith",
            email="john@example.com",
            phone="+14158586273",
            company="Acme Corp",
            address="123 Main St",
        )
        is_valid, errors = validator.validate_contact(contact)
        assert is_valid is True
        assert errors == []

    def test_valid_with_only_a_name(self, validator):
        # email, phone, company, address are all optional
        is_valid, errors = validator.validate_contact(make_contact(name="Jane Doe"))
        assert is_valid is True
        assert errors == []

    def test_valid_international_phone(self, validator):
        is_valid, errors = validator.validate_contact(
            make_contact(name="Jane Doe", phone="+442070313000")
        )
        assert is_valid is True

    def test_name_exactly_at_minimum_length(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(name="Bob"))  # 3 chars
        assert is_valid is True

    def test_name_exactly_at_maximum_length(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(name="A" * 100))
        assert is_valid is True


class TestContactValidatorInvalidFields:
    """Each field's failure mode, one at a time."""

    def test_missing_name_is_invalid(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(name=None))
        assert is_valid is False
        assert any("name" in e.lower() for e in errors)

    def test_empty_string_name_is_invalid(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(name="   "))
        assert is_valid is False

    def test_name_too_short_is_invalid(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(name="Al"))  # 2 chars
        assert is_valid is False
        assert "3" in errors[0] and "100" in errors[0]

    def test_name_too_long_is_invalid(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(name="A" * 101))
        assert is_valid is False

    def test_invalid_email_format(self, validator):
        is_valid, errors = validator.validate_contact(
            make_contact(email="not-an-email")
        )
        assert is_valid is False
        assert any("email" in e.lower() for e in errors)

    def test_invalid_phone_too_short(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(phone="123"))
        assert is_valid is False
        assert any("phone" in e.lower() for e in errors)

    def test_company_present_but_empty(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(company="   "))
        assert is_valid is False
        assert any("company" in e.lower() for e in errors)

    def test_address_present_but_empty(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(address=""))
        assert is_valid is False
        assert any("address" in e.lower() for e in errors)

    def test_company_none_is_not_an_error(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(company=None))
        assert is_valid is True


class TestContactValidatorMultipleErrors:
    """Multiple simultaneous problems should all be reported."""

    def test_collects_every_field_error(self, validator):
        contact = make_contact(name="Al", email="bad-email", phone="123", company="")
        is_valid, errors = validator.validate_contact(contact)
        assert is_valid is False
        assert len(errors) == 4  # name, email, phone, company each contribute one

    def test_valid_flag_matches_error_list_emptiness(self, validator):
        is_valid, errors = validator.validate_contact(make_contact(name=None))
        assert is_valid == (len(errors) == 0)


class TestContactValidatorConstruction:
    def test_stores_injected_validators(self):
        email_validator = EmailValidator(check_mx=False)
        phone_validator = PhoneValidator()
        validator = ContactValidator(email_validator, phone_validator)
        assert validator.email_validator is email_validator
        assert validator.phone_validator is phone_validator
