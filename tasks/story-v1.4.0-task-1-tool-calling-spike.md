# Task: Tool-calling reliability spike

**Story:** `tasks/story-v1.4.0-mcp-integration.md`
**Status:** Planned. May start before v1.3.0 completes.
**Release:** v1.4.0

## Summary

Measure how reliably the configured local model calls tools through two
presentation strategies - Ollama's native `tools` field and a prompt-based
contract - on a fixed task set. The result decides the default presentation
layer. This is a human-run measurement task in the tradition of the v1.2.5
TTS spike; the speech-markup instability report
(`tasks/bug_reports/gemma4-speech-markup-contract-instability.md`) is the
precedent that makes it mandatory.

## Current Boundary

- Write `manual/manual_check_tool_calling.py`; the agent prepares exact
  commands, the human runs them against live Ollama.
- Fixed task set, each run N times per strategy for a stable rate:
  - single tool call with typed arguments (Russian and English prompts);
  - a question that must NOT trigger a tool call (false-positive rate);
  - choosing between two available tools;
  - a two-step turn: tool result comes back, model must produce a final
    answer without a spurious second call;
  - malformed-output detection: how often arguments fail schema validation.
- Metrics per strategy: correct-call rate, false-positive rate, argument
  schema validity rate, and any template/format errors from Ollama.
- Native strategy: `tools` in `/api/chat` via the existing request path in
  `src/jarvis/dialog/backend.py`. If the model template does not support
  tools, record that as a fact - it decides the strategy by itself.
- Prompt strategy: tool declarations in the system prompt, structured
  (JSON) reply contract, strict parser with validation - measured with the
  same task set.
- No MCP dependency, no engine integration: the spike talks to Ollama
  directly with hardcoded fake tool schemas.
- After human runs: record verified facts in `PROJECT.md` (rates, chosen
  default strategy, model/template caveats) before any task 3+ work.

## Acceptance Criteria

- [ ] Spike script covers the full task set for both strategies with exact
      human-run commands.
- [ ] Pure tests cover the spike's parsing/validation logic.
- [ ] `python -m pytest` passes.
- [ ] Human measurements recorded in `PROJECT.md`, including the chosen
      default presentation strategy.

## Stop Conditions

- Stop (story-level re-plan) if both strategies are unreliable on the
  local model.
- Stop if Ollama's tool-calling API behaves differently from its
  documentation in a way that affects architecture - record the fact
  first.
