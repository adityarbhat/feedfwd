# FeedFwd Knowledge Card Format Specification
# ================================================================
# This skill defines the canonical format for knowledge cards.
# It serves as a reference for the distiller subagent and any
# component that reads or writes knowledge cards.
#
# How it works in Claude Code:
#   Skills are reference documents that Claude can consult. They
#   live in skills/<name>/SKILL.md and are discovered automatically.
#   Unlike agents (which do work), skills provide knowledge.
# ================================================================

---
name: distiller
description: >
  Knowledge card format specification for FeedFwd. Defines the structure,
  fields, and rules for creating and maintaining knowledge cards.
---

## Knowledge Card Format

Each knowledge card is a markdown file with YAML frontmatter stored in
`~/.config/feedfwd/knowledge/<category>/<name>.md`.

### Required YAML Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Kebab-case identifier (also the filename without .md) |
| `source` | string | Original URL, "pasted-text", or "screenshot" |
| `captured` | date | ISO date when the card was created (YYYY-MM-DD) |
| `category` | string | One of the predefined categories or a new one |
| `score` | float | Relevance score, 0.0–1.0. New cards start at 0.50 |
| `times_surfaced` | int | How many sessions this card has been injected into |
| `times_useful` | int | How many times the user marked it as useful |
| `triggers.keywords` | list | Words that signal this card is relevant |
| `triggers.file_patterns` | list | Glob patterns for relevant file types |
| `triggers.task_types` | list | Task categories where this applies |
| `injection_tokens` | int | Pre-computed token count of the Injection Text |

### Required Markdown Sections

1. **## Insight** — 2-3 sentences. Human-readable summary. Never injected.
2. **## Injection Text** — Direct instruction to Claude. Hard cap: 250 tokens.
   Written as actionable guidance, not article summary.
3. **## Example** — Before/after demonstrating the technique in action.

### Categories

Predefined: `prompting`, `python`, `workflow`, `tools`, `testing`,
`architecture`, `debugging`

New categories can be created as needed. Each category is a subdirectory
under `~/.config/feedfwd/knowledge/`.

### Scoring Rules

| Signal | Score Change |
|--------|-------------|
| New card created | Set to 0.50 |
| User says "useful" | +0.15 |
| Implicit: technique applied in session | +0.10 |
| User says "not useful" | -0.10 |
| Implicit: injected but not referenced | -0.02 |
| Skipped / no response | 0.00 |

Score is clamped to range [0.0, 1.0].
