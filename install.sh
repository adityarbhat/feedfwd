#!/bin/bash
# FeedFwd Installer
# ==================
# One command to install FeedFwd into Claude Code.
#
# Install:   curl -sL https://raw.githubusercontent.com/adityarbhat/feedfwd/main/install.sh | bash
# Uninstall: curl -sL https://raw.githubusercontent.com/adityarbhat/feedfwd/main/install.sh | bash -s -- --uninstall

set -e

INSTALL_DIR="$HOME/.claude/plugins/feedfwd"
COMMANDS_DIR="$HOME/.claude/commands"
AGENTS_DIR="$HOME/.claude/agents"
SKILLS_DIR="$HOME/.claude/skills"
SETTINGS_FILE="$HOME/.claude/settings.json"
SCRIPTS_DIR="$INSTALL_DIR/scripts"

# ─── Uninstall ────────────────────────────────────────────────────────
if [ "$1" = "--uninstall" ]; then
    echo "📡 FeedFwd Uninstaller"
    echo "======================"
    echo ""

    # Remove commands
    rm -f "$COMMANDS_DIR/learn.md" "$COMMANDS_DIR/knowledge.md" 2>/dev/null && \
        echo "→ Removed commands" || true

    # Remove agent
    rm -f "$AGENTS_DIR/distiller.md" 2>/dev/null && \
        echo "→ Removed agent" || true

    # Remove skills
    rm -rf "$SKILLS_DIR/distiller" 2>/dev/null && \
        echo "→ Removed skills" || true

    # Remove hooks from settings.json
    if [ -f "$SETTINGS_FILE" ]; then
        python3 << 'PYTHON_UNINSTALL'
import json, os

settings_file = os.path.expanduser("~/.claude/settings.json")
try:
    with open(settings_file, "r") as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    exit(0)

changed = False
for event in ["SessionStart", "Stop"]:
    if event in settings.get("hooks", {}):
        original = settings["hooks"][event]
        filtered = [g for g in original if not any("feedfwd" in h.get("command", "").lower() for h in g.get("hooks", []))]
        if len(filtered) != len(original):
            settings["hooks"][event] = filtered
            changed = True

if changed:
    with open(settings_file, "w") as f:
        json.dump(settings, f, indent=2)
    print("→ Removed hooks from settings.json")
PYTHON_UNINSTALL
    fi

    # Remove plugin source
    rm -rf "$INSTALL_DIR" 2>/dev/null && \
        echo "→ Removed plugin source" || true

    echo ""
    echo "✅ FeedFwd uninstalled."
    echo "   Your knowledge base at ~/.config/feedfwd/ was preserved."
    echo "   Delete it manually if you want: rm -rf ~/.config/feedfwd"
    exit 0
fi

# ─── Install ──────────────────────────────────────────────────────────
echo "📡 FeedFwd Installer"
echo "===================="
echo ""

# Prerequisite checks
if ! command -v git &> /dev/null; then
    echo "❌ git is required but not installed."
    echo "   Install it from https://git-scm.com/ and try again."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    echo "   Install Python 3.11+ from https://python.org/ and try again."
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo "❌ Python 3.11+ is required (found $PYTHON_VERSION)."
    echo "   Upgrade Python and try again."
    exit 1
fi

if [ ! -d "$HOME/.claude" ]; then
    echo "❌ Claude Code config directory (~/.claude/) not found."
    echo "   Install and run Claude Code first, then re-run this installer."
    exit 1
fi

echo "   Python $PYTHON_VERSION ✓"
echo ""

# 1. Clone or update the plugin source
if [ -d "$INSTALL_DIR" ]; then
    echo "→ Updating existing installation..."
    git -C "$INSTALL_DIR" pull --quiet
else
    echo "→ Cloning to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --quiet https://github.com/adityarbhat/feedfwd.git "$INSTALL_DIR"
fi

# 2. Install Python dependencies
echo "→ Installing Python dependencies..."
python3 -m pip install --quiet --user httpx beautifulsoup4 python-frontmatter tiktoken 2>/dev/null || \
pip3 install --quiet httpx beautifulsoup4 python-frontmatter tiktoken 2>/dev/null || \
{ echo "⚠️  Could not auto-install Python packages. Run manually:"; \
  echo "   pip install httpx beautifulsoup4 python-frontmatter tiktoken"; }

