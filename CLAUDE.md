# Agent Instructions

0. Stop and explain when:
   0.1. There is a question to which there is no answer in the spec,
        documentation, or this file.
   0.2. There is a conflict between requirements — e.g. the spec contradicts
        existing code or two other files.
   0.3. A change turns out to affect more than expected — e.g. a small fix
        requires reworking something large.
   0.4. Two approaches have non-obvious trade-offs and the choice has
        architectural consequences.
   0.5. Tests are failing for a reason outside the scope of the task.
   0.6. A circular dependency is detected.
   0.7. You are looping — if you are attempting the same fix or approach for
        the second time, stop. Specific symptoms:
        - The same error reappears after a fix
        - You are applying a third (or more) workaround to the same place
        - A test was written, broke, rewritten, and broke again for the same
          reason
   0.8. You cannot write a test for code you just wrote — this is a design
        problem, not a test problem.
   0.9. Build or test tooling produces an unexpected error (including
        access/permission errors, missing dependencies, environment issues).
        Do not attempt to work around infrastructure problems.
        Rule: an error in the code is your responsibility;
              an error in the environment is not.

## Project context

1. Read `PROJECT.md` before any work. It is the single source of truth for
   architectural decisions and verified experimental facts. Facts marked
   "do not re-litigate" are settled; do not re-test or reverse them without
   the human's explicit request.
2. When an architectural decision changes, update `PROJECT.md` in the same
   commit as the change.

## Core engineering principles

1. Always follow best practices.
2. Always respect SRP.
3. Always write clean code.
4. Code is clean if it is easy to test and easy to expand without violating
   the SRP or Best Practices.
5. Work in TDD style where practical.
6. Each test must be self-explanatory.
7. Prefer self-explanatory code over comments.
8. Do not add code documentation to compensate for unclear design.
9. Use ASCII punctuation and status markers in documentation, code comments,
   logs, and UI text unless a non-ASCII character is required by existing
   canonical text. Avoid symbols that render poorly in some terminals, such
   as long dashes and check marks.
   Exception: runtime user-facing strings — the Russian system prompt, TTS
   output, and dialog text — are data, not documentation. Normal Russian
   typography applies there; do not "fix" it.
10. Use UTF-8 for project files unless a file or external format explicitly
    requires another encoding.

## Testing protocol

1. Hardware-dependent tests are run by the human, not the agent. This covers
   anything touching the microphone, speakers, hotkeys, screen capture, GPU
   VRAM, or the live Ollama endpoint. The agent writes such tests or check
   scripts, hands over the exact commands, and waits for the human to report
   output. Do not attempt to run them yourself and do not treat their
   absence from your own runs as a failure or as a loop symptom (0.7).
2. Automated tests cover pure logic only: event bus behavior, sentence
   buffering, request payload construction, VAD chunking on prerecorded wav
   fixtures, config parsing.
3. Media payload rule (verified experimentally, see PROJECT.md): audio and
   images both go to Ollama through the `images` field of `/api/chat`.
   A test asserting a dedicated `audio` field is a wrong test.

## Tooling notes

1. This is a Windows 11 setup. Python 3.11, asyncio.
2. Runtime locality and CI verification are separate guarantees:
   - The Jarvis runtime must not require network access beyond the
     configured local Ollama endpoint. This is unconditional and does not
     change based on how the code was tested.
   - Cloud CI is allowed, but only for the pure automated suite: installing
     `requirements.txt` and running `python -m pytest`. CI may install
     dependencies from the network.
   - CI must not run, and must not be extended to run, anything requiring
     live Ollama, model downloads, secrets, or hardware (GPU/VRAM, WebView
     visual review, microphone, speakers, global hotkeys, screen capture).
     Those stay human-run manual handoffs per the Testing protocol above.
3. Install Python packages with `pip`; keep `requirements.txt` current in
   the same commit that introduces a dependency.
4. Run automated tests as `python -m pytest`, not bare `pytest`, both
   locally and in CI.
5. When reading project text files with PowerShell, pass `-Encoding UTF8`
   explicitly, e.g. `Get-Content -Raw -Encoding UTF8 PROJECT.md`.
