# AI transcript 1 — Codex (requirements analysis and first implementation)

First AI session for the OCR invoice assignment. Codex analyzed the requirements,
proposed the validation rules, and produced the initial implementation and test
suite. The second session (`02-claude-code.md`) reviewed the result.

Exported from Codex. The assignment PDF was attached to the first message.

---

### 🧑 User — 4:35 PM

can you start explore this task, explain to me everything I should know and consider before starting it and let me know how I can implement it the best way possible.

*(assignment PDF attached: `junior-swe-home-assignment_final (2).pdf`)*

### 🤖 Codex — worked for 15m 12s

I reviewed the complete two-page assignment: junior-swe-home-assignment_final (2).pdf.

The assignment is deliberately small. They are primarily evaluating your judgment, validation process, and ability to explain decisions—not whether you can build a complicated data-processing system.

**What you need to deliver**

You need three things:

1. A Python implementation exposing exactly:

```python
def process_records(raw_records: list[dict]) -> tuple[list[dict], list[dict]]:
```

2. A short write-up explaining:
   - Your validation assumptions.
   - Ambiguous formats and edge cases.
   - How you used AI.
   - What you tested or changed after reviewing AI output.

3. This AI conversation as a shared link or exported transcript.

Keep that last requirement in mind: this conversation is part of your submission evidence.

**Recommended solution design**

Use three small layers:

```
process_records()
    ├── normalize_amount()
    ├── normalize_date()
    └── validate_record()
```

Avoid pandas, Pydantic, databases, or a large class hierarchy. A plain Python module with small helper functions is the best fit for the stated 2–3 hour scope.

A clean project would be:

```
invoice_processor.py
test_invoice_processor.py
README.md
```

The README can serve as the requested half-page write-up.

**Assumptions I recommend**

*Amounts*

- Remove surrounding whitespace.
- Treat blank strings and values such as `N/A`, `NA`, or `NULL` as missing.
- Accept `$` and comma thousands separators.
- Correct uppercase `O` to `0` only when it occurs in an otherwise numeric-looking amount.
- Parse money using `Decimal`, not `float`.
- Quantize accepted amounts to two decimal places.
- Flag zero or negative amounts as suspicious.

Using `Decimal` demonstrates awareness that binary floating-point is undesirable for financial values.

Do not remove every nonnumeric character indiscriminately. For example, `"12ABC34"` should be rejected, not silently converted into `1234`.

*Dates*

Accept only the formats demonstrated by the assignment:

```python
"%Y-%m-%d"   # 2024-01-05
"%m/%d/%Y"   # 01/06/2024
"%b %d, %Y"  # Jan 8, 2024
"%Y/%m/%d"   # 2024/01/09
```

Normalize valid dates to an ISO string: `2024-01-08`

Explicitly document that `01/06/2024` is interpreted as US-style `MM/DD/YYYY`, making it January 6 rather than June 1.

Use strict `datetime.strptime` parsing. This naturally rejects `2024-13-40`.

For suspicious date ranges, a reasonable documented rule is:

- Before 2020-01-01: suspicious.
- After today, or perhaps more than 30 days into the future: suspicious.

Put these limits in named constants so the business rule is visible and easy to change.

*Vendors and invoice IDs*

Although the task only explicitly says to normalize amounts and dates, an empty vendor is clearly suspicious.

I would validate:

- `invoice_id` is present and nonblank.
- Optionally, it matches `INV-\d+`.
- `vendor` is present and nonblank.

Avoid inventing excessive validation rules that the supplied data cannot justify.

*Duplicates*

Do not silently discard duplicates.

A strong, explainable policy is:

- Keep the first occurrence of an exact duplicate.
- Put later occurrences into `flagged_records`.
- Give them a reason such as `"Exact duplicate of invoice INV-1001"`.

Use `invoice_id` as the business identifier. You should also consider the hypothetical case where two records share an invoice ID but contain different details. Those should be flagged as conflicting duplicates rather than choosing one silently.

*Flagged record representation*

Preserve the original raw values in flagged records and add a reason:

```python
{
    "invoice_id": "INV-1003",
    "amount": "N/A",
    "date": "2024-01-07",
    "vendor": "Acme Corp",
    "reason": "Missing or invalid amount",
}
```

This maintains auditability: someone reviewing the failure can see exactly what OCR produced.

For valid records, return normalized fields.

Accumulate all applicable reasons rather than stopping at the first problem:

```python
reason = "; ".join(reasons)
```

That matters for `INV-1005`, which has both a negative amount and an impossible date.

**Recommended outcome for every sample row**

