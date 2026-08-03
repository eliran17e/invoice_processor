# Write-up

*(Full detail — severity mapping, per-record results, reasoning behind each rule
— is in `README.md`.)*

## Assumptions

- **Amounts.** `Decimal`, never `float`. Positive and non-zero is normal; zero
  and negative are readable, so they're flagged for review rather than rejected
  — a negative may be a real credit note.
- **Dates.** 2020-01-01 to today is normal, but **nothing in the data says that**
  — it's a policy I chose, so it's a parameter rather than a constant.
- **Ambiguous formats.** `01/06/2024` is January 6, US-style, documented rather
  than guessed. `O`→`0` only inside an otherwise-numeric amount, so `95O.5` is
  repaired and `ONE HUNDRED` is rejected — and the repair is recorded in
  `corrections`, since a silent edit looks identical to a clean read.

## Edge cases

The amount in `INV-1006` is `" "`, not `""` — a space is truthy, so the obvious
`if not amount` check misses it. `"$1,200.00"` invites stripping commas
everywhere, which would break `"Jan 8, 2024"`. `2024-13-40` looks like an ISO
date but no such day exists, so I used an explicit format list rather than a
permissive parser.

What surprised me most were the failures that don't fail: `float()` happily
returns `1200.0` and `-450.0`, so a naive version reports success while putting
money in binary floating point and accepting a negative invoice without comment.
And `INV-1007` has nothing wrong with it at all — it's flagged only by a cutoff I
invented, which is why that cutoff is overridable.

## How I used AI

I used Codex to understand the task and write a first version, then Claude to review it — but most of what I actually did with both was check rather than generate: where a rule came from, whether an example was real, and whether my own reading of the output was right.

Twice I asked where something came from and the answer was that the AI had invented it — the 2020 date cutoff, and an example invoice ID it used to justify a decision. The severity field was my idea, and my question about what happens with 2000 rows to review changed the recommendation I'd been given on malformed IDs.

I also went through the flagged records one at a time and described each in my own words to check I had them right, and I switched to Hebrew partway through because I wanted to understand the decisions well enough to defend them, not just ship them.

The first version looked fine — 9 tests passing and the expected 2 clean / 6 flagged. But all of that used only the 8 supplied rows, so I ran it against inputs the sample doesn't contain, and found two real bugs: duplicates were compared as raw text, so the same invoice read once as `"$1,200.00"` and once as `"1200"` came out as a *conflicting* duplicate; and a flagged record still claimed its invoice ID, so a broken row (`amount: "N/A"`) blocked a good row with the same ID after it. Neither was reachable from the 8 rows, which is why 9 passing tests didn't catch them. I fixed both and added tests.
