# OCR Invoice Record Processor

This small Python module normalizes and validates invoice records produced by OCR. Its public entry point is:

```python
def process_records(raw_records: list[dict]) -> tuple[list[dict], list[dict]]:
```

Valid records are returned with `Decimal` amounts, ISO `YYYY-MM-DD` dates, and a `corrections` list recording any safe OCR repair. Flagged records retain their original OCR values and add human-readable `reason` and `severity` fields.

The required `process_records` function keeps the exact assignment signature. A second entry point allows callers to override the date policy without changing the assignment contract:

```python
process_records_with_policy(raw_records, min_date=..., max_date=...)
```

## Running the tests

The project uses only the Python standard library:

```bash
python3 -m unittest -v
```

20 tests. The first two pin the required signature and run the exact eight records from the assignment.

## Output

**Clean records** carry a `Decimal` amount, an ISO date, and a `corrections` list:

```python
{'invoice_id': 'INV-1002',
 'amount': Decimal('950.50'),
 'date': '2024-01-06',
 'vendor': 'Beta LLC',
 'corrections': ["amount: read OCR 'O' as '0' ('95O.5' -> '950.5')"]}
```

**Flagged records** keep their original OCR values and add `reason` and `severity`:

```python
{'invoice_id': 'INV-1007',
 'amount': '3200.00',
 'date': '2019-01-10',
 'vendor': 'Acme Corp',
 'reason': 'date is before the supported range (2020-01-01)',
 'severity': 'suspicious'}
```

## Severity: unreadable vs. unwanted

The assignment asks for records that look *suspicious or invalid*. Those are two different problems that need different people to resolve, so flagged records say which:

- **`invalid`** — the value could not be read. It has to be re-read from the original scan. Nobody can approve `'N/A'` as an amount.
- **`suspicious`** — the value was read perfectly and one of *our own rules* rejected it. A reviewer can approve it as-is, or the rule can be widened.

| Reason | Severity |
| --- | --- |
| `amount is missing` / `amount has an invalid format` | invalid |
| `amount is negative (possible credit note)` / `amount is zero` | suspicious |
| `date is missing` / `date is invalid or uses an unsupported format` | invalid |
| `date is before/after the supported range` | suspicious |
| `vendor is missing` | invalid |
| `invoice_id is missing` | invalid |
| `invoice_id has an invalid format` | suspicious |
| `exact duplicate` / `conflicting duplicate` | suspicious |

`invoice_id has an invalid format` is the one genuinely close call. The `INV-<digits>` shape is our convention, not a property of the data: a vendor numbering invoices `ACME-2024-01` produces a perfectly readable id that our pattern happens to reject. At scale, routing those to a re-keying queue wastes the reviewer's time and hides the real problem, which is that our pattern is too narrow — so it is `suspicious`. A missing id is `invalid`.

Severity classifies the *routing*, not the data: a flagged record never enters `clean_records` regardless of its label.

## Assumptions

- Money is parsed with `Decimal` and normalized to two decimal places. Dollar signs and correctly placed comma separators are accepted.
- An uppercase `O` is changed to `0` only when the rest of the amount is numeric punctuation. This handles `95O.5` without broadly deleting OCR errors, and the change is recorded in the clean record's `corrections` list.
- Zero and negative amounts are readable but suspicious. A negative value may be a legitimate credit note, while zero may indicate lost OCR digits; neither is treated as an unreadable value.
- Accepted date formats are `YYYY-MM-DD`, US-style `MM/DD/YYYY`, abbreviated-month dates such as `Jan 8, 2024`, and `YYYY/MM/DD`. Output dates use ISO format.
- `01/06/2024` is interpreted as January 6, 2024. The slash format is intentionally not guessed from locale.
- Dates before January 1, 2020 or after the day of processing are suspicious by default. This is a configurable policy rather than a claim that an older date is inherently invalid. Callers can supply a different inclusive date window through `process_records_with_policy`. Passing `min_date=date(2018, 1, 1)` turns the sample into 3 clean / 5 flagged.
- The upper bound is resolved on every call rather than at import, so a long-running process does not begin rejecting the current day's invoices after midnight.
- `%b %d, %Y` depends on `LC_TIME`, so `Jan 8, 2024` parses on an English-locale machine.
- Invoice IDs must match `INV-` followed by digits, and vendors must be nonempty strings.
- The first valid occurrence of an invoice ID is retained. A later identical record is flagged as an exact duplicate; a later record with different normalized fields is flagged as a conflicting duplicate. Both duplicate outcomes are suspicious rather than invalid.
- Flagged records preserve the raw OCR data so a reviewer can see what failed. If several checks fail, all reasons are included. The overall severity is `invalid` if any value was unreadable; otherwise it is `suspicious`, meaning a business rule requested review.
- Not handled, deliberately: `(450.00)` accounting negatives, trailing currency codes such as `1200.00 USD`, and OCR substitutions other than `O`→`0` (`l`→`1`, `S`→`5`). Each is a documented boundary rather than a silent gap.
- Callers serializing to JSON should use `str(amount)`. Converting a `Decimal` to `float` reintroduces the precision problem it was chosen to avoid.

