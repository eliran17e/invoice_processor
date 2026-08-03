"""Tests for the OCR invoice normalization exercise."""

from __future__ import annotations

import copy
import inspect
import unittest
from datetime import date, timedelta
from decimal import Decimal

from invoice_processor import (
    SEVERITY_INVALID,
    SEVERITY_SUSPICIOUS,
    process_records,
    process_records_with_policy,
)


RAW_RECORDS = [
    {
        "invoice_id": "INV-1001",
        "amount": "$1,200.00",
        "date": "2024-01-05",
        "vendor": "Acme Corp",
    },
    {
        "invoice_id": "INV-1002",
        "amount": "95O.5",
        "date": "01/06/2024",
        "vendor": "Beta LLC",
    },
    {
        "invoice_id": "INV-1003",
        "amount": "N/A",
        "date": "2024-01-07",
        "vendor": "Acme Corp",
    },
    {
        "invoice_id": "INV-1004",
        "amount": "2,340",
        "date": "Jan 8, 2024",
        "vendor": "",
    },
    {
        "invoice_id": "INV-1001",
        "amount": "$1,200.00",
        "date": "2024-01-05",
        "vendor": "Acme Corp",
    },
    {
        "invoice_id": "INV-1005",
        "amount": "-450.00",
        "date": "2024-13-40",
        "vendor": "Gamma Inc",
    },
    {
        "invoice_id": "INV-1006",
        "amount": " ",
        "date": "2024/01/09",
        "vendor": "Delta Co",
    },
    {
        "invoice_id": "INV-1007",
        "amount": "3200.00",
        "date": "2019-01-10",
        "vendor": "Acme Corp",
    },
]


