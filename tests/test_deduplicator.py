"""Tests for contact_deduplicator.deduplicator."""

import json

import pytest

from contact_deduplicator.deduplicator import ContactDeduplicator
from contact_deduplicator.matcher import calculate_completeness
from contact_deduplicator.models import Contact, DeduplicationError

FIXTURE_CSV = "tests/fixtures/sample_contacts.csv"


def make_contact(id_="1", name=None, email=None, phone=None, company=None, address=None):
    # completeness_score mirrors what load_csv would actually compute, so
    # tests that pick a "most complete" record behave like real data
    # rather than always tie-breaking on insertion order.
    score = calculate_completeness(name, email, phone, company, address)
    return Contact(id_, name, email, phone, company, address, score)


@pytest.fixture
def deduplicator():
    return ContactDeduplicator()


def write_csv(tmp_path, text, name="contacts.csv"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


class TestLoadCsv:
    """load_csv: column auto-detection, normalization, IDs, error handling."""

    def test_loads_the_sample_fixture(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        assert len(contacts) == 5
        assert contacts[0].name == "John Smith"
        assert contacts[0].email == "john@example.com"

    def test_assigns_sequential_row_based_ids(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        assert [c.id for c in contacts] == ["row-1", "row-2", "row-3", "row-4", "row-5"]

    def test_column_order_and_case_do_not_matter(self, deduplicator, tmp_path):
        csv_text = "PHONE,NAME,EMAIL\n555-1234,Alice,alice@example.com\n"
        path = write_csv(tmp_path, csv_text)
        contacts = deduplicator.load_csv(path)
        assert len(contacts) == 1
        assert contacts[0].name == "Alice"
        assert contacts[0].email == "alice@example.com"
        assert contacts[0].phone == "555-1234"

    def test_column_alias_variants_are_recognized(self, deduplicator, tmp_path):
        csv_text = "Full Name,E-mail,Telephone,Organization,Street Address\n"
        csv_text += "Bob Lee,bob@example.com,555-9999,Acme,1 Main St\n"
        path = write_csv(tmp_path, csv_text)
        contacts = deduplicator.load_csv(path)
        assert contacts[0].name == "Bob Lee"
        assert contacts[0].company == "Acme"
        assert contacts[0].address == "1 Main St"

    def test_missing_columns_become_none(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "name,email\nAlice,alice@example.com\n")
        contacts = deduplicator.load_csv(path)
        assert contacts[0].phone is None
        assert contacts[0].company is None
        assert contacts[0].address is None

    def test_extra_unrecognized_columns_are_ignored(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "name,favorite_color\nAlice,blue\n")
        contacts = deduplicator.load_csv(path)
        assert contacts[0].name == "Alice"
        assert not hasattr(contacts[0], "favorite_color")

    def test_whitespace_is_stripped_and_email_lowercased(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "name,email\n  Alice  ,  ALICE@EXAMPLE.COM  \n")
        contacts = deduplicator.load_csv(path)
        assert contacts[0].name == "Alice"
        assert contacts[0].email == "alice@example.com"

    def test_empty_cell_becomes_none(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "name,email\nAlice,\n")
        contacts = deduplicator.load_csv(path)
        assert contacts[0].email is None

    def test_completeness_score_reflects_populated_fields(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "name,email\nAlice,alice@example.com\n")
        contacts = deduplicator.load_csv(path)
        assert contacts[0].completeness_score == pytest.approx(0.4)  # 2 of 5 fields

    def test_empty_data_csv_returns_empty_list(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "name,email,phone,company,address\n")
        assert deduplicator.load_csv(path) == []

    def test_missing_file_raises_deduplication_error(self, deduplicator):
        with pytest.raises(DeduplicationError, match="not found"):
            deduplicator.load_csv("/no/such/file.csv")

    def test_zero_byte_file_raises_deduplication_error(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "")
        with pytest.raises(DeduplicationError, match="empty"):
            deduplicator.load_csv(path)

    def test_no_recognizable_columns_raises_deduplication_error(self, deduplicator, tmp_path):
        path = write_csv(tmp_path, "foo,bar\n1,2\n")
        with pytest.raises(DeduplicationError, match=r"[Nn]o recognizable"):
            deduplicator.load_csv(path)


class TestFindDuplicates:
    """find_duplicates: exact + fuzzy grouping, transitivity, edge cases."""

    def test_sample_fixture_produces_two_groups(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        groups = deduplicator.find_duplicates(contacts)
        sizes = sorted(len(g) for g in groups)
        assert sizes == [2, 2]

    def test_exact_email_group(self, deduplicator):
        a = make_contact("1", email="x@example.com")
        b = make_contact("2", email="x@example.com")
        c = make_contact("3", email="y@example.com")
        groups = deduplicator.find_duplicates([a, b, c])
        assert len(groups) == 1
        assert {contact.id for contact in groups[0]} == {"1", "2"}

    def test_exact_phone_group(self, deduplicator):
        a = make_contact("1", phone="555-0456")
        b = make_contact("2", phone="555-0456")
        groups = deduplicator.find_duplicates([a, b])
        assert len(groups) == 1

    def test_fuzzy_name_group(self, deduplicator):
        a = make_contact("1", name="Jon Smith")
        b = make_contact("2", name="John Smith")
        groups = deduplicator.find_duplicates([a, b])
        assert len(groups) == 1

    def test_transitive_grouping_across_different_methods(self, deduplicator):
        # A-B match by email; B-C match by phone. A and C never match
        # each other directly, but all three must end up in one group.
        a = make_contact("A", email="shared@example.com", phone="111-1111")
        b = make_contact("B", email="shared@example.com", phone="222-2222")
        c = make_contact("C", email="different@example.com", phone="222-2222")
        groups = deduplicator.find_duplicates([a, b, c])
        assert len(groups) == 1
        assert {contact.id for contact in groups[0]} == {"A", "B", "C"}

    def test_no_duplicates_returns_empty_list(self, deduplicator):
        a = make_contact("1", email="a@example.com", name="Alice")
        b = make_contact("2", email="b@example.com", name="Bob")
        assert deduplicator.find_duplicates([a, b]) == []

    def test_all_records_duplicate_returns_one_group(self, deduplicator):
        contacts = [make_contact(str(i), email="same@example.com") for i in range(4)]
        groups = deduplicator.find_duplicates(contacts)
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_empty_list_returns_empty_list(self, deduplicator):
        assert deduplicator.find_duplicates([]) == []

    def test_single_record_returns_empty_list(self, deduplicator):
        assert deduplicator.find_duplicates([make_contact()]) == []

    def test_non_list_input_raises_deduplication_error(self, deduplicator):
        with pytest.raises(DeduplicationError):
            deduplicator.find_duplicates("not a list")  # type: ignore[arg-type]


class TestMergeContacts:
    """merge_contacts: longest-value-wins field selection, primary id."""

    def test_longest_value_wins_per_field(self, deduplicator):
        a = make_contact("1", name="John Smith", company="Acme", address="123 Main St")
        b = make_contact("2", name="John Smith", company="Acme Corp", address="123 Main")
        merged = deduplicator.merge_contacts([a, b])
        assert merged.company == "Acme Corp"  # longer than "Acme"
        assert merged.address == "123 Main St"  # longer than "123 Main"

    def test_primary_id_is_the_most_complete_record(self, deduplicator):
        sparse = make_contact("1", email="x@example.com")
        full = make_contact(
            "2", name="X", email="x@example.com", phone="1", company="C", address="D"
        )
        merged = deduplicator.merge_contacts([sparse, full])
        assert merged.id == "2"

    def test_missing_field_stays_none_if_absent_everywhere(self, deduplicator):
        a = make_contact("1", name="A")
        b = make_contact("2", name="B")
        merged = deduplicator.merge_contacts([a, b])
        assert merged.company is None

    def test_field_filled_from_only_one_record_is_kept(self, deduplicator):
        a = make_contact("1", name="A", company="Acme")
        b = make_contact("2", name="A", company=None)
        merged = deduplicator.merge_contacts([a, b])
        assert merged.company == "Acme"

    def test_merged_contact_completeness_is_recomputed(self, deduplicator):
        a = make_contact("1", name="A")
        b = make_contact("2", email="a@example.com")
        merged = deduplicator.merge_contacts([a, b])
        assert merged.completeness_score == pytest.approx(0.4)  # name + email of 5

    def test_single_element_group_returned_unchanged(self, deduplicator):
        contact = make_contact("1", name="Solo")
        assert deduplicator.merge_contacts([contact]) is contact

    def test_empty_group_raises_deduplication_error(self, deduplicator):
        with pytest.raises(DeduplicationError, match="empty"):
            deduplicator.merge_contacts([])

    def test_sample_fixture_merge_matches_hand_verified_output(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        john_group = [c for c in contacts if c.id in ("row-1", "row-2")]
        merged = deduplicator.merge_contacts(john_group)
        assert merged.id == "row-1"
        assert merged.phone == "(555) 555-0123"  # longer than "555-0123"
        assert merged.company == "Acme Corp"      # longer than "Acme"
        assert merged.address == "123 Main Street"  # longer than "123 Main St"


class TestDeduplicateWorkflow:
    """deduplicate(): full orchestration, edge cases, validation."""

    def test_sample_fixture_end_to_end(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        result = deduplicator.deduplicate(contacts)
        assert result.total_records == 5
        assert result.unique_records == 3
        assert result.duplicates_found == 2
        assert len(result.merge_actions) == 2

    def test_sample_fixture_reasons_are_correct(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        result = deduplicator.deduplicate(contacts)
        reasons = {action.primary_id: action.reason for action in result.merge_actions}
        assert reasons["row-1"] == "exact_email"
        assert reasons["row-3"] == "exact_phone"

    def test_standalone_record_passes_through_unchanged(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        result = deduplicator.deduplicate(contacts)
        bob = next(c for c in result.deduplicated_contacts if c.id == "row-5")
        assert bob.name == "Bob Johnson"

    def test_empty_list_is_a_trivial_success(self, deduplicator):
        result = deduplicator.deduplicate([])
        assert result.total_records == 0
        assert result.unique_records == 0
        assert result.duplicates_found == 0
        assert result.merge_actions == []

    def test_single_record_has_no_duplicates(self, deduplicator):
        result = deduplicator.deduplicate([make_contact("1", name="Solo Solo")])
        assert result.total_records == 1
        assert result.unique_records == 1
        assert result.duplicates_found == 0

    def test_all_records_duplicate_collapses_to_one(self, deduplicator):
        contacts = [make_contact(str(i), email="same@example.com") for i in range(5)]
        result = deduplicator.deduplicate(contacts)
        assert result.total_records == 5
        assert result.unique_records == 1
        assert result.duplicates_found == 4

    def test_validation_errors_are_collected(self, deduplicator):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        result = deduplicator.deduplicate(contacts)
        # Every sample phone is missing an area code, so every row fails validation.
        assert len(result.errors) == 5
        assert all(":" in error for error in result.errors)

    def test_skip_validation_produces_no_errors(self):
        deduplicator = ContactDeduplicator(skip_validation=True)
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        result = deduplicator.deduplicate(contacts)
        assert result.errors == []

    def test_non_list_input_raises_deduplication_error(self, deduplicator):
        with pytest.raises(DeduplicationError):
            deduplicator.deduplicate("not a list")  # type: ignore[arg-type]

    def test_custom_threshold_changes_grouping(self):
        strict = ContactDeduplicator(name_similarity_threshold=0.99)
        contacts = [
            make_contact("1", name="John Smith"),
            make_contact("2", name="Jon Smith"),  # 95% similar
        ]
        assert strict.find_duplicates(contacts) == []

        loose = ContactDeduplicator(name_similarity_threshold=0.70)
        assert len(loose.find_duplicates(contacts)) == 1


class TestContactDeduplicatorConfiguration:
    def test_rejects_threshold_above_one(self):
        with pytest.raises(DeduplicationError):
            ContactDeduplicator(name_similarity_threshold=1.5)

    def test_rejects_negative_threshold(self):
        with pytest.raises(DeduplicationError):
            ContactDeduplicator(name_similarity_threshold=-0.1)

    def test_accepts_boundary_values(self):
        ContactDeduplicator(name_similarity_threshold=0.0)
        ContactDeduplicator(name_similarity_threshold=1.0)

    def test_default_threshold_is_0_90(self):
        assert ContactDeduplicator().name_similarity_threshold == 0.90


class TestSaveResults:
    """save_results: CSV + JSON report output."""

    def test_writes_deduplicated_csv(self, deduplicator, tmp_path):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        result = deduplicator.deduplicate(contacts)
        out_csv = str(tmp_path / "out.csv")
        out_json = str(tmp_path / "report.json")
        deduplicator.save_results(result, out_csv, out_json)

        import pandas as pd

        frame = pd.read_csv(out_csv)
        assert len(frame) == 3
        assert list(frame.columns) == [
            "id", "name", "email", "phone", "company", "address", "completeness_score",
        ]

    def test_writes_valid_json_report(self, deduplicator, tmp_path):
        contacts = deduplicator.load_csv(FIXTURE_CSV)
        result = deduplicator.deduplicate(contacts)
        out_csv = str(tmp_path / "out.csv")
        out_json = str(tmp_path / "report.json")
        deduplicator.save_results(result, out_csv, out_json)

        with open(out_json) as handle:
            data = json.load(handle)
        assert data["statistics"]["total_records"] == 5
        assert data["statistics"]["unique_records"] == 3
        assert len(data["merge_actions"]) == 2
        assert "timestamp" in data

    def test_handles_empty_result(self, deduplicator, tmp_path):
        result = deduplicator.deduplicate([])
        out_csv = str(tmp_path / "out.csv")
        out_json = str(tmp_path / "report.json")
        deduplicator.save_results(result, out_csv, out_json)

        import pandas as pd

        frame = pd.read_csv(out_csv)
        assert len(frame) == 0
        with open(out_json) as handle:
            data = json.load(handle)
        assert data["statistics"]["total_records"] == 0
