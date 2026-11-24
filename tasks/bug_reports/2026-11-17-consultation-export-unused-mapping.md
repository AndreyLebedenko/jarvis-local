# Generated correspondence can describe replacements absent from the export

Status: PoC finding, 2026-11-17. Detected at
`e3d38562dda7887599d1750cc9c64f01dfd4d322`, with uncommitted PoC files on
`codex/spike-consultation-export`. Result: `consultation-export-v1-results.md`.

## Symptoms

All three `single_message_missing_antecedent` outputs map `Он` to `<PERSON_1>`
while leaving the original pronoun in the copyable turn. Their private notes
correctly recognize missing identity/context; no unselected antecedent is
imported. All three `public_private_namesakes` outputs also have an unused
`<PERSON_1>` mapping while the original names remain in the export.

Raw calls are under `manual_check_consultation_export_out/calls/prepare/`, named
after these fixtures and seeds 19210/19211/19212. The manifest SHA256 starts
`84aea9814f181e08`; semantic-review records include exact file hashes.

## Suspected cause and temporary decision

Schema validation ensures field types but not agreement between the generated
correspondence and generated text. A mapping can therefore look valid without
documenting a real transformation. The pronoun case is not counted as a private
name disclosure; its correspondence is unresolved. The namesake's actual privacy
failure is reported separately.

Keep the measured candidate unchanged, report unresolved correspondence and do
not treat a mapping as proof of successful replacement. Application remains
unmeasured because the preparation privacy gate already failed. No persistence
or automatic-restoration implementation is selected to compensate for it.

## Future boundary

A new arm may validate mapping usage and occurrence-level correspondence as
pure logic before considering storage or answer interpretation. Such validation
does not itself solve referent ambiguity or identify whether a public/private
occurrence was transformed correctly.
