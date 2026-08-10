"""Per-contact field validation, delegating to email-phone-validator.

:class:`ContactValidator` checks each field of a :class:`Contact` and
collects human-readable error messages, rather than raising -- an invalid
contact is normal, expected input for a deduplication tool, not an
exceptional situation. See
:class:`~contact_deduplicator.models.DeduplicationError` for the
boundary between "invalid data" and "couldn't even attempt this."
"""

from __future__ import annotations

from email_phone_validator import EmailValidator, PhoneValidator

from .logger import get_logger
from .models import Contact

logger = get_logger("validator")

__all__ = ["ContactValidator"]

_MIN_NAME_LENGTH = 3
_MAX_NAME_LENGTH = 100


class ContactValidator:
    """Validates individual :class:`Contact` records field by field.

    Email and phone validation are delegated to the ``email-phone-validator``
    library; name, company, and address use simple presence/length rules.

    Args:
        email_validator: An :class:`~email_phone_validator.EmailValidator`
            instance used to validate ``contact.email``.
        phone_validator: A :class:`~email_phone_validator.PhoneValidator`
            instance used to validate ``contact.phone``.

    Example:
        >>> validator = ContactValidator(
        ...     EmailValidator(check_mx=False), PhoneValidator()
        ... )
        >>> is_valid, errors = validator.validate_contact(
        ...     Contact("1", "John Smith", "john@example.com", "+14158586273",
        ...             None, None, 0.6)
        ... )
        >>> is_valid
        True
    """

    def __init__(self, email_validator: EmailValidator, phone_validator: PhoneValidator) -> None:
        self.email_validator = email_validator
        self.phone_validator = phone_validator

    def validate_contact(self, contact: Contact) -> tuple[bool, list[str]]:
        """Validate every field of a contact.

        Args:
            contact: The contact to validate.

        Returns:
            A ``(is_valid, errors)`` tuple. ``is_valid`` is ``True`` only
            if every present field passed its checks; ``errors`` lists
            every problem found (empty when ``is_valid`` is ``True``).
        """
        errors: list[str] = []

        errors.extend(self._validate_name(contact.name))
        errors.extend(self._validate_email(contact.email))
        errors.extend(self._validate_phone(contact.phone))
        errors.extend(self._validate_optional_text("company", contact.company))
        errors.extend(self._validate_optional_text("address", contact.address))

        is_valid = not errors
        if is_valid:
            logger.info("Contact %s passed validation", contact.id)
        else:
            logger.warning("Contact %s failed validation: %s", contact.id, "; ".join(errors))

        return is_valid, errors

    def _validate_name(self, name: object) -> list[str]:
        """Validate the ``name`` field: required, 3-100 characters."""
        if not name or not str(name).strip():
            return ["Name is missing or empty"]
        length = len(str(name).strip())
        if length < _MIN_NAME_LENGTH or length > _MAX_NAME_LENGTH:
            return [
                (
                    f"Name length must be between {_MIN_NAME_LENGTH} and "
                    f"{_MAX_NAME_LENGTH} characters, got {length}"
                )
            ]
        return []

    def _validate_email(self, email: object) -> list[str]:
        """Validate the ``email`` field via :class:`EmailValidator`, if present."""
        if not email:
            return []
        result = self.email_validator.validate(str(email))
        if result.is_valid:
            return []
        return [f"Invalid email: {'; '.join(result.errors) or 'unknown error'}"]

    def _validate_phone(self, phone: object) -> list[str]:
        """Validate the ``phone`` field via :class:`PhoneValidator`, if present."""
        if not phone:
            return []
        result = self.phone_validator.validate(str(phone))
        if result.is_valid:
            return []
        return [f"Invalid phone: {'; '.join(result.errors) or 'unknown error'}"]

    def _validate_optional_text(self, field_name: str, value: object) -> list[str]:
        """Validate an optional free-text field: not empty/whitespace-only if present."""
        if value is None:
            return []
        if not str(value).strip():
            return [f"{field_name.capitalize()} is present but empty"]
        return []
