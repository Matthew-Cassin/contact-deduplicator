"""Tests for contact_deduplicator.models."""

import dataclasses

import pytest

from contact_deduplicator.models import (
    Contact,
    DeduplicationError,
    DeduplicationResult,
    MergeAction,
    MergeReport,
)


def make_contact(id_="1", name="John Smith", email="john@example.com", phone="+14158586273"):
    return Contact(
        id=id_, name=name, email=email, phone=phone, company=None, address=None,
        completeness_score=0.6,
    )


class TestContact:
    """Tests for the Contact dataclass."""

    def test_construction_keeps_all_fields(self):
        contact = make_contact()
        assert contact.id == "1"
        assert contact.name == "John Smith"
        assert contact.email == "john@example.com"
        assert contact.phone == "+14158586273"
        assert contact.company is None
        assert contact.address is None
        assert contact.completeness_score == 0.6

    def test_optional_fields_accept_none(self):
        contact = Contact("1", None, None, None, None, None, 0.0)
        assert contact.name is None
        assert contact.email is None

    def test_is_a_dataclass_with_the_documented_fields(self):
        field_names = {f.name for f in dataclasses.fields(Contact)}
        assert field_names == {
            "id", "name", "email", "phone", "company", "address", "completeness_score",
        }

    def test_equal_field_values_compare_equal(self):
        assert make_contact() == make_contact()

    def test_different_ids_are_not_equal(self):
        assert make_contact(id_="1") != make_contact(id_="2")


class TestMergeAction:
    """Tests for the MergeAction dataclass."""

    def test_construction_keeps_all_fields(self):
        merged = make_contact(id_="1")
        action = MergeAction(
            primary_id="1", merged_ids=["2", "3"], reason="exact_email", merged_contact=merged
        )
        assert action.primary_id == "1"
        assert action.merged_ids == ["2", "3"]
        assert action.reason == "exact_email"
        assert action.merged_contact is merged

    def test_merged_ids_defaults_are_not_shared_between_instances(self):
        merged = make_contact()
        first = MergeAction("1", ["2"], "exact_email", merged)
        second = MergeAction("1", [], "exact_email", merged)
        first.merged_ids.append("x")
        assert second.merged_ids == []


class TestDeduplicationResult:
    """Tests for the DeduplicationResult dataclass."""

    def test_minimal_construction_applies_defaults(self):
        result = DeduplicationResult(total_records=0, unique_records=0, duplicates_found=0)
        assert result.merge_actions == []
        assert result.deduplicated_contacts == []
        assert result.errors == []

    def test_full_construction_keeps_all_fields(self):
        contact = make_contact()
        result = DeduplicationResult(
            total_records=5,
            unique_records=3,
            duplicates_found=2,
            merge_actions=[],
            deduplicated_contacts=[contact],
            errors=["row-1: bad phone"],
        )
        assert result.total_records == 5
        assert result.unique_records == 3
        assert result.duplicates_found == 2
        assert result.deduplicated_contacts == [contact]
        assert result.errors == ["row-1: bad phone"]

    def test_default_lists_are_not_shared_between_instances(self):
        first = DeduplicationResult(total_records=0, unique_records=0, duplicates_found=0)
        second = DeduplicationResult(total_records=0, unique_records=0, duplicates_found=0)
        first.errors.append("oops")
        first.deduplicated_contacts.append(make_contact())
        assert second.errors == []
        assert second.deduplicated_contacts == []


class TestMergeReport:
    """Tests for the MergeReport dataclass and its (de)serialization helpers."""

    def _sample_result(self):
        merged = make_contact(id_="row-1")
        action = MergeAction("row-1", ["row-2"], "exact_email", merged)
        return DeduplicationResult(
            total_records=2,
            unique_records=1,
            duplicates_found=1,
            merge_actions=[action],
            deduplicated_contacts=[merged],
            errors=["row-2: Invalid phone: Wrong length for a phone number"],
        )

    def test_from_result_copies_statistics(self):
        report = MergeReport.from_result(self._sample_result())
        assert report.total_records == 2
        assert report.unique_records == 1
        assert report.duplicates_found == 1
        assert len(report.merge_actions) == 1
        assert report.validation_errors == [
            "row-2: Invalid phone: Wrong length for a phone number"
        ]

    def test_from_result_sets_an_iso_timestamp(self):
        report = MergeReport.from_result(self._sample_result())
        # Should parse cleanly as an ISO 8601 timestamp; raises if not.
        from datetime import datetime

        datetime.fromisoformat(report.timestamp)

    def test_to_dict_has_expected_top_level_keys(self):
        report = MergeReport.from_result(self._sample_result())
        data = report.to_dict()
        assert set(data.keys()) == {
            "timestamp", "statistics", "merge_actions", "validation_errors"
        }

    def test_to_dict_statistics_block(self):
        report = MergeReport.from_result(self._sample_result())
        data = report.to_dict()
        assert data["statistics"] == {
            "total_records": 2,
            "unique_records": 1,
            "duplicates_found": 1,
            "validation_error_count": 1,
        }

    def test_to_dict_expands_merge_actions_and_merged_contact(self):
        report = MergeReport.from_result(self._sample_result())
        data = report.to_dict()
        action = data["merge_actions"][0]
        assert action["primary_id"] == "row-1"
        assert action["merged_ids"] == ["row-2"]
        assert action["reason"] == "exact_email"
        assert action["merged_contact"]["id"] == "row-1"
        assert action["merged_contact"]["name"] == "John Smith"

    def test_to_dict_is_json_serializable(self):
        import json

        report = MergeReport.from_result(self._sample_result())
        json.dumps(report.to_dict())  # raises if not serializable


class TestDeduplicationError:
    """Tests for the DeduplicationError exception type."""

    def test_is_an_exception_subclass(self):
        assert issubclass(DeduplicationError, Exception)

    def test_raises_and_preserves_message(self):
        with pytest.raises(DeduplicationError, match="boom"):
            raise DeduplicationError("boom")