## The sample data

| Record | Result | Why |
| --- | --- | --- |
| `INV-1001` | clean | `Decimal('1200.00')`, `2024-01-05` |
| `INV-1002` | clean | `95O.5` → `Decimal('950.50')`, correction recorded; `01/06/2024` → January 6 |
| `INV-1003` | invalid | amount is `N/A` |
| `INV-1004` | invalid | vendor is empty (amount and date parsed fine) |
| `INV-1001` (again) | suspicious | exact duplicate — every normalized field matches |
| `INV-1005` | invalid | `2024-13-40` is not a date; also a negative amount |
| `INV-1006` | invalid | amount is whitespace only |
| `INV-1007` | suspicious | `2019-01-10` is a real date outside our chosen window |

**2 clean, 6 flagged.** Not the only defensible classification — the point is that the policy is consistent and written down. `INV-1007` is the only record in the sample whose flag depends entirely on a threshold we invented; every other flag comes from the data itself.

## Edge cases considered

Almost every row in the sample has something planted in it, and several carry more than one problem.

- **`" "` is not empty.** The amount in `INV-1006` is a single space. `if not amount` catches `""` and `None` and sails straight past `" "`, because a space is truthy. The value has to be stripped before it is tested for emptiness.
- **The two commas conflict.** `"$1,200.00"` invites a blanket `.replace(",", "")`, which would turn `"Jan 8, 2024"` into `"Jan 8 2024"` and break the very date format written to parse it. Commas are therefore handled inside amount parsing only, never across the record.
- **The failures that don't look like failures.** `float("N/A")` and `float(" ")` raise, which is easy to notice. But `float("$1,200.00".replace("$", "").replace(",", ""))` quietly returns `1200.0`, and `float("-450.00")` quietly returns `-450.0`. A naive implementation reports success on both while storing money in binary floating point and accepting a negative invoice without comment. The silent cases are more dangerous than the crashes.
- **`2024-13-40` looks like an ISO date** but no such day exists. An explicit `strptime` format list rejects it for free; a permissive date library would have guessed at it.
- **`01/06/2024` is locale-ambiguous.** Read as US-style January 6 and documented as such, rather than inferred from a locale.
- **Replacing every `O` with `0`** would turn unrelated text into an amount, so the substitution runs only when every other character already belongs to a number. `ONE HUNDRED` is rejected rather than mangled into `0NE 100`.
- **`INV-1004` fails on one field only.** Its amount and date parse perfectly; only the vendor is empty. Validation is per-field, so the reason names what actually failed instead of rejecting the record wholesale.
- **`INV-1005` fails twice** — an impossible date and a negative amount. All applicable reasons are collected rather than returning the first one found.
- **`INV-1007` has nothing wrong with it.** Every field parses cleanly. It is flagged only because of a range we chose, which is why that range is an overridable policy rather than a hardcoded constant.

The implementation also never mutates the caller's input records, and duplicate comparison uses normalized values, so `$1,200.00` and `1200` under the same invoice ID are recognized as the same invoice rather than as a conflict.

## AI usage

I used Codex first, to review the task and help me understand the best way to approach it. After his take I asked for a first version of the code and for the judgment calls I'd need to decide myself.

I ran it and it looked fine — 9 tests passing and the expected 2 clean / 6 flagged on the sample. But every one of those checks only used the 8 rows from the assignment, so I moved to Claude and ran the code against inputs the sample doesn't contain. That found two real bugs:

- Duplicates were compared as raw text, so the same invoice read once as `"$1,200.00"` and once as `"1200"` came out as a conflicting duplicate — the code failing on exactly the OCR noise it's supposed to handle.
- A flagged record still claimed its invoice ID, so a broken row (`amount: "N/A"`) blocked a perfectly good row with the same ID that came after it. Zero clean records where there should have been one.

Neither was reachable from the 8 supplied rows, which is why 9 passing tests didn't catch them. I fixed both and added tests for them.

The first version also didn't record that it had changed anything. 95O.5 came out as a clean 950.50 that looked identical to a value the OCR read perfectly, and it felt wrong not to mention it — so I added a corrections field.

I also added severity to flagged records. If I had 2000 rows to review, "the scan is unreadable" and "the date is older than our cutoff" are not the same job — one needs the original document, the other just needs someone to say yes. So they shouldn't sit in the same pile.

What I decided against: treating an unrecognized invoice ID as invalid. ACME-2024-01 is perfectly readable — it just doesn't match the INV- pattern we chose, and at scale that would send a whole vendor's invoices to be re-typed when the real fix is our pattern. I also considered flagging both sides of a conflicting duplicate and kept first-wins, documented above.
