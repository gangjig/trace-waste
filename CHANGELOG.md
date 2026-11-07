# Changelog

## 0.1.0 - 2026-11-07

- Initial release.
- JSONL trace parsing with a tolerant schema: reasoning/text steps, tool
  calls, tool results, and context segments; unknown event types are kept
  and counted but not waste-checked.
- Deterministic offline heuristic judge (no API key) covering four waste
  categories: repeated tool calls with identical results, near-duplicate
  reasoning blocks, tool results never referenced later, and context
  segments never referenced later.
- Pluggable judge interface plus an optional `--judge-command` external
  judge hook (off by default).
- Human-readable report and `--json` output: per-category waste tokens,
  waste share of the run, estimated savings, optional dollar conversion
  and a `--fail-above` CI gate. Token counts use a documented
  characters/4 estimate unless an event carries its own `tokens` value.
- CLI: `analyze`, `demo`. Standard library only.
