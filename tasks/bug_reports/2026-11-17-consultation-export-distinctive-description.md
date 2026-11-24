# Consultation export retains a distinctive profession without a reliable warning

Status: PoC finding, 2026-11-17. No runtime implementation exists for this feature.
Detected at `e3d38562dda7887599d1750cc9c64f01dfd4d322`, with uncommitted PoC files
on `codex/spike-consultation-export`. Parent result:
`consultation-export-v1-results.md`; manifest SHA256 starts `84aea9814f181e08`.

## Symptoms

In synthetic fixture `identifiers_and_combination`, all three seeds retain
`единственный реставратор фиолетовых башенных часов` in the copyable export after
removing the explicit name, e-mail, phone, and village. The profession phrase is
pre-labeled sensitive. Seed 19211 flags residual identification risk; seeds
19210 and 19212 imply successful anonymization without that warning. Seed 19210
specifically claims the restoration task was anonymized, contradicting its text.

Raw evidence: `manual_check_consultation_export_out/calls/prepare/` files
`identifiers_and_combination-s19210.json`, `-s19211.json`, and `-s19212.json`.

## Suspected cause and temporary decision

The local candidate prioritizes literal entities and copies the surrounding
description. Its risk explanation is another generated claim and is not checked
against the actual export. This is a hypothesis supported by the outputs, not a
separate model-internals experiment.

Keep outputs/prompts frozen and stop before application calls under the rubric.
Do not fix this with further unreviewed prompt retries or claim that passing an
identifier detector proves anonymity. The reviewed result distinguishes the
flagged residual from the two critical unflagged failures.

## Future boundary

Review identifying descriptions and combinations separately from string-based
identifier checks. Any later warning/transform policy must preserve consultation
utility and be measured as a new arm. No runtime detector redesign is part of
this spike result.
