# Consultation export leaves a private namesake named as a public figure

Status: PoC finding, 2026-11-17. Detected at
`e3d38562dda7887599d1750cc9c64f01dfd4d322`, with uncommitted PoC files on
`codex/spike-consultation-export`. Result: `consultation-export-v1-results.md`.

## Symptoms

Synthetic fixture `public_private_namesakes` explicitly distinguishes the public
physicist from a private colleague sharing his name and asks not to disclose the
colleague's name. All three seeds copy the private occurrence unchanged. A
`<PERSON_1>` mapping is generated but never used in exported turns; risk notes
are empty. The legitimate public occurrence makes a blanket literal check
insufficient to identify this failure.

Raw evidence: `manual_check_consultation_export_out/calls/prepare/` files
`public_private_namesakes-s19210.json`, `-s19211.json`, and `-s19212.json`.
Manifest SHA256 starts `84aea9814f181e08`.

## Suspected cause and temporary decision

The candidate's permission to retain public names appears to dominate the
explicitly private occurrence, while its mapping is generated independently of
actual replacement. The outputs establish failure, not its internal cause.

Record all three as critical privacy failures and stop under the frozen rubric.
Do not introduce a public-name allowlist or tune this fixture repeatedly; both
would obscure the contextual issue and exceed this measured arm.

## Future boundary

A later design must distinguish occurrences/referents, or explicitly present the
ambiguity for review. Replacing every occurrence of a shared name sacrifices
public context and is a policy choice, not an automatic fix. Persistent mapping
representation remains unsettled by this experiment.