| Input | Result | Reason or normalization |
| --- | --- | --- |
| `INV-1001` first occurrence | Clean | Amount `Decimal("1200.00")`, date `2024-01-05` |
| `INV-1002` | Clean | Correct `95O.5` to `Decimal("950.50")`; interpret date as January 6 |
| `INV-1003` | Flagged | Amount is `N/A` |
| `INV-1004` | Flagged | Vendor is missing; date can still be recognized as `2024-01-08` |
| `INV-1001` second occurrence | Flagged | Exact duplicate |
| `INV-1005` | Flagged | Negative amount and impossible date |
| `INV-1006` | Flagged | Blank amount |
| `INV-1007` | Flagged | Date is earlier than the documented acceptable range |

That gives 2 clean records and 6 flagged records.

This is not the only defensible classification. What matters is that your policy is consistent and documented.

**Important implementation details**

Your function should not modify the caller's input dictionaries. Copy each record before adding fields or normalizing values:

```python
record_copy = dict(raw_record)
```

The processing order should be approximately:

1. Copy the raw record.
2. Normalize amount and date into temporary values.
3. Gather validation reasons.
4. Check duplicate status.
5. If reasons exist, preserve the raw record and attach the joined reason.
6. Otherwise, create a normalized clean record.
7. Return both lists in predictable input order.

Keep normalization and validation distinct where practical. A parse failure means invalid; a successfully parsed but unusually old date means suspicious.

**Tests you should include**

At minimum, test:

- The exact supplied eight-record dataset.
- There are two clean and six flagged records under your chosen policy.
- `"$1,200.00"` becomes `Decimal("1200.00")`.
- `"95O.5"` becomes `Decimal("950.50")`.
- `"Jan 8, 2024"` becomes `"2024-01-08"`.
- `"2024-13-40"` is rejected.
- `01/06/2024` becomes January 6.
- The second `INV-1001` is identified as a duplicate.
- Multiple problems produce multiple reasons.
- The original `raw_records` input is unchanged.
- An empty list returns `([], [])`.
- Missing keys or `None` values do not crash the function.
- An OCR correction is not overly permissive—for example, `"ONE HUNDRED"` remains invalid.

Run the tests and include the command/result in your write-up:

```bash
pytest -q
```

**Common mistakes to avoid**

- Using broad date parsing that silently guesses ambiguous dates.
- Replacing every `O` everywhere instead of only in numeric context.
- Using `float` without acknowledging financial precision.
- Dropping the duplicate silently.
- Returning only the first error for a record with several problems.
- Mutating the original input.
- Normalizing invalid records so aggressively that the original OCR value is lost.
- Adding arbitrary rules without documenting why they exist.
- Producing polished code without demonstrating that it was actually run against every sample row.

**Suggested build order**

A sensible 2–3 hour workflow is:

1. Write your assumptions before coding.
2. Implement and test amount normalization.
3. Implement and test strict date normalization.
4. Add record validation and accumulated reasons.
5. Add duplicate handling.
6. Run the exact sample and inspect all eight results manually.
7. Add targeted edge-case tests.
8. Write the short README while the decisions are fresh.
9. Export or share this AI conversation.

For the AI section, be completely factual. You can say that you asked AI to analyze the requirements, propose validation rules, identify ambiguity around dates and duplicates, and recommend tests. Then explain which decisions you accepted, rejected, or tightened after running the implementation. That directly matches what the evaluators say they want.

---

### 🧑 User — 7:47 PM

can you start building it? and let me know if there is some judgemental call I should answer

### 🤖 Codex — worked for 3m 38s

The initial submission-ready version is built.

- `invoice_processor.py` (line 118) implements normalization, validation, duplicate handling, and reasons.
- `test_invoice_processor.py` (line 65) contains nine tests, including the exact assignment dataset.
- `README.md` (line 19) documents assumptions, edge cases, execution, and an AI-usage draft.

Verification succeeded:

- 9 tests passed
- Python compilation passed
- Sample result: 2 clean, 6 flagged

The judgment calls for you to confirm are:

1. **Old-date threshold:** Currently anything before 2020-01-01 is flagged.
2. **Negative amounts:** Currently flagged. They could be valid credit notes in some systems.
3. **OCR correction:** `95O.5` is automatically corrected and accepted as clean.
4. **Duplicates:** The first invoice ID is kept; subsequent identical or conflicting records are flagged. For conflicting duplicates, a more conservative policy would flag both records.
5. **Flagged output:** Original OCR values are preserved instead of partially normalized.
6. **Money type:** Clean amounts use `Decimal`, which is safer for money but not directly JSON-serializable.

My recommendation is to keep all current defaults for this assignment. The only one worth serious consideration is conflicting duplicates: production systems might flag both, but "keep first and flag later" is simpler and explicitly documented.

Before submission, rewrite the AI section in `README.md` (line 37) in your own voice while keeping it honest.

---

*This session produced the first implementation. It passed 9 tests and produced the
expected 2 clean / 6 flagged on the sample data, and closed by recommending that
every default be kept. The second session tested inputs the sample does not
contain and found two bugs — see `02-claude-code.md`.*
