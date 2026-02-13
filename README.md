<div align="center">

# FEEDFWD

**Turn what you read into how you code.**

**A Claude Code plugin that bridges the gap between learning and doing. You read articles and discover techniques — FeedFwd distills them into actionable knowledge that automatically improves how Claude works with you.**

[![GitHub stars](https://img.shields.io/github/stars/adityarbhat/feedfwd?style=for-the-badge&logo=github&color=181717)](https://github.com/adityarbhat/feedfwd)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

<br>

```
/learn <url> | <screenshot> | <pasted text>
```

**One command. Any input. Knowledge captured forever.**

<br>

[Why I Built This](#why-i-built-this) · [Getting Started](#getting-started) · [How It Works](#how-it-works) · [Commands](#commands)

</div>

---

## Why I Built This

Every week I consume articles, tutorials, and posts about AI workflows, prompting techniques, coding patterns, and developer productivity. Within days, most of it fades. I never implement the things I read about — not because they weren't valuable, but because the gap between "I read about it" and "I use it in my workflow" is too wide.

Existing tools solve adjacent problems but not this one:
- **PKM tools** (Obsidian, Notion) store knowledge but don't inject it into your tools
- **Claude Code plugins** offer static best practices that don't evolve with your learning
- **Continuous learning plugins** learn from your sessions but don't incorporate external knowledge

FeedFwd closes the loop: **capture → distill → inject → feedback**.

You read something useful, run `/learn`, and FeedFwd distills it into a concise knowledge card. Next time you start a Claude Code session, the relevant knowledge is automatically injected. Over time, cards that prove useful rise in score. Cards that don't fade away.

No manual organization. No tagging. No remembering to apply what you learned. It just works.

---

## Getting Started

### One-Command Install

```bash
curl -sL https://raw.githubusercontent.com/adityarbhat/feedfwd/main/install.sh | bash
```

This does everything in one step:

1. Clones the plugin to `~/.claude/plugins/feedfwd/`
2. Installs Python dependencies (`httpx`, `beautifulsoup4`, `python-frontmatter`, `tiktoken`)
3. Copies `/learn` and `/knowledge` commands to `~/.claude/commands/`
4. Adds SessionStart and Stop hooks to `~/.claude/settings.json`
5. Creates the knowledge base at `~/.config/feedfwd/knowledge/`

Then start a **new** Claude Code session and try:

```
/learn https://example.com/great-article
```

**Works on Mac and Linux. Requires Python 3.11+ and Claude Code.**

<details>
<summary><strong>Development Installation</strong></summary>

For contributing or testing changes locally, use `--plugin-dir` to load the plugin directly:

```bash
git clone https://github.com/adityarbhat/feedfwd.git
cd feedfwd
pip install httpx beautifulsoup4 python-frontmatter tiktoken
claude --plugin-dir .
```

This loads the plugin for a single session without modifying your Claude Code settings.

</details>

### Updating

Re-run the installer to pull the latest version:

```bash
curl -sL https://raw.githubusercontent.com/adityarbhat/feedfwd/main/install.sh | bash
```

### Accessing Your Knowledge Base

Your knowledge cards live in `~/.config/feedfwd/` outside the plugin directory. To browse them from any project, create a symlink:

```bash
ln -s ~/.config/feedfwd knowledge-base
```

The symlink is in `.gitignore` — it won't be committed to your repo.

---

## How It Works

FeedFwd operates on a simple loop that runs in the background of every Claude Code session.

### 1. Capture

Feed knowledge in any format you want:

```bash
# From a URL
/learn https://simonwillison.net/2025/Feb/thinking-patterns/

# From multiple URLs at once
/learn https://url1.com https://url2.com https://url3.com

# Paste text or drop a screenshot — just run /learn with no args
/learn
```

The distiller subagent reads your input, extracts the **one core actionable technique**, and writes it as a knowledge card — a direct instruction to Claude, not a summary.

```
✅ Learned: thinking-patterns → prompting/thinking-patterns.md
```

### 2. Inject

Every time you start a Claude Code session, the SessionStart hook fires automatically:

```
📚 FeedFwd — active learnings for this session:
• [Thinking Patterns] When tackling complex problems, break into
  phases: understand → plan → implement → verify. Spend 40% on planning.
• [Uv Inline Dependencies] When creating standalone Python scripts,
  use PEP 723 inline script dependencies with the # /// script block.
```

Only the 2-3 most relevant cards are injected, based on:
- What languages and frameworks your project uses
- What's in your CLAUDE.md
- What you've been working on recently (git log)

Max 400 tokens. Minimal overhead.

### 3. Feedback

When your session ends, the Stop hook analyzes what happened:

- **What kind of session was it?** Planning-heavy (markdown files) or code-heavy (source files)?
- **Were the card's keywords used?** Did the techniques appear in your git diff?

Cards that matched the session get a score boost. Cards that didn't get a gentle decay. No manual feedback needed.

### 4. Evolve

Over time, your knowledge base self-organizes:
- High-scoring cards surface more often
- Low-scoring cards fade naturally
- The implicit boost cap (0.70) prevents runaway inflation — beyond that requires explicit feedback

```
/knowledge stats

📊 FeedFwd Stats
Total cards: 12
Active (score > 0.3): 10
Top performers:
  ★ 0.70  ultrathink-prompting     (8 sessions, 6 useful)
  ★ 0.65  structured-outputs       (5 sessions, 4 useful)
Low performers (consider removing):
  ★ 0.18  react-server-components  (3 sessions, 0 useful)
```

---

## Commands

### Learning

| Command | What it does |
|---------|--------------|
| `/learn <url>` | Fetch and distill an article into a knowledge card |
| `/learn <url1> <url2> ...` | Batch learn from multiple URLs |
| `/learn` (then paste text) | Distill from pasted text |
| `/learn` (then drop screenshot) | Distill from a screenshot |

### Knowledge Management

| Command | What it does |
|---------|--------------|
| `/knowledge` | List all cards grouped by category |
| `/knowledge search <term>` | Search across cards |
| `/knowledge show <name>` | Display a card's full content |
| `/knowledge edit <name>` | Edit a card's markdown file |
| `/knowledge remove <name>` | Delete a card |
| `/knowledge stats` | Summary stats and top/low performers |

---

## Architecture

```
feedfwd/
├── .claude-plugin/plugin.json     # Plugin manifest
├── agents/distiller.md            # Subagent: raw content → knowledge card
├── skills/distiller/SKILL.md      # Knowledge card format specification
├── commands/
│   ├── learn.md                   # /learn command definition
│   └── knowledge.md               # /knowledge command definition
├── hooks/hooks.json               # SessionStart + Stop lifecycle hooks
└── scripts/
    ├── knowledge.py               # Core data model & I/O layer
    ├── inject.py                  # SessionStart: context-aware card injection
    ├── feedback.py                # Stop: session-type aware scoring
    ├── fetch_url.py               # URL content extraction
    └── card_cli.py                # CLI helper for card management
```

### Knowledge Cards

Each card is a markdown file with YAML frontmatter:

```markdown
---
name: ultrathink-prompting
source: "https://example.com/article"
category: prompting
score: 0.50
triggers:
  keywords: [complex reasoning, multi-step, planning]
  file_patterns: ["*.py", "*.md"]
injection_tokens: 145
---

## Injection Text
When tackling complex problems, break into phases:
understand → plan → implement → verify.
```

The **Injection Text** is what Claude sees. Max 250 tokens. Written as a direct instruction, not a summary.

### Scoring

**Injection relevance:**
```
relevance = keyword_overlap * 0.6 + card_score * 0.4
```

**Session feedback:**

| Signal | Score Change |
|--------|-------------|
| Session type matches + keywords in diff | +0.10 |
| Session type matches OR keywords found | +0.05 |
| Neither matches | -0.02 |

Implicit feedback caps at 0.70. New cards start at 0.50. Range: 0.0 to 1.0.

---

## User Data

Your knowledge base lives in `~/.config/feedfwd/` — outside the plugin directory. This means:

- Knowledge persists across plugin updates
- Knowledge is global across all projects
- Easy to back up and version control independently
- Fully yours — plain markdown files you can read and edit

---

## Requirements

- Python 3.11+
- Claude Code
- Python packages: `httpx`, `beautifulsoup4`, `python-frontmatter`, `tiktoken`

---

## Roadmap

| Version | Theme | Key Features |
|---------|-------|-------------|
| **v0.1** | Core Loop | `/learn`, injection, feedback, `/knowledge` |
| **v0.2** | Intelligence | Semantic matching, auto-decay, graduation to rules, import/export |
| **v0.3** | Ecosystem | Browser extension, community knowledge packs, Readwise integration |
| **v0.4** | Teams | Shared team knowledge bases, onboarding packs |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Reading about best practices should mean using them.**

</div>
