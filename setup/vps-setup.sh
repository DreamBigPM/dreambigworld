#!/bin/bash
# ============================================================
#  The Wolf Pack — VPS Setup Script
#  Run once on a fresh Ubuntu 22.04 or 24.04 server
#  Usage:  bash <(curl -fsSL https://raw.githubusercontent.com/wocros/wolf-pack/main/setup/vps-setup.sh)
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
info() { echo -e "  ${BLUE}→${NC}  $1"; }
warn() { echo -e "  ${YELLOW}!${NC}  $1"; }
fail() { echo -e "  ${RED}✗${NC}  $1"; echo ""; echo "  Setup stopped. Fix the issue above and run the script again."; echo ""; exit 1; }
divider() { echo -e "${BOLD}--------------------------------------------${NC}"; }

clear
echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}       The Wolf Pack — Server Setup        ${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
echo "  This runs once. Takes about 5 minutes."
echo "  Follow the prompts. Don't close this window."
echo ""
divider
echo ""

# ── Root check ─────────────────────────────────────────────
if [[ "$EUID" -ne 0 ]]; then
  fail "Please run as root. Try: sudo bash vps-setup.sh"
fi

# ── OS check ───────────────────────────────────────────────
if ! grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
  warn "This script is designed for Ubuntu. Continuing anyway — some steps may fail."
  echo ""
fi

# ── Step 1: Update the server ──────────────────────────────
echo -e "${BOLD}[1/6] Updating your server...${NC}"
info "This can take a minute. Hang tight."
echo ""
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq
ok "Server is up to date"
echo ""

# ── Step 2: Install essentials ─────────────────────────────
echo -e "${BOLD}[2/6] Installing tools...${NC}"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  git curl wget unzip build-essential ca-certificates gnupg || fail "Could not install required tools."
ok "Core tools ready"
echo ""

# ── Step 3: Install Node.js ────────────────────────────────
echo -e "${BOLD}[3/6] Installing Node.js...${NC}"
if command -v node &>/dev/null; then
  ok "Node.js already installed ($(node --version)) — skipping"
else
  info "Downloading Node.js installer..."
  curl -fsSL https://deb.nodesource.com/setup_lts.x -o /tmp/nodesource_setup.sh
  if [[ ! -s /tmp/nodesource_setup.sh ]]; then
    fail "Could not download Node.js installer. Check your internet connection."
  fi
  bash /tmp/nodesource_setup.sh > /dev/null 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs
  if ! command -v node &>/dev/null; then
    fail "Node.js installation failed. Try running the script again."
  fi
  ok "Node.js $(node --version) installed"
fi
echo ""

# ── Step 4: Install Claude Code ────────────────────────────
echo -e "${BOLD}[4/6] Installing Claude Code...${NC}"
if command -v claude &>/dev/null; then
  ok "Claude Code already installed — skipping"
else
  info "Installing (this takes about 30 seconds)..."
  npm install -g @anthropic-ai/claude-code 2>&1 | tail -1
  if ! command -v claude &>/dev/null; then
    fail "Claude Code installation failed. Check that Node.js installed correctly (run: node --version)."
  fi
  ok "Claude Code installed"
fi
echo ""

# ── Step 5: Set up your Anthropic API key ──────────────────
echo -e "${BOLD}[5/6] Connect your Anthropic account${NC}"
echo ""
echo "  Your API key is what connects this server to Claude's brain."
echo "  It looks like:  sk-ant-api03-..."
echo ""
echo "  Don't have one yet?"
echo "    1. Go to console.anthropic.com"
echo "    2. Sign in → API Keys → Create Key → copy it"
echo "    3. Add billing credit (Billing → Add credit card → Add \$10)"
echo ""
divider
echo ""

APIKEY=""
ATTEMPTS=0
MAX_ATTEMPTS=5

while true; do
  ATTEMPTS=$((ATTEMPTS + 1))

  if [[ $ATTEMPTS -gt $MAX_ATTEMPTS ]]; then
    echo ""
    warn "Too many failed attempts."
    echo ""
    echo "  Your key will be saved as-is. You can update it later by running:"
    echo ""
    echo -e "  ${BOLD}nano ~/.bashrc${NC}  (find the ANTHROPIC_API_KEY line and replace it)"
    echo ""
    APIKEY="REPLACE_WITH_YOUR_API_KEY"
    break
  fi

  read -rp "  Paste your API key and press Enter: " APIKEY
  echo ""

  # Empty check
  if [[ -z "$APIKEY" ]]; then
    warn "Nothing entered. Try again."
    echo ""
    continue
  fi

  # Trim whitespace
  APIKEY=$(echo "$APIKEY" | tr -d '[:space:]')

  # Format check
  if [[ ! "$APIKEY" == sk-ant-* ]]; then
    warn "This doesn't look like an Anthropic key (should start with sk-ant-)."
    echo ""
    read -rp "  Try again (t) or save it anyway (s): " CHOICE
    echo ""
    [[ "$CHOICE" == "s" || "$CHOICE" == "S" ]] && break
    continue
  fi

  # Test the key
  info "Testing your key..."
  HTTP_STATUS=$(curl -s -o /tmp/api_test_response.txt -w "%{http_code}" \
    --connect-timeout 10 --max-time 20 \
    -H "x-api-key: $APIKEY" \
    -H "anthropic-version: 2023-06-01" \
    -H "content-type: application/json" \
    -d '{"model":"claude-haiku-4-5-20251001","max_tokens":5,"messages":[{"role":"user","content":"hi"}]}' \
    https://api.anthropic.com/v1/messages 2>/dev/null)

  if [[ "$HTTP_STATUS" == "200" ]]; then
    ok "API key works!"
    echo ""
    break

  elif [[ "$HTTP_STATUS" == "401" ]]; then
    echo ""
    warn "Key rejected (401). Most common reasons:"
    echo ""
    echo "    1. No billing credit — go to console.anthropic.com → Billing"
    echo "       Add a credit card and at least \$10 in credit."
    echo ""
    echo "    2. Key copied incorrectly — try copying it again from the console."
    echo ""
    read -rp "  Try a different key (t) or save this one anyway (s): " CHOICE
    echo ""
    [[ "$CHOICE" == "s" || "$CHOICE" == "S" ]] && break

  elif [[ "$HTTP_STATUS" == "429" ]]; then
    ok "Key is valid (rate limit hit — totally fine). Saving."
    echo ""
    break

  elif [[ "$HTTP_STATUS" == "000" ]]; then
    warn "Could not reach Anthropic (network timeout). Check your internet connection."
    echo ""
    read -rp "  Try again (t) or save the key anyway (s): " CHOICE
    echo ""
    [[ "$CHOICE" == "s" || "$CHOICE" == "S" ]] && break

  else
    warn "Unexpected response (HTTP $HTTP_STATUS). Saving key anyway."
    echo ""
    break
  fi
done

# Save the key
grep -v "ANTHROPIC_API_KEY" ~/.bashrc > /tmp/.bashrc_tmp 2>/dev/null && mv /tmp/.bashrc_tmp ~/.bashrc
echo "" >> ~/.bashrc
echo "# Wolf Pack — Anthropic API Key" >> ~/.bashrc
echo "export ANTHROPIC_API_KEY=\"$APIKEY\"" >> ~/.bashrc
export ANTHROPIC_API_KEY="$APIKEY"
ok "API key saved to ~/.bashrc"
echo ""

# ── Step 6: Create workspace ───────────────────────────────
echo -e "${BOLD}[6/6] Setting up your workspace...${NC}"

# Create projects folder
mkdir -p /root/wolf-pack/projects
ok "Workspace ready at /root/wolf-pack"

# Set up git identity if not already done
GIT_NAME=$(git config --global user.name 2>/dev/null || true)
GIT_EMAIL=$(git config --global user.email 2>/dev/null || true)

if [[ -z "$GIT_NAME" ]]; then
  echo ""
  echo "  Git needs your name and email to track your work."
  echo "  Use your real name — it shows up on your GitHub commits."
  echo ""
  read -rp "  Your full name: " GIT_NAME
  read -rp "  Your email address: " GIT_EMAIL
  git config --global user.name "$GIT_NAME"
  git config --global user.email "$GIT_EMAIL"
  ok "Git configured for $GIT_NAME"
else
  ok "Git already configured ($GIT_NAME)"
fi

git config --global init.defaultBranch main
echo ""

# ── Done ───────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}============================================${NC}"
echo -e "${GREEN}${BOLD}   You're in the pack. Server is ready.${NC}"
echo -e "${GREEN}${BOLD}============================================${NC}"
echo ""
echo "  Before you move on, run this command:"
echo ""
echo -e "  ${BOLD}source ~/.bashrc${NC}"
echo ""
echo "  That activates your API key in this session."
echo ""
divider
echo ""
echo "  Next steps:"
echo "  1. Run:  source ~/.bashrc"
echo "  2. Go back to your class checklist — Part 5"
echo "     Fork the Wolf Pack repo on GitHub, then clone YOUR copy here"
echo ""