6. Graphify is an agent/dev tool, not a Jarvis runtime dependency.
   Generated graph data lives under `graphify-out/` and is not committed.
   Use the project wrapper for standard operations:
   - `tools/graphify.ps1 init` for the first graph build;
   - `tools/graphify.ps1 update` after code changes when a graph exists;
   - `tools/graphify.ps1 refresh` after meaningful changes to `PROJECT.md`,
     agent instructions, README/spec files, task cards, or bug reports;
   - `tools/graphify.ps1 label` to refresh community labels only;
   - `tools/graphify.ps1 query "..."` for codebase questions;
   - `tools/graphify.ps1 hook-install` to install local git hooks.
   The `refresh` command runs full code+docs extraction and community labeling
   through a generative LLM backend, and is intentionally not part of the fast
   hook path. For local Ollama use a JSON-capable chat/instruct model such as
   `gemma4:12b-it-qat`; embedding-only models are not suitable for graphify's
   semantic extraction step. On Windows, `tools/graphify-refresh.cmd` is the
   same operation as `tools/graphify.ps1 refresh`.
   If `graphify-out/graph.json` exists and the task is a codebase question,
   query the graph before manually reading large parts of the repository.
   Do not run graph extraction in CI or treat missing graph output as a test
   failure.

## Git protocol

1. Commit before any destructive or wide-ranging change (file deletion,
   mass rename, rewriting a module).
2. Never delete or rewrite files outside the active task scope without
   explicit confirmation from the human.
3. Create a new git branch with a task-appropriate name unless the human
   explicitly asks to use the current branch.

## Task documentation workflow

1. Keep implementation planning in `tasks/`.
2. Use a story card for a larger feature or multi-step change. The story card
   should describe the user-facing goal, boundaries, acceptance criteria, and
   the ordered task-card sequence.
3. Use task cards for implementation slices that can be completed and verified
   independently. A task card should state status, summary, current boundary,
   and acceptance criteria.
4. Before starting a task card, read the relevant story card, task card,
   project docs, and source code. If the requirements are unclear or conflict
   with existing code, stop and ask before implementing.
5. While implementing, keep the code change scoped to the active task card.
   Do not silently pull later story-card steps into the current task.
6. When a task card is complete and verified, change its status to
   `Completed.` and move it to `tasks/done/`. Leave the story card in
   `tasks/` until the full story is complete.

## Standard task-card workflow

After reading the relevant story card, task card, docs, and source code:

1. Ask all blocking questions before implementation. If there are no
   questions, or the questions have been answered, proceed.
2. Follow the Git protocol above for branching.
3. Implement the required code and/or data changes within the active
   task-card boundary.
4. Run the required project checks and reach a green state, or stop and
   report if any stop condition from section 0 applies. For hardware-
   dependent verification, "green" means: automated logic tests pass AND
   the manual test handoff is prepared for the human.
5. Unless the human explicitly asked for a different handoff, stop after the
   implementation and verification summary, then wait for human review before
   closing the task card, committing, merging, or starting the next task.

## How to report an issue

1. If an implementation or playtest reveals a behavior that should not be
   fixed in the current change, write an edge case report before moving on.
2. Store reports as Markdown files under `tasks/bug_reports/`.
3. Include:
   - the current commit id where the issue was detected;
   - symptoms visible to the user or tester;
   - the suspected current cause;
   - the temporary decision, including why that decision was chosen over
     nearby alternatives;
   - future considerations and boundaries for later work.
4. Keep the report focused on the issue. Do not mix unrelated bugs, feature
   wishes, or broad roadmap notes into the same report.

---

## Communication protocol

- Russian for conceptual and architectural discussion; English for code,
  identifiers, commit messages, and technical documentation.
- Be concise. No preamble, no postamble, no restating the task back.
- Prose by default; minimal markdown.
- Push back directly when you disagree or see a problem. Do not validate
  decisions you consider mistaken. A stated position with reasoning is
  expected; hedging without a position is not.
- Cross-domain analogies are welcome when they carry real explanatory weight.
