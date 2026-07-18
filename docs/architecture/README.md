# Architecture diagrams

This directory contains two complementary views:

- `package-dependencies.puml` is the stable package responsibility and
  dependency map.
- `request-flow.puml` follows one request through input, orchestration,
  optional MCP tool dispatch, Ollama, journaling, TTS, and UI projection.

The exhaustive symbol-level graph remains available in
`graphify-out/graph.html`; it is generated developer data and is not committed.

## Local PlantUML verification

Java 17 or newer is required. Install the pinned official PlantUML JAR once:

```powershell
python tools/plantuml.py install
```

The JAR is downloaded from the official PlantUML GitHub release, checked
against its published SHA-256 digest, and stored under the ignored `.tools/`
developer cache. No PlantUML server is used.

Check every diagram without writing images:

```powershell
python tools/plantuml.py check
```

Render every diagram as SVG into `docs/architecture/rendered/`:

```powershell
python tools/plantuml.py render
```

Pass one or more `.puml` paths to check or render only selected diagrams. Use
`--format png` or `--output-dir PATH` to override render defaults.
