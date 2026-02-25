# Iteration Log

This file is a template and writing guide for iteration records in `docs/logs/`.

## How to Use
- Add a new file under `docs/logs/` for each non-trivial behavior change.
- Prefer describing user-visible behavior and parsing/notification rule changes.
- Keep one iteration per file to make review and history lookup easier.
- Focus on requirement context, design decisions, and implementation steps.

## File Naming
- Recommended format: `YYYY-MM-DD-short-title.md`
- Example: `2026-02-24-codex-exec-command-escalation-confirmation.md`

## Entry Template (copy to docs/logs/<new-file>.md)

```md
## YYYY-MM-DD - Short title

### Requirement Background
- Why this change is needed.

### Solution Design
- Design goals and key decisions.
- Tradeoffs or fallback strategy (if any).

### Implementation Process
- Main implementation steps in order.
- Related docs/config/code updates.
```
