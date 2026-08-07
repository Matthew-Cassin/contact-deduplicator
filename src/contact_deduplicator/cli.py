"""Command-line interface for contact-deduplicator, built on Click."""

from __future__ import annotations

import logging
import sys

import click

from .deduplicator import ContactDeduplicator
from .logger import configure_logging
from .models import DeduplicationError

__all__ = ["deduplicate"]


@click.command()
@click.argument("input_csv", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    default="deduplicated.csv",
    show_default=True,
    help="Path to write the deduplicated contacts CSV to.",
)
@click.option(
    "--report",
    default="merge_report.json",
    show_default=True,
    help="Path to write the JSON merge/audit report to.",
)
@click.option(
    "--threshold",
    default=0.90,
    show_default=True,
    type=float,
    help="Fuzzy name-match similarity threshold, from 0.0 to 1.0.",
)
@click.option(
    "--skip-validation",
    is_flag=True,
    default=False,
    help="Skip email/phone validation (faster; omits validation errors from the report).",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable verbose (INFO-level) logging to the console.",
)
def deduplicate(
    input_csv: str,
    output: str,
    report: str,
    threshold: float,
    skip_validation: bool,
    verbose: bool,
) -> None:
    """Deduplicate contact records in INPUT_CSV.

    Reads INPUT_CSV, detects duplicate contacts by exact email, exact
    phone, and fuzzy name matching, merges each duplicate group into a
    single best record, and writes the result to --output plus a JSON
    audit trail to --report.
    """
    if not 0.0 <= threshold <= 1.0:
        raise click.BadParameter(
            f"threshold must be between 0.0 and 1.0, got {threshold}", param_hint="--threshold"
        )

    if verbose:
        configure_logging(level=logging.INFO)

    try:
        deduplicator = ContactDeduplicator(
            name_similarity_threshold=threshold, skip_validation=skip_validation
        )
        contacts = deduplicator.load_csv(input_csv)
        result = deduplicator.deduplicate(contacts)
        deduplicator.save_results(result, output_csv=output, report_json=report)
    except DeduplicationError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Total records:     {result.total_records}")
    click.echo(f"Duplicates found:  {result.duplicates_found}")
    click.echo(f"Unique contacts:   {result.unique_records}")
    if result.errors:
        click.echo(f"Validation issues: {len(result.errors)} (see {report})")
    click.echo(f"\nSaved deduplicated contacts to {output}")
    click.echo(f"Saved merge report to {report}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(deduplicate())
