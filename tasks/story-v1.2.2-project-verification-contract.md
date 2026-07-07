# Story v1.2.2: Project verification contract

**Status:** Backlog.
**Roadmap:** `tasks/roadmap-v1.2-v1.4.md`
**Release:** v1.2.2

## User-facing goal

Make the project verification contract explicit: Jarvis runtime remains local
and offline, while cloud CI is allowed only for pure build/test checks that do
not touch hardware, live Ollama, secrets, model downloads, or external runtime
services.

## Boundaries

- This story changes project policy and verification plumbing only.
- Runtime behavior is unchanged.
- CI may install dependencies from the network.
- CI must not run manual/hardware checks or any test requiring live hardware,
  live Ollama, GPU/VRAM, WebView visual review, microphone, speakers, global
  hotkeys, screen capture, secrets, or model downloads.
- Normal local test invocation remains `python -m pytest`.

## Acceptance Criteria

- [ ] `AGENTS.md` no longer forbids CI categorically and instead separates
      runtime locality from pure CI verification.
- [ ] `PROJECT.md` records the same decision as an architectural project fact.
- [ ] GitHub Actions runs the pure automated suite with `python -m pytest`.
- [ ] CI documentation states which checks are deliberately excluded and why.
- [ ] Hardware/manual check scripts remain human handoffs, not CI jobs.
- [ ] No runtime network dependency is introduced.

## Task Card Sequence

1. Update project verification policy.
   - Update `AGENTS.md` and `PROJECT.md`.
   - Preserve the runtime offline guarantee.

2. Add pure CI workflow.
   - Add GitHub Actions for dependency install and `python -m pytest`.
   - Do not add secrets, Ollama services, model download steps, or hardware
     checks.

3. Document excluded checks.
   - Make the CI/manual boundary visible in project documentation.
   - Ensure future task cards know which checks remain human-run.

## Stop Conditions

- Stop if current tests require hardware or live services despite being treated
  as pure tests.
- Stop if the policy update conflicts with an existing project guarantee that
  has no clear replacement wording.
- Stop if CI needs secrets, model downloads, live Ollama, or hardware access to
  pass.
