# Single-pass TTS spike: decision report

Blind review on seed 19200; automated measures on all seeds.

Decision: **CLOSE** - speed: median gain below 1.0 s at both levels.

## Level off (production block, B vs A-prod)

| criterion | measured | threshold | result |
|---|---|---|---|
| 1. tag failures among B generations | 0 of 32 | <= 1 | pass |
| 2. canvas pairs B lost | 3 of 16 | <= 4 | pass |
| 3. voice pairs B lost vs A-prod | 10 of 16 | <= 6 | FAIL |
| 4. voices flagged for invented claims | B 0, A-prod 0 | B <= A-prod | pass |
| 5. runaways | B 0, A-prod 0 | B <= A-prod | pass |
| 6. median first-sentence gain (A-prod minus B), s | 0.605 over 32 matched, 0 dropped | >= 1.0 | FAIL |

Go at this level: does not hold.

## Level medium (production block, B vs A-prod)

| criterion | measured | threshold | result |
|---|---|---|---|
| 1. tag failures among B generations | 1 of 32 | <= 1 | pass |
| 2. canvas pairs B lost | 6 of 16 | <= 4 | FAIL |
| 3. voice pairs B lost vs A-prod | 7 of 16 | <= 6 | FAIL |
| 4. voices flagged for invented claims | B 0, A-prod 0 | B <= A-prod | pass |
| 5. runaways | B 1, A-prod 0 | B <= A-prod | FAIL |
| 6. median first-sentence gain (A-prod minus B), s | -8.989 over 32 matched, 0 dropped | >= 1.0 | FAIL |

Go at this level: does not hold.

## Equalized block (explains, does not decide)

The equalized sitting was not reviewed.

## Reviewer guess of B (reported, does not decide)

Possible bias when correct/shown >= 13/16; an empty guess is an abstention and counts as not correct.

| level | pairs | correct | guessed | shown | possible bias |
|---|---|---|---|---|---|
| off | canvas | 2 | 5 | 16 | no |
| medium | canvas | 1 | 3 | 16 | no |
| off | voice | 3 | 14 | 16 | no |
| medium | voice | 5 | 12 | 15 | no |

## Voice hygiene and cost per arm (reported, does not decide)

| level | arm | generations | median wall s | eval_count sum | markdown_markers | table_pipe_lines | code_fences | raw_urls |
|---|---|---|---|---|---|---|---|---|
| off | a_prod | 32 | 7.272 | 15934 | 0 | 2 | 0 | 0 |
| off | b | 32 | 5.042 | 11500 | 0 | 0 | 0 | 0 |
| medium | a_prod | 32 | 28.878 | 77079 | 0 | 0 | 0 | 0 |
| medium | b | 32 | 41.662 | 105271 | 0 | 0 | 0 | 0 |
| medium | a_eq | 32 | n/a | 107933 | 0 | 2 | 0 | 0 |

A-eq median wall time is n/a: the harness runs A-eq's pass 2 after A-prod's pass 2, so A-eq timings include A-prod's pass 2.
