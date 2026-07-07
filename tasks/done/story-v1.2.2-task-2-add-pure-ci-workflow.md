# Task: Add pure CI workflow

**Story:** `tasks/story-v1.2.2-project-verification-contract.md`
**Status:** Completed.
**Release:** v1.2.2
**Depends on:** `tasks/done/story-v1.2.2-task-1-update-verification-policy.md`

## Summary

Add GitHub Actions for the pure automated test suite.

## Current Boundary

- Add CI workflow only after the policy task lands.
- CI installs dependencies and runs `python -m pytest`.
- Do not add live services, secrets, model downloads, or hardware checks.

## Acceptance Criteria

- [x] A GitHub Actions workflow exists for push and pull request checks.
- [x] Workflow sets up Python 3.11.
- [x] Workflow installs `requirements.txt`.
- [x] Workflow runs `python -m pytest`.
- [x] Workflow does not start Ollama, download models, access secrets, or run
      manual check scripts.
- [x] Any CI-specific cache is dependency-cache only, not model-cache.

## Verification

- Run `python -m pytest` locally.
- Inspect workflow YAML for excluded live/hardware/model steps.

## Stop Conditions

- Stop if the pure suite attempts to use hardware or live services in CI.
- Stop if CI needs credentials or model downloads to pass.
