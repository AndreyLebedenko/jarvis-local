# Story: Prepare a conversation for external consultation

Status: Draft for owner review, 2026-11-16. Story and spike requested by the
owner; spike first, no production implementation started. No release version
assigned.

Spike: `spike-external-consultation-export.md`.
Related work: `story-v2.1.0-personal-proxy.md`,
`story-v2.1.1-proxy-speech-modes.md` (further development on hold).

## Origin and goal

The original goal was to let the local assistant benefit from a stronger model
without disclosing sensitive context. Detecting its own lack of knowledge proved
an unsuitable prerequisite. The owner already separated that decision (human)
from the protection protocol (personal proxy). The remaining question is whether
a separate proxy conversation provides enough benefit to the main local dialog.

Owner decision, 2026-11-16: explore a context-menu action that prepares selected
conversation content for an external consultation. The user reviews and transfers
the text manually to a model of their choice. They may stop there or bring its
answer back into the same local conversation. Jarvis then has the original
private context and the prepared text available when applying the answer.

The first version does not summarize. Summarization may be explored later as a
separate operation with separate preservation criteria. The working label is
"Prepare for external consultation"; the final localized menu label is not settled.

## User flow

1. The user talks to the normal local Jarvis without anonymizing their input.
2. The user invokes the action from a message/question or the whole dialog.
3. Jarvis prepares a text-only derivative locally and saves it in the same
   conversation context, linked to its source. It does not create a proxy session.
4. The user reads the exact prepared text, requests corrections if needed, and
   copies/sends it themselves. Jarvis does not contact an external provider.
5. Optionally, the user pastes an external answer into that conversation and
   identifies it as an external model's answer.
6. Jarvis can relate the answer to the private source context and the version of
   the prepared text that was used. Successful application is a spike hypothesis,
   not an assumed capability or a guarantee of correctness.

## Settled requirements

- The human decides whether and when to consult. No confidence detector,
  automatic escalation, or model-selected external call.
- Preparation, review, and later discussion stay in the same local context.
  A journal-only record excluded from model context would not satisfy this.
- No shortening: retain substantive facts, qualifications, disagreements,
  questions, speaker attribution, and order within the selected source scope.
  Sensitive details can be replaced or generalized, but every such change must
  be inspectable locally. Do not silently omit difficult passages.
- The prepared text is a derivative, not a rewrite of the original messages.
  Source records remain unchanged. It must not be treated as an additional
  independent source corroborating the originals.
- Only the reviewed export text is intended to leave. Original values, local
  correspondence information, and private review notes are not part of it.
- An external answer retains external provenance. Its claims are not promoted
  to user facts or trusted instructions merely because they were pasted.
- No anonymity guarantee: substitutions and detectors can miss sensitive
  content, and combinations of circumstances can identify a person. Human
  review is required; passing checks is not proof of safe disclosure.
- Further personal-proxy development is on hold, including the public-names
  task. Its shipped behavior and recorded experimental facts remain intact.

## Boundaries

In scope: a source-linked local text export, review/correction, retention in the
same context, and optional use of a manually returned external answer.

Out of scope: automatic external transport, provider/key setup, automatic
clipboard reads, automatic confidence detection, summarization, model training,
proxy removal, and changes to existing proxy sanitization or speech modes.
Media bytes are not exported. How voice transcripts and attachments participate
must be resolved before implementing their support; unsupported content must be
reported, not silently dropped. No attempt to bypass context limits by truncation
or unapproved summarization.

## Design questions for the spike and subsequent review

These are deliberately unresolved, not permission to pick an architecture while
implementing. Stop and review their consequences before production work.

1. Which representation preserves meaning best without shortening: minimally
   transformed attributed turns, structured export, or another measured shape?
2. What local correspondence information is necessary for consistent identities
   across turns and for interpreting a returned answer? Does it need durable
   storage, or can explicit context suffice? Do not assume proxy mapping storage
   rules apply: the shipped proxy deliberately does not persist its mapping.
3. How are revisions, multiple exports, and returned answers linked? What must
   survive session reload and working-context eviction? The existing history
   budget remains binding; "same context" cannot mean unlimited prompt capacity.
4. Which journal provenance and retrieval policies make the derivative available
   to this conversation without duplicating facts in general memory?
5. How does the user explicitly mark a pasted external answer and choose its
   source export? Reuse of existing external-canvas provenance requires review;
   this story does not silently reuse the separate MCP run mode.
6. What happens when selected content depends on messages outside the selection,
   contains media, or cannot fit? No silent expansion or omission.
7. Which sensitive categories can be transformed while retaining utility?
   Names, exact amounts, dates, relationships, and distinctive circumstances need
   separate assessment; replacing them all blindly is not the requirement.

## Ordered work sequence

1. **PoC spike.** Implement an isolated harness only after the experiment plan is
   frozen. Measure preservation, sensitive-content exposure, referential
   consistency, and the returned-answer application in synthetic conversations.
   Report failures and raw evidence. No runtime/UI integration.
2. **Contract review and implementation cards.** Review the spike with the owner;
   settle the questions above and write independently verifiable task cards.
   Update `PROJECT.md` with accepted architecture before implementing it.
3. **Local preparation and context retention.** Implement the agreed source,
   derivative, revision, and correspondence contracts with pure-logic tests.
4. **Context-menu action and review.** Add the agreed message/dialog selection,
   preparation, inspection, and copy workflow; retain exact reviewed versions.
5. **Optional returned-answer workflow.** Implement explicit external attribution
   and association with the applicable export in the same conversation.
6. **Docs and verification.** Document limits and source-selection behavior,
   verify end-to-end logic and prepare self-sufficient human UI checks.

Steps 3-6 are planning slices, not implementation authorization. Do not write
their task cards as if the spike's architectural questions were already settled.

## Acceptance criteria

- [ ] The spike has a reproducible result and an owner-reviewed go/no-go decision.
- [ ] Message/question and whole-dialog actions have explicit source boundaries.
- [ ] Original messages remain unchanged; the derivative is available in the
      same local context and is linked to its source and version.
- [ ] No substantive shortening or silent source truncation occurs.
- [ ] The user can inspect and correct the exact text before manual transfer;
      local private correspondence data are kept out of that text.
- [ ] A returned answer has explicit external provenance and can be associated
      with its export; measured application to private context is documented.
- [ ] Failures, unsupported inputs, and limits are visible without partial
      results masquerading as completed exports.
- [ ] Production changes have meaningful unit/edge-case and functional coverage;
      project checks pass and human UI verification is prepared.

## Stop conditions

Stop if useful context cannot be preserved without unacceptable disclosure,
returned answers are consistently misapplied, or the design requires weakening
the runtime locality or provenance contracts. Report the evidence and the
decision needed; do not repair the concept by adding summarization, automatic
transport, or confidence detection to this scope.
