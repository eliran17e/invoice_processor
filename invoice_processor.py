"""Normalize and validate invoice records produced by OCR."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple


# Nothing in the data says invoices start in 2020. This is a business rule we
# chose. The assignment entry point uses it as its default; callers processing
# an older backlog can opt into process_records_with_policy() to widen it.
MIN_INVOICE_DATE = date(2020, 1, 1)

# A flagged record is either unreadable or unwanted, and the two need different
# people to resolve them. SEVERITY_INVALID means the value could not be parsed,
# so it has to be re-read from the original scan. SEVERITY_SUSPICIOUS means the
# value parsed cleanly and one of our own business rules rejected it, so a
# reviewer can approve it as-is, or the rule can be widened.
SEVERITY_INVALID = "invalid"
SEVERITY_SUSPICIOUS = "suspicious"

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%b %d, %Y",
    "%Y/%m/%d",
)
_INVOICE_ID_PATTERN = re.compile(r"^INV-\d+$")
_AMOUNT_PATTERN = re.compile(
    r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$"
)
_MISSING_MARKERS = {"", "n/a", "na", "null", "none"}
_CENT = Decimal("0.01")


class _Reason(NamedTuple):
    """Why a record was flagged, carrying its severity from the point of failure."""

    message: str
    severity: str


def _invalid(message: str) -> _Reason:
    return _Reason(message, SEVERITY_INVALID)


def _suspicious(message: str) -> _Reason:
    return _Reason(message, SEVERITY_SUSPICIOUS)


def _normalize_amount(
    value: Any,
) -> tuple[Decimal | None, _Reason | None, str | None]:
    """
    Return (amount, reason, correction).

    The amount is rounded to cents. `reason` explains why parsing failed, and
    `correction` describes any character the parser altered on its own, so an
    edited figure is never indistinguishable from one the OCR read cleanly.
    """
    if value is None:
        return None, _invalid("amount is missing"), None

    if isinstance(value, bool):
        return None, _invalid("amount has an invalid format"), None

    if isinstance(value, (int, float, Decimal)):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None, _invalid("amount has an invalid format"), None

    if text.casefold() in _MISSING_MARKERS:
        return None, _invalid("amount is missing"), None

    original_text = text
    correction: str | None = None

    if text.startswith("$"):
        text = text[1:].strip()

    # OCR commonly confuses uppercase O with zero. Apply that correction only
    # when every other character already belongs to a numeric amount.
    if "O" in text:
        if not re.fullmatch(r"[0-9O,.+\-]+", text):
            return None, _invalid("amount has an invalid format"), None
        text = text.replace("O", "0")
        correction = (
            f"amount: read OCR 'O' as '0' ({original_text!r} -> {text!r})"
        )

    if not _AMOUNT_PATTERN.fullmatch(text):
        return None, _invalid("amount has an invalid format"), None

    try:
        amount = Decimal(text.replace(",", "")).quantize(_CENT)
    except InvalidOperation:
        return None, _invalid("amount has an invalid format"), None

    return amount, None, correction


def _normalize_date(value: Any) -> tuple[date | None, _Reason | None]:
    """Parse one of the documented input formats into a date."""
    if value is None:
        return None, _invalid("date is missing")

    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None
    if not isinstance(value, str):
        return None, _invalid("date is invalid or uses an unsupported format")

    text = value.strip()
    if text.casefold() in _MISSING_MARKERS:
        return None, _invalid("date is missing")

    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date(), None
        except ValueError:
            continue

    return None, _invalid("date is invalid or uses an unsupported format")


def _clean_invoice_id(value: Any) -> tuple[str | None, _Reason | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, _invalid("invoice_id is missing")
    if not isinstance(value, str):
        return None, _invalid("invoice_id has an invalid format")

    invoice_id = value.strip()
    if not _INVOICE_ID_PATTERN.fullmatch(invoice_id):
        # The INV-<digits> shape is our own convention, not a fact about the
        # data, so a readable id in another shape is a policy rejection. At
        # scale a whole vendor can use a different format, and that is a reason
        # to revisit the pattern rather than to re-read every scan.
        return None, _suspicious("invoice_id has an invalid format")
    return invoice_id, None


def _clean_vendor(value: Any) -> tuple[str | None, _Reason | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, _invalid("vendor is missing")
    if not isinstance(value, str):
        return None, _invalid("vendor has an invalid format")
    return value.strip(), None


class _ParsedRecord(NamedTuple):
    """One raw record after normalization, before duplicate detection."""

    source: dict[str, Any]
    invoice_id: str | None
    amount: Decimal | None
    invoice_date: date | None
    vendor: str | None
    reasons: list[_Reason]
    corrections: list[str]

    @property
    def identity(self) -> tuple[Any, ...]:
        """The normalized fields two records must share to be the same invoice."""
        return (self.amount, self.invoice_date, self.vendor)

    @property
    def severity(self) -> str:
        """A record that failed on any unreadable value is invalid overall."""
        if any(reason.severity == SEVERITY_INVALID for reason in self.reasons):
            return SEVERITY_INVALID
        return SEVERITY_SUSPICIOUS


def _parse_record(
    raw_record: dict, min_date: date, max_date: date
) -> _ParsedRecord:
    """Normalize every field and collect the reasons the record cannot be used.

    `min_date` and `max_date` are the caller's supported window, inclusive.
    """
    # Work with a copy so the caller's input is never mutated.
    source_record = dict(raw_record)
    reasons: list[_Reason] = []

    invoice_id, invoice_id_reason = _clean_invoice_id(
        source_record.get("invoice_id")
    )
    amount, amount_reason, amount_correction = _normalize_amount(
        source_record.get("amount")
    )
    invoice_date, date_reason = _normalize_date(source_record.get("date"))
    vendor, vendor_reason = _clean_vendor(source_record.get("vendor"))

    for reason in (
        invoice_id_reason,
        amount_reason,
        date_reason,
        vendor_reason,
    ):
        if reason:
            reasons.append(reason)

    # Both of these amounts parsed perfectly well, so both are business
    # questions rather than extraction failures. They are reported separately
    # because they ask the reviewer different things: whether a credit note is
    # genuine, or whether a zero is real rather than a scan that lost its
    # digits.
    if amount is not None:
        if amount < 0:
            reasons.append(_suspicious("amount is negative (possible credit note)"))
        elif amount == 0:
            reasons.append(_suspicious("amount is zero"))

    # Likewise the supported window: these dates are real, they are simply
    # outside the range the caller asked us to process.
    if invoice_date is not None:
        if invoice_date < min_date:
            reasons.append(
                _suspicious(
                    f"date is before the supported range ({min_date.isoformat()})"
                )
            )
        elif invoice_date > max_date:
            reasons.append(
                _suspicious(
                    f"date is after the supported range ({max_date.isoformat()})"
                )
            )

    return _ParsedRecord(
        source=source_record,
        invoice_id=invoice_id,
        amount=amount,
        invoice_date=invoice_date,
        vendor=vendor,
        reasons=reasons,
        corrections=[note for note in (amount_correction,) if note],
    )


def _mark_duplicates(parsed_records: list[_ParsedRecord]) -> None:
    """
    Append duplicate reasons in place, grouping records by invoice_id.

    Records are compared on their normalized values, so the same invoice read
    with different OCR formatting ("$1,200.00" and "1200") counts as a repeat
    rather than as a conflict.

    Only records that passed every other check take part, so a record that
    already failed is reported for that failure alone and never claims an
    invoice_id on behalf of a later valid record.

    The first valid occurrence of an invoice id is kept. Later occurrences are
    flagged as either exact or conflicting duplicates. This is intentionally a
    first-wins policy, matching the documented assumption for this exercise.
    """
    groups: dict[str, list[_ParsedRecord]] = {}
    for entry in parsed_records:
        if entry.invoice_id is not None and not entry.reasons:
            groups.setdefault(entry.invoice_id, []).append(entry)

    for invoice_id, group in groups.items():
        if len(group) == 1:
            continue

        # Every record here already parsed cleanly, so both duplicate outcomes
        # are business decisions rather than extraction failures.
        first = group[0]
        for entry in group[1:]:
            if entry.identity == first.identity:
                entry.reasons.append(
                    _suspicious(f"exact duplicate of invoice_id {invoice_id}")
                )
            else:
                entry.reasons.append(
                    _suspicious(f"conflicting duplicate for invoice_id {invoice_id}")
                )


def process_records_with_policy(
    raw_records: list[dict],
    *,
    min_date: date = MIN_INVOICE_DATE,
    max_date: date | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Takes the raw records and returns (clean_records, flagged_records).
    Flagged records also include a 'reason' field explaining why they were
    flagged.

    Clean records contain Decimal amounts, ISO-formatted date strings, and a
    'corrections' list naming any value the parser altered on its own.

    Flagged records preserve the original OCR values for auditability and add a
    'severity' of SEVERITY_INVALID (the value could not be read) or
    SEVERITY_SUSPICIOUS (it was read cleanly and a business rule rejected it).

    `min_date` and `max_date` bound the dates we accept, inclusive. Neither is
    derived from the data, so both are arguments: widen them to process an
    older backlog. `max_date` defaults to the day of processing, resolved on
    every call so a long-running process stays correct past midnight.
    """
    if max_date is None:
        max_date = date.today()
    if min_date > max_date:
        raise ValueError("min_date must be on or before max_date")

    parsed_records = [
        _parse_record(raw_record, min_date, max_date)
        for raw_record in raw_records
    ]
    _mark_duplicates(parsed_records)

    clean_records: list[dict] = []
    flagged_records: list[dict] = []

    for entry in parsed_records:
        if entry.reasons:
            flagged_record = dict(entry.source)
            flagged_record["reason"] = "; ".join(
                reason.message for reason in entry.reasons
            )
            flagged_record["severity"] = entry.severity
            flagged_records.append(flagged_record)
            continue

        clean_record = dict(entry.source)
        clean_record.update(
            {
                "invoice_id": entry.invoice_id,
                "amount": entry.amount,
                "date": entry.invoice_date.isoformat(),
                "vendor": entry.vendor,
                "corrections": entry.corrections,
            }
        )
        clean_records.append(clean_record)

    return clean_records, flagged_records


def process_records(
    raw_records: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Takes the raw records and returns (clean_records, flagged_records).

    This wrapper intentionally preserves the exact signature requested by the
    assignment. Use process_records_with_policy() when a caller needs a date
    window other than the documented defaults.
    """
    return process_records_with_policy(raw_records)
