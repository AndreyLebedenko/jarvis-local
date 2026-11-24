# Task: Deployment Wizard 4 - Windows UI

Status: Completed. Owner reported a successful normal-path Windows run.
Startup failure and interrupted preparation have separate automated checks.
Story: `story-deployment-wizard.md`, task 4.
Predecessor: `task-deployment-wizard-3-copy-isolation.md`.

## Boundary

Launch a WPF window with `DeploymentWizard.cmd`. Reuse the CLI planner and
deployment runner in a background process. The preview reads source metadata
and checks destination paths without preparing a target. The UI asks for
consent before using winget when Python 3.11 is missing.

- Choose the mode and destination, review the canonical paths and snapshot
  scope, run deployment with live output, then show the target actions.
- Show captured failure details and allow a validated installer retry from
  `ready`. A shortcut starts the destination `Jarvis.cmd` directly, with that
  home as its working directory. Report startup failures before the main WPF
  window and show recovery guidance for an interrupted `preparing` target.
- Keep the window responsive while the worker runs. Release verification and
  README updates remain task 5.

## Acceptance criteria

- The wizard opens without destination Python packages. Both modes and resume
  use the CLI backend, and invalid inputs cannot start installation.
- A fake worker verifies the UI's review, failure, retry and completion states.
  A human-run handoff covers the real window, live progress and target launch.

## Windows handoff

The wizard and CLI remain undocumented in `README.md` and `README.ru.md` until
story task 5. Follow the dependency and local Ollama steps in
`task-deployment-wizard-2-clean-install.md`. The installer reads the effective
`[backend].endpoint` from the destination. Its default is
`http://localhost:11434` in `config.example.toml`, and `installer.py` uses
`/api/tags` on that endpoint to check models.

1. In the source home, run `.\DeploymentWizard.cmd`. The choice page should
   show that home. Select **Clean installation** and enter a new sibling
   directory under an existing parent in **Destination folder**. An existing
   folder or a path inside the source should fail the review. If the machine
   lacks Python 3.11, select **Allow installing Python 3.11 through winget if
   needed** before reviewing, or install Python manually. `bootstrap.ps1`
   defines the Python 3.11 check and winget command.
2. Select **Review** and confirm the displayed journal and memory paths are
   inside the destination. Select **Deploy**. Resize the window during the
   operation and confirm output continues to appear. If the installer reports
   an error and the UI offers **Resume installation**, address the error and
   use that button to continue from the prepared target.
3. On **Jarvis is ready**, select **Open folder** and confirm Explorer opens
   the target. Select **Create shortcut...** and choose a file name. In the
   shortcut's properties, confirm **Target** is the destination `Jarvis.cmd`
   and **Start in** is the same destination. Close any running Jarvis, then
   select **Launch Jarvis**. `Jarvis.cmd` launches `--status-console` in its
   own directory. Confirm the **Journal** tab has no sessions from the source.
4. Repeat from the source with **Copy current Jarvis** and a different new
   target. Use the source eligibility, Journal and memory verification steps
   from `task-deployment-wizard-3-copy-isolation.md`. The review should show the
   original journal and memory roots and the new local paths. When the source
   runtime is active, the review should ask you to close it.
