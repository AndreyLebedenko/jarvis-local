# Task: Deployment Wizard 1 - inventory and plan validation

Status: Completed.
Story: `story-deployment-wizard.md`, task 1.

## Boundary

Build a read-only plan from an application home, a new destination, and a
deployment mode. A checkout and a deployed home share the same application
layout. Git metadata, Python environments, caches, and user data are outside
the application payload. Copying, installer execution, runtime locking, and
configuration edits belong to later tasks.

## Path inventory

| Setting or resource | Copy mode handling |
| --- | --- |
| `config.toml`, `config.ui.toml` | Read effective settings with the runtime loader. Plan to transfer each existing layer. A missing base layer means runtime defaults. |
| `[journal].root`, `[memory].root` | Resolve from the source home and follow a linked root to find its data. Snapshot by value into `journal/` and `memory/` in the destination. Reject overlapping roots and roots that contain the source home. |
| `[memory].self_file`, `[memory].memory_file` | Preserve the configured paths relative to the new memory root. |
| `[logging].directory`, `[mcp_mode].token_file` | Use fresh destination paths `logs/` and `mcp_mode.token`. Reject a configuration where copying a snapshot root would also copy the original logs or token. |
| Prompt references under `.jarvis`, `[personal_proxy].topics_file`, `[personal_proxy].public_names_file` | Copy supported referenced input files by value. The snapshot task handles relocation where required. |
| `[sound_cues]`, Piper `model`, `config_path`, `espeak_data_dir`, `download_dir` | Inventory local assets and independently place writable paths on the destination side. Use the existing installer to report missing models. The snapshot task handles the asset copies and rebasing. |
| `[mcp].servers` | With an enabled provider, reject Copy and identify the provider key. Command, arguments, and environment can address stores beyond Jarvis's filesystem contract. Preserve disabled configuration for user review. |
| Ollama endpoint and models, external service and camera endpoints | Machine-managed or independently configured services. The deployment plan does not contact them. |

Clean mode selects application files only. It does not read the source
installation's settings or state.

## Follow-up constraints

- Task 3 must check effective paths for prompt files, Personal Proxy inputs,
  sound cues and Piper assets before installing the copy. Test absolute source
  references such as `topics_file` and Piper `download_dir`. Copy and rebase
  supported inputs, and reject any unresolved writable path into the source.
- Tasks 2 and 4 must account for the planner's `jarvis.core.config` import.
  Use the source `.venv` interpreter when available. A checkout without a venv
  needs Python 3.11 with the source `src` directory on `PYTHONPATH` for the
  planner process. Keep that setting scoped to the process.

## Acceptance criteria

- Plan the application payload from the supported on-disk layout without Git
  or an installed destination environment, and omit caches and user state.
- Reject an existing, overlapping or aliased destination and report the path.
- Use effective config layers in Copy mode and report the key for protected
  path conflicts or an enabled MCP provider. Resolve Windows junctions in the
  source or destination path before checking overlap.
- Use filesystem fixtures for both modes and demonstrate that validation
  creates no files at the destination.
