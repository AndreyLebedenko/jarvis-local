# Plan: v2.0.0 release preparation

**Status:** Completed.
**Branch:** `release/v2.0.0-prep` from `main` (`8c903d7`).
**Owner decisions (2026-10-03):** screenshots from the demo harness
(`src/jarvis/ui/status_console_ui/demo.html`), release notes as a repository
file plus text for a GitHub Release, version and tag `v2.0.0`.

## Roles

`claude-code` scopes, reviews, writes the release notes, and makes the
screenshots; `glm` updates the READMEs; read-only subagents review. Nobody
commits before the owner's review. Push, tag, and the GitHub Release are the
owner's (outward-facing; `gh` is not installed here).

## Work items

1. **READMEs (`glm`).** `README.md` and `README.ru.md` describe the current
   product, verified against the code, not against older README text:
   - the intro and "Status" sections speak of v2.0.0 (today "Status" says
     "usable v1.6.1"), including `--mcp-mode` as the headline;
   - "Features" lists the voice guide mode and anything else shipped since
     the README was last aligned that is missing (check `PROJECT.md`
     "Current roadmap" and the done story cards; list, do not explain);
   - "Status Console UI" mentions the `MCP MODE` / `РЕЖИМ MCP` header badge
     and the voice-guide block;
   - the "Voice guide mode" section embeds two new screenshots (names below);
   - every other section: only fix what is now false. No rewrites, no new
     sections, no marketing tone. `README.ru.md` keeps its own style.
2. **Screenshots (`claude-code`).** From the demo harness, both languages,
   saved as `docs/screenshots/{en,ru}/voice-guide-status.jpg` (Status tab in
   MCP mode, guide speaking, queue shown) and
   `docs/screenshots/{en,ru}/voice-guide-journal.jpg` (Journal with external
   answer rows). Existing screenshots stay.
3. **Release notes (`claude-code`).** `docs/release-notes/v2.0.0.md`
   (English), usable as is for the GitHub Release body.

## Boundaries

- No production code changes. A doc statement that turns out false against
  the code is fixed in the doc; a code bug found on the way is reported, not
  fixed here.
- CLAUDE.md section 9: ASCII punctuation in English docs.
