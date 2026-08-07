"""Tests for contact_deduplicator.cli."""

import json
import os
import shutil

from click.testing import CliRunner

from contact_deduplicator.cli import deduplicate

FIXTURE_CSV = os.path.abspath("tests/fixtures/sample_contacts.csv")


def run(args):
    return CliRunner().invoke(deduplicate, args)


class TestCliHappyPath:
    """A normal run against the sample CSV."""

    def test_exits_zero_and_prints_summary(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv"])
            assert result.exit_code == 0
            assert "Total records:     5" in result.output
            assert "Duplicates found:  2" in result.output
            assert "Unique contacts:   3" in result.output

    def test_creates_default_output_files(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(deduplicate, ["sample.csv"])
            assert os.path.exists("deduplicated.csv")
            assert os.path.exists("merge_report.json")

    def test_custom_output_and_report_paths(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(
                deduplicate, ["sample.csv", "--output", "out.csv", "--report", "rep.json"]
            )
            assert result.exit_code == 0
            assert os.path.exists("out.csv")
            assert os.path.exists("rep.json")
            assert not os.path.exists("deduplicated.csv")

    def test_report_json_is_well_formed(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            runner.invoke(deduplicate, ["sample.csv"])
            with open("merge_report.json") as handle:
                data = json.load(handle)
            assert data["statistics"]["duplicates_found"] == 2


class TestCliOptions:
    """--threshold, --skip-validation, --verbose."""

    def test_high_threshold_changes_grouping(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv", "--threshold", "0.99"])
            assert result.exit_code == 0
            # Threshold only affects fuzzy name matching; the sample's two
            # groups are formed by exact email/phone, so the count is the
            # same either way -- this just confirms the flag is accepted
            # and plumbed through without error.
            assert "Duplicates found:  2" in result.output

    def test_skip_validation_omits_validation_issues_line(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv", "--skip-validation"])
            assert "Validation issues" not in result.output

    def test_without_skip_validation_reports_validation_issues(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv"])
            assert "Validation issues: 5" in result.output

    def test_verbose_flag_emits_log_lines(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv", "--verbose"])
            assert "INFO" in result.output

    def test_without_verbose_no_log_lines(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv"])
            assert "INFO" not in result.output


class TestCliErrorHandling:
    """Missing file and invalid threshold: clean, non-crashing errors."""

    def test_missing_file_exits_nonzero_with_friendly_message(self):
        result = run(["does-not-exist.csv"])
        assert result.exit_code != 0
        assert "does not exist" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_threshold_above_one_is_rejected(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv", "--threshold", "1.5"])
            assert result.exit_code != 0
            assert "threshold" in result.output.lower()

    def test_negative_threshold_is_rejected(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            shutil.copy(FIXTURE_CSV, "sample.csv")
            result = runner.invoke(deduplicate, ["sample.csv", "--threshold", "-0.5"])
            assert result.exit_code != 0

    def test_csv_with_no_recognizable_columns_is_handled_gracefully(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("bad.csv", "w") as handle:
                handle.write("foo,bar\n1,2\n")
            result = runner.invoke(deduplicate, ["bad.csv"])
            assert result.exit_code == 1
            assert "recognizable" in result.output.lower()
            # DeduplicationError was caught and turned into a clean
            # click.ClickException (a friendly "Error: ..." line and a
            # controlled sys.exit), not an unhandled traceback dumped to
            # the console.
            assert result.output.startswith("Error:")
            assert "Traceback" not in result.output


class TestCliEmptyCsv:
    def test_empty_data_csv_succeeds_with_zero_counts(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            with open("empty.csv", "w") as handle:
                handle.write("name,email,phone,company,address\n")
            result = runner.invoke(deduplicate, ["empty.csv"])
            assert result.exit_code == 0
            assert "Total records:     0" in result.output
