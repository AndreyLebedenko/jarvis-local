# Task: Deployment Wizard 5 - documentation and release verification

Status: In progress, 2026-11-24. Documentation and release handoff prepared.
Story: `story-deployment-wizard.md`, task 5.
Predecessor: `task-deployment-wizard-4-windows-ui.md`.
Windows procedure: `deployment-wizard-release-handoff.md`.

## Boundary

Document the GUI, the two CLI modes, their storage paths, and installer resume
in both READMEs. Provide one Windows procedure for Clean and Copy. Record
evidence against the deployment story before closing it. Run automated checks
locally. The owner runs the real Windows applications and live Ollama steps.

## Acceptance criteria

- Both READMEs cover `DeploymentWizard.cmd`, `deploy.cmd`, a new destination,
  storage isolation, the Copy prerequisite and `-Resume` recovery.
- The handoff gives runnable steps for an empty Clean journal, preserved Copy
  history, and unchanged source journal and memory after writes in Copy.
- The verification record identifies what ran, the platform and the results.
  Review the handoff results before closing the story.

## Verification record

On Windows 11 with Python 3.11, `python -m pytest -q` reported 6359 passed
and 3 skipped. Ruff lint and format checks passed. The handoff checker passed.
All five PowerShell blocks parsed, and the inventory and marker helpers passed
checks on synthetic source and copy files, including detection of a changed
source hash.

The owner reported a successful normal-path wizard run while reviewing task 4.
That report did not include the release hash comparison. The results template
in `deployment-wizard-release-handoff.md` records the remaining Windows evidence.
