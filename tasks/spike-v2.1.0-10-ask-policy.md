# Spike v2.1.0-10: when to ask the owner to confirm, and what to point at

Status: Result recorded 2026-10-19. An offline analysis of recorded data; nothing
was run live and no rule was frozen before it (it follows spike 9's data).

Parent story: `tasks/story-v2.1.0-personal-proxy.md`. Follows spikes 8 and 9. Owner's
design (2026-10-19): the chat always records what the engine heard (whole, without
placeholders) and what it decided; if there is a reason to doubt, a separate
Text+Voice exchange asks for confirmation (the text shows the whole transcript,
the voice names what to check); otherwise the request is sent without a question;
a separate block always records what actually went out. A flag therefore means
"ask", not "refuse". Budget (owner): about 1 request in 4 asked about, for
sensitive and complex cases. Journal: the whole heard text; logs: only what goes
out, with placeholders.

## Question

Which doubt source decides whether to ask, within the 25% budget, and does the
voice part have the wrong fragment to name?

## Data

The 60 recordings of both corpora that carry labeled spans (the first corpus
without its topic and neutral utterances, the second corpus whole). Real errors
by the label `addresses_assembled` of spike 9 (7 of 60; the neutral
`n_short_translate`, a Russian request rewritten in English, has no spans and is
outside this set). Doubt sources: the judge's list of uncertain fragments for the
base sample (J3), the items the six samples disagree on (S2), and Whisper's words
under probability 0.5. The strings that identify each wrong fragment were chosen by
the agent after reading the outputs (`WRONG_FRAGMENT_KEYS` in
`manual/personal_proxy/ask_policy.py`). Command:
`python -m manual.manual_check_ask_policy --v2-out manual_check_confidence_v2_out`.

## Result

| rule | asked | within 25% | errors covered |
|---|---|---|---|
| J3 >= 1 (the judge lists a doubt) | 13/60 = 0.22 | yes | 7/7 |
| S2 >= 0.6 | 9/60 = 0.15 | yes | 4/7 |
| S1 >= 3 | 5/60 = 0.08 | yes | 5/7 |
| S3a >= 0.5 | 8/60 = 0.13 | yes | 1/7 |
| H: S2 >= 0.6 or J3 >= 1 | 16/60 = 0.27 | no | 7/7 |
| S1 >= 3 or J3 >= 1 | 13/60 = 0.22 | yes | 7/7 |
| S1, S2, J3 together | 16/60 = 0.27 | no | 7/7 |

The judge's list alone fits the budget and covers every error in the data; adding
S1 changes nothing, adding S2 pushes the rate over the budget. Naming the wrong
fragment (a listed doubt quotes it): the judge's list does in 5 of 7 errors,
the disagreement of the samples in 4 of 7, Whisper's weak words in 0 of 7, the
union of the three in 6 of 7 (the exception is `id_letter_long`, the
organization "Альфтеррейт"). The judge's list is short (mean 1.2 items, at most
2, on 13 of 60 recordings); the union is longer (mean 2.2, at most 10).

Cost of the options: J3 needs one Gemma sample and one judge call (the base
sample's); S2 needs six samples and six judge calls.

## Reading and limits

The judge's list of doubts is the simplest sufficient trigger on this data, and
it also supplies the text for the voice part. The evidence is thin: 7 errors,
of which 3 are one phrase in three voices; the J3 threshold was chosen on the
first corpus; the wrong-fragment keys and the label rule were written after the
data was seen; the asked share (22%) comes from a corpus dense with identifiers
and will be lower on ordinary requests. Whisper's weak words add nothing as a
trigger or as a pointer on this data.
