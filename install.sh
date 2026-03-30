#!/bin/sh
# Halyn install script
# https://halyn.dev/install
#
# This script will:
#   1. Check Python version (requires 3.10+)
#   2. Ask permission before installing
#   3. Run: pip install halyn==2.1.3
#   4. Tell you how to start the dashboard
#
# PHY §2 — this script asks permission before acting.

set -e

HALYN_VERSION="2.1.3"
HALYN_DASHBOARD="http://localhost:7420"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
DIM='\033[0;37m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo "  ${BOLD}Halyn${NC} — governance layer for AI agents"
echo "  ${DIM}https://halyn.dev${NC}"
echo ""

# Check Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ${RED}Error:${NC} Python 3 not found."
  echo "  Install Python 3.10+ from https://python.org"
  exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "  ${RED}Error:${NC} Python $PY_VERSION found, but Halyn requires Python 3.10+."
  exit 1
fi

echo "  ${GREEN}✓${NC} Python $PY_VERSION"
echo ""
echo "  ${BOLD}This script will run:${NC}"
echo "    pip install halyn==${HALYN_VERSION}"
echo ""
printf "  Proceed? [y/N] "
read -r REPLY

case "$REPLY" in
  [Yy]|[Yy][Ee][Ss])
    ;;
  *)
    echo "  Aborted."
    exit 0
    ;;
esac

echo ""
echo "  Installing halyn ${HALYN_VERSION}..."
pip install "halyn==${HALYN_VERSION}" --quiet

echo ""
echo "  ${GREEN}✓${NC} Halyn ${HALYN_VERSION} installed"
echo ""
echo "  Start the dashboard:"
echo "    ${BLUE}halyn serve${NC}"
echo ""
echo "  Then open: ${DIM}${HALYN_DASHBOARD}${NC}"
echo ""