class ProcessRecordsTests(unittest.TestCase):
    def test_assignment_entry_point_keeps_the_exact_signature(self) -> None:
        parameters = list(inspect.signature(process_records).parameters)
        self.assertEqual(parameters, ["raw_records"])

    def test_exact_assignment_data(self) -> None:
        clean, flagged = process_records(RAW_RECORDS)

        self.assertEqual(
            [record["invoice_id"] for record in clean],
            ["INV-1001", "INV-1002"],
        )
        self.assertEqual(len(flagged), 6)
        self.assertEqual(clean[0]["amount"], Decimal("1200.00"))
        self.assertEqual(clean[0]["date"], "2024-01-05")
        self.assertEqual(clean[1]["amount"], Decimal("950.50"))
        self.assertEqual(clean[1]["date"], "2024-01-06")

        reasons = [record["reason"] for record in flagged]
        self.assertTrue(any("amount is missing" in reason for reason in reasons))
        self.assertTrue(any("vendor is missing" in reason for reason in reasons))
        self.assertTrue(any("exact duplicate" in reason for reason in reasons))
        self.assertTrue(any("amount is negative" in reason for reason in reasons))
        self.assertTrue(any("date is invalid" in reason for reason in reasons))
        self.assertTrue(
            any("before the supported range" in reason for reason in reasons)
        )

    def test_severity_separates_unreadable_from_unwanted(self) -> None:
        clean, flagged = process_records(RAW_RECORDS)

        severity_by_reason = {
            record["reason"]: record["severity"] for record in flagged
        }
        self.assertEqual(
            severity_by_reason["amount is missing"], SEVERITY_INVALID
        )
        self.assertEqual(
            severity_by_reason["vendor is missing"], SEVERITY_INVALID
        )
        self.assertEqual(
            severity_by_reason["exact duplicate of invoice_id INV-1001"],
            SEVERITY_SUSPICIOUS,
        )
        self.assertEqual(
            severity_by_reason[
                "date is before the supported range (2020-01-01)"
            ],
            SEVERITY_SUSPICIOUS,
        )
        # Clean records carry no severity at all.
        self.assertTrue(all("severity" not in record for record in clean))

    def test_invalid_wins_over_suspicious(self) -> None:
        """INV-1005 has an unreadable date and a readable negative amount."""
        _, flagged = process_records(
            [
                {
                    "invoice_id": "INV-1005",
                    "amount": "-450.00",
                    "date": "2024-13-40",
                    "vendor": "Gamma Inc",
                }
            ]
        )

        self.assertIn("date is invalid", flagged[0]["reason"])
        self.assertIn("amount is negative", flagged[0]["reason"])
        self.assertEqual(flagged[0]["severity"], SEVERITY_INVALID)

    def test_zero_and_negative_ask_different_questions(self) -> None:
        """Both parsed cleanly, but a reviewer checks two different things."""
        _, flagged = process_records(
            [
                {
                    "invoice_id": "INV-8101",
                    "amount": "-450.00",
                    "date": "2024-01-01",
                    "vendor": "V",
                },
                {
                    "invoice_id": "INV-8102",
                    "amount": "0.00",
                    "date": "2024-01-01",
                    "vendor": "V",
                },
            ]
        )

        self.assertIn("negative", flagged[0]["reason"])
        self.assertIn("credit note", flagged[0]["reason"])
        self.assertEqual(flagged[1]["reason"], "amount is zero")
        for record in flagged:
            self.assertEqual(record["severity"], SEVERITY_SUSPICIOUS)

    def test_caller_can_widen_the_supported_date_window(self) -> None:
        """The 2020 cutoff is our policy, not a property of the data."""
        clean, flagged = process_records_with_policy(
            RAW_RECORDS, min_date=date(2018, 1, 1)
        )

        self.assertEqual(len(clean), 3)
        self.assertEqual(len(flagged), 5)
        self.assertIn("INV-1007", [record["invoice_id"] for record in clean])

    def test_max_date_is_resolved_per_call(self) -> None:
        """A caller processing a backlog can accept dates we would call future."""
        record = {
            "invoice_id": "INV-8201",
            "amount": "100.00",
            "date": (date.today() + timedelta(days=30)).isoformat(),
            "vendor": "V",
        }

        _, flagged = process_records([record])
        self.assertIn("after the supported range", flagged[0]["reason"])

        clean, _ = process_records_with_policy(
            [record], max_date=date.today() + timedelta(days=60)
        )
        self.assertEqual(len(clean), 1)

    def test_negative_amount_alone_is_suspicious(self) -> None:
        """A credit note is readable, so a reviewer can approve it as-is."""
        _, flagged = process_records(
            [
                {
                    "invoice_id": "INV-8001",
                    "amount": "-450.00",
                    "date": "2024-01-01",
                    "vendor": "Gamma Inc",
                }
            ]
        )

        self.assertEqual(flagged[0]["severity"], SEVERITY_SUSPICIOUS)

    def test_unrecognized_invoice_id_shape_is_suspicious(self) -> None:
        """The INV- convention is our rule, not a fact about the data."""
        _, flagged = process_records(
            [
                {
                    "invoice_id": "ACME-2024-01",
                    "amount": "100.00",
                    "date": "2024-01-01",
                    "vendor": "Acme Corp",
                },
                {
                    "invoice_id": "",
                    "amount": "100.00",
                    "date": "2024-01-01",
                    "vendor": "Acme Corp",
                },
            ]
        )

        self.assertEqual(flagged[0]["severity"], SEVERITY_SUSPICIOUS)
        self.assertEqual(flagged[1]["severity"], SEVERITY_INVALID)

    def test_input_is_not_mutated(self) -> None:
        original = copy.deepcopy(RAW_RECORDS)
        process_records(RAW_RECORDS)
        self.assertEqual(RAW_RECORDS, original)

    def test_empty_input(self) -> None:
        self.assertEqual(process_records([]), ([], []))

    def test_supported_date_formats_are_normalized(self) -> None:
        records = [
            {
                "invoice_id": f"INV-{index}",
                "amount": "10",
                "date": raw_date,
                "vendor": "Test Vendor",
            }
            for index, raw_date in enumerate(
                ("2024-01-05", "01/06/2024", "Jan 8, 2024", "2024/01/09"),
                start=1,
            )
        ]

        clean, flagged = process_records(records)

        self.assertEqual(flagged, [])
        self.assertEqual(
            [record["date"] for record in clean],
            ["2024-01-05", "2024-01-06", "2024-01-08", "2024-01-09"],
        )

    def test_ocr_correction_is_limited_to_numeric_context(self) -> None:
        record = {
            "invoice_id": "INV-2001",
            "amount": "ONE HUNDRED",
            "date": "2024-01-01",
            "vendor": "Test Vendor",
        }

        clean, flagged = process_records([record])

        self.assertEqual(clean, [])
        self.assertIn("invalid format", flagged[0]["reason"])

    def test_ocr_correction_is_recorded_on_the_clean_record(self) -> None:
        """An auto-edited amount must never look like a clean OCR read."""
        records = [
            {
                "invoice_id": "INV-7001",
                "amount": "95O.5",
                "date": "2024-01-01",
                "vendor": "Test Vendor",
            },
            {
                "invoice_id": "INV-7002",
                "amount": "950.50",
                "date": "2024-01-01",
                "vendor": "Test Vendor",
            },
        ]

        clean, _ = process_records(records)

        self.assertEqual(clean[0]["amount"], clean[1]["amount"])
        self.assertEqual(len(clean[0]["corrections"]), 1)
        self.assertIn("95O.5", clean[0]["corrections"][0])
        self.assertEqual(clean[1]["corrections"], [])

    def test_multiple_problems_are_reported_together(self) -> None:
        record = {
            "invoice_id": "bad-id",
            "amount": "-10",
            "date": "not-a-date",
            "vendor": " ",
        }

        _, flagged = process_records([record])

        reason = flagged[0]["reason"]
        self.assertIn("invoice_id", reason)
        self.assertIn("amount is negative", reason)
        self.assertIn("date is invalid", reason)
        self.assertIn("vendor is missing", reason)

    def test_missing_fields_do_not_crash_processing(self) -> None:
        clean, flagged = process_records([{}])

        self.assertEqual(clean, [])
        self.assertEqual(len(flagged), 1)
        self.assertIn("invoice_id is missing", flagged[0]["reason"])
        self.assertIn("amount is missing", flagged[0]["reason"])

    def test_future_date_is_flagged(self) -> None:
        record = {
            "invoice_id": "INV-3001",
            "amount": "100.00",
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "vendor": "Test Vendor",
        }

        _, flagged = process_records([record])

        self.assertIn("after the supported range", flagged[0]["reason"])

    def test_duplicate_detection_ignores_ocr_formatting(self) -> None:
        """The same invoice read two different ways is a repeat, not a conflict."""
        records = [
            {
                "invoice_id": "INV-5001",
                "amount": "$1,200.00",
                "date": "2024-01-05",
                "vendor": "Acme Corp",
            },
            {
                "invoice_id": "INV-5001",
                "amount": "1200",
                "date": "01/05/2024",
                "vendor": " Acme Corp ",
            },
        ]

        clean, flagged = process_records(records)

        self.assertEqual(len(clean), 1)
        self.assertIn("exact duplicate", flagged[0]["reason"])
        self.assertNotIn("conflicting", flagged[0]["reason"])

    def test_flagged_record_does_not_claim_the_invoice_id(self) -> None:
        """A later valid record is kept even if an unusable one came first."""
        records = [
            {
                "invoice_id": "INV-6001",
                "amount": "N/A",
                "date": "2024-01-05",
                "vendor": "Acme Corp",
            },
            {
                "invoice_id": "INV-6001",
                "amount": "500.00",
                "date": "2024-01-05",
                "vendor": "Acme Corp",
            },
        ]

        clean, flagged = process_records(records)

        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["amount"], Decimal("500.00"))
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["reason"], "amount is missing")

    def test_conflicting_duplicate_keeps_first_and_flags_later_record(self) -> None:
        """The documented policy keeps the first valid invoice id."""
        records = [
            {
                "invoice_id": "INV-4001",
                "amount": "100.00",
                "date": "2024-01-01",
                "vendor": "Vendor One",
            },
            {
                "invoice_id": "INV-4001",
                "amount": "200.00",
                "date": "2024-01-01",
                "vendor": "Vendor One",
            },
        ]

        clean, flagged = process_records(records)

        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["amount"], Decimal("100.00"))
        self.assertEqual(len(flagged), 1)
        self.assertIn("conflicting duplicate", flagged[0]["reason"])
        self.assertEqual(flagged[0]["severity"], SEVERITY_SUSPICIOUS)
        self.assertEqual(flagged[0]["amount"], "200.00")


if __name__ == "__main__":
    unittest.main()
