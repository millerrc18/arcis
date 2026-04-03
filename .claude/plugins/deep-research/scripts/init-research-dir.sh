#!/usr/bin/env bash
# Initialize deep-research plugin environment
# Run from the deep-research plugin directory
# Compatible with Git Bash on Windows

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$PLUGIN_DIR/server"

echo "=== Deep Research Plugin Setup ==="
echo "Plugin directory: $PLUGIN_DIR"
echo ""

# Check Python
if command -v py &>/dev/null; then
    PY=py
elif command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "ERROR: Python not found. Install Python 3.10+ and try again."
    exit 1
fi

echo "Using Python: $($PY --version)"

# Check Python version
$PY -c "import sys; assert sys.version_info >= (3, 10), f'Python 3.10+ required, got {sys.version}'" || {
    echo "ERROR: Python 3.10 or higher is required."
    exit 1
}

# Install dependencies
echo ""
echo "Installing Python dependencies..."
$PY -m pip install -r "$SERVER_DIR/requirements.txt" --quiet

# Verify MCP server starts
echo ""
echo "Verifying MCP server..."
timeout 5 $PY "$SERVER_DIR/research_mcp_server.py" 2>&1 | head -3 || true
echo "MCP server OK"

# Check API keys
echo ""
echo "=== API Key Status ==="
echo ""

check_key() {
    local key_name=$1
    local required=$2
    local desc=$3
    if [ -n "${!key_name}" ]; then
        echo "  [OK] $key_name — $desc"
    elif [ "$required" = "recommended" ]; then
        echo "  [--] $key_name — $desc (recommended but not set)"
    else
        echo "  [  ] $key_name — $desc (optional)"
    fi
}

echo "Tier 1 (Core — free tiers available):"
check_key TAVILY_API_KEY recommended "AI-optimized web search (free 1K/mo)"
check_key EXA_API_KEY recommended "Semantic/neural search (free 1K/mo)"
check_key FIRECRAWL_API_KEY recommended "Content extraction + JS rendering (free 500/mo)"
echo ""
echo "Tier 2 (Complements):"
check_key SERPER_API_KEY optional "Google search results"
check_key BRAVE_API_KEY optional "Independent search index (free 2K/mo)"
check_key NEWSAPI_KEY optional "News search"
echo ""
echo "Tier 3 (Specialized):"
check_key WOLFRAM_APP_ID optional "Computational answers"
check_key SERPAPI_KEY optional "Google Scholar access"
echo ""
echo "Free APIs (always active, no key needed):"
echo "  [OK] Semantic Scholar, OpenAlex, CrossRef, Unpaywall,"
echo "       arXiv, PubMed, GDELT, FRED, SEC EDGAR, Wikipedia"

# Create default output directory
echo ""
mkdir -p docs/research
echo "Output directory: docs/research/"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Usage:  /research \"your question here\""
echo "        /research \"topic\" --depth deep --domain aerospace-engineering"
echo ""
echo "To set API keys, add them to your shell profile or .env file."
