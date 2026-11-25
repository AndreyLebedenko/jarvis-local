# Task: CI failures on 2026-11-24

Status: Completed.

## Boundary

Repair the Windows CI failures in annotation overlay initialization and in the
personal proxy status test harness. Track the MCP SDK shutdown defect in
`2026-11-24-mcp-sdk-standalone-sse-close.md`.

## Acceptance criteria

- Concurrent annotation writers see a complete schema and enforce the session
  limit in the same transaction as insertion.
- A failed schema creation rolls back, and a metadata-only database left by
  earlier code can accept annotations again.
- The Node harness decodes Russian output as UTF-8 on Windows.
- The automated suite and both Ruff checks pass locally.

## Verification

Windows `python -m pytest -q` reported 6363 passed and 1 skipped. Both Ruff
checks and `git diff --check` passed. The MCP SDK issue remains open in its
own report.
