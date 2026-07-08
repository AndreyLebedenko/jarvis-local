# Task: Graphify pipeline wrapper

**Status:** Completed.

## Summary

Add a project-local graphify entry point so agents can run common graph
operations without remembering CLI details.

## Boundary

- Add wrapper and agent instructions only.
- Do not commit generated graph output.
- Do not add graphify to Jarvis runtime dependencies.
- Do not run a full graph extraction as part of the pure automated suite.

## Acceptance Criteria

- [x] Generated `graphify-out/` data is ignored by git.
- [x] Common operations have short commands: init, update, query, path,
      explain, cluster, hook install/status/uninstall.
- [x] Initial local graph can be built through the fast no-LLM code path.
- [x] Agent instructions explain when to use the graph and how to update it.
- [x] Pure automated tests still pass.

## Commands

```powershell
tools/graphify.ps1 init
tools/graphify.ps1 update
tools/graphify.ps1 query "How does shutdown flow through the app?"
tools/graphify.ps1 hook-install
tools/graphify.ps1 hook-status
```

## Verification

- `tools/graphify.ps1 help`
- `tools/graphify.ps1 hook-status`
- `graphify update . --no-cluster`
- `python -m pytest`
