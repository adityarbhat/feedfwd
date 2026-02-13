# FeedFwd

**Turn what you read into how you code.**

FeedFwd is a Claude Code plugin that turns articles, tutorials, and techniques you read into active knowledge that improves how Claude works with you — automatically.

## The Problem

You read 5 articles a week about AI, coding, and productivity. By next week, you've forgotten most of it. You never actually *use* what you learned.

## The Solution

1. You read something useful
2. Run `/learn <url>` in Claude Code
3. FeedFwd distills it into an actionable knowledge card
4. Next session, Claude automatically applies what you learned
5. Over time, low-value knowledge fades; high-value knowledge sticks

## Quick Start

```
# Learn from an article
/learn https://example.com/great-article

# Learn from multiple articles
/learn https://url1.com https://url2.com https://url3.com

# Paste text or a screenshot directly
/learn

# See your knowledge base
/knowledge

# Search for something specific
/knowledge search pydantic
```

## How It Works

FeedFwd operates on a simple loop:

**Capture** — `/learn` distills articles into concise knowledge cards
**Inject** — SessionStart hook surfaces relevant cards each session
**Feedback** — Stop hook tracks what's useful and what's not
**Evolve** — High-scoring knowledge sticks; low-scoring knowledge fades

Your knowledge lives in `~/.config/feedfwd/knowledge/` as plain markdown files. Human-readable, git-friendly, fully yours.

## Architecture

```
feedfwd/
├── .claude-plugin/plugin.json     # Plugin manifest
├── agents/distiller.md            # Subagent: raw content → knowledge card
├── skills/distiller/SKILL.md      # Knowledge card format spec
├── commands/
│   ├── learn.md                   # /learn command
│   └── knowledge.md               # /knowledge command
├── hooks/hooks.json               # SessionStart + Stop hooks
└── scripts/
    ├── knowledge.py               # Core data model & I/O
    ├── inject.py                  # SessionStart: inject relevant cards
    ├── feedback.py                # Stop: score cards based on usage
    ├── fetch_url.py               # URL content extraction
    └── card_cli.py                # CLI helper for card management
```

## Knowledge Cards

Each card is a markdown file with YAML frontmatter containing:

- **Injection Text** — A direct instruction to Claude (max 250 tokens)
- **Insight** — Human-readable summary of the technique
- **Example** — Before/after showing the technique in action
- **Triggers** — Keywords, file patterns, and task types for relevance matching

Cards are scored from 0.0 to 1.0. New cards start at 0.50 and evolve based on session feedback.

## Feedback System

FeedFwd uses session-type aware scoring to determine if injected knowledge was useful:

| Signal | Score Change |
|--------|-------------|
| Session type matches + keywords in diff | +0.10 |
| Session type matches OR keywords found | +0.05 |
| Neither matches | -0.02 |

An implicit boost cap of 0.70 prevents automated feedback from inflating scores unchecked. Beyond that requires explicit feedback.

## Commands

| Command | Description |
|---------|-------------|
| `/learn <url>` | Distill an article into a knowledge card |
| `/learn <url1> <url2> ...` | Batch learn from multiple URLs |
| `/learn` | Paste text or screenshot directly |
| `/knowledge` | List all cards grouped by category |
| `/knowledge search <term>` | Search across cards |
| `/knowledge show <name>` | Display a card's full content |
| `/knowledge edit <name>` | Edit a card |
| `/knowledge remove <name>` | Delete a card |
| `/knowledge stats` | Summary stats and top/low performers |

## Accessing Your Knowledge Base

Your knowledge cards live in `~/.config/feedfwd/` outside the plugin directory. To browse them from your project folder, create a symlink:

```bash
# From your project root
ln -s ~/.config/feedfwd knowledge-base
```

This gives you direct access to your cards:

```
knowledge-base/
├── knowledge/
│   ├── prompting/
│   ├── python/
│   ├── workflow/
│   ├── tools/
│   └── ...
├── _index.json
└── _session_log.json
```

The symlink is already in `.gitignore` — it won't be committed to your repo.

## Requirements

- Python 3.11+
- Claude Code
- Python packages: `httpx`, `beautifulsoup4`, `python-frontmatter`, `tiktoken`

## License

MIT