# 3. Create knowledge base directory structure
echo "→ Setting up knowledge base..."
mkdir -p "$HOME/.config/feedfwd/knowledge"/{prompting,python,workflow,tools,testing,architecture,debugging}

# 4. Install commands (with path rewriting)
echo "→ Installing commands..."
mkdir -p "$COMMANDS_DIR"

for cmd_file in "$INSTALL_DIR/commands"/*.md; do
    filename=$(basename "$cmd_file")
    sed -e "s|scripts/|$SCRIPTS_DIR/|g" \
        -e "s|\\\$PLUGIN_DIR/scripts/|$SCRIPTS_DIR/|g" \
        "$cmd_file" > "$COMMANDS_DIR/$filename"
done

# 5. Install agent (distiller) — rewrite paths
echo "→ Installing agents..."
mkdir -p "$AGENTS_DIR"

for agent_file in "$INSTALL_DIR/agents"/*.md; do
    filename=$(basename "$agent_file")
    sed -e "s|scripts/|$SCRIPTS_DIR/|g" \
        -e "s|\\\$PLUGIN_DIR/scripts/|$SCRIPTS_DIR/|g" \
        "$agent_file" > "$AGENTS_DIR/$filename"
done

# 6. Install skills
echo "→ Installing skills..."
if [ -d "$INSTALL_DIR/skills" ]; then
    mkdir -p "$SKILLS_DIR"
    cp -r "$INSTALL_DIR/skills"/* "$SKILLS_DIR/" 2>/dev/null || true
fi

# 7. Add hooks to Claude Code settings
echo "→ Configuring hooks..."
python3 << 'PYTHON_SCRIPT'
import json, os

settings_file = os.path.expanduser("~/.claude/settings.json")
scripts_dir = os.path.expanduser("~/.claude/plugins/feedfwd/scripts")

# Load existing settings
try:
    with open(settings_file, "r") as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

# Ensure hooks dict exists
if "hooks" not in settings:
    settings["hooks"] = {}

# SessionStart hook
session_start_hook = {
    "hooks": [{
        "type": "command",
        "command": f"python3 {scripts_dir}/inject.py",
        "timeout": 5,
        "statusMessage": "FeedFwd: loading knowledge cards..."
    }]
}

# Stop hook
stop_hook = {
    "hooks": [{
        "type": "command",
        "command": f"python3 {scripts_dir}/feedback.py",
        "timeout": 10,
        "statusMessage": "FeedFwd: updating card scores..."
    }]
}

# Avoid duplicates
def has_feedfwd_hook(hook_list):
    for group in hook_list:
        for hook in group.get("hooks", []):
            if "feedfwd" in hook.get("command", "").lower():
                return True
    return False

if "SessionStart" not in settings["hooks"]:
    settings["hooks"]["SessionStart"] = []
if not has_feedfwd_hook(settings["hooks"]["SessionStart"]):
    settings["hooks"]["SessionStart"].append(session_start_hook)

if "Stop" not in settings["hooks"]:
    settings["hooks"]["Stop"] = []
if not has_feedfwd_hook(settings["hooks"]["Stop"]):
    settings["hooks"]["Stop"].append(stop_hook)

with open(settings_file, "w") as f:
    json.dump(settings, f, indent=2)

print("   Hooks configured in settings.json")
PYTHON_SCRIPT

echo ""
echo "✅ FeedFwd installed!"
echo ""
echo "Start a new Claude Code session and try:"
echo "   /learn https://example.com/great-article"
echo ""
echo "Installed to:"
echo "   Scripts:        $INSTALL_DIR/scripts/"
echo "   Commands:       $COMMANDS_DIR/learn.md, knowledge.md"
echo "   Knowledge base: ~/.config/feedfwd/knowledge/"
echo ""
echo "To update:    re-run this installer"
echo "To uninstall: curl -sL https://raw.githubusercontent.com/adityarbhat/feedfwd/main/install.sh | bash -s -- --uninstall"
