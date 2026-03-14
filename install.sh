#!/usr/bin/env bash
set -euo pipefail

# ─── VoiceStack3 Installer ──────────────────────────────────────────────────
# Works on macOS (Apple Silicon) and Linux (with or without NVIDIA GPU).
# Installs Docker if needed, configures .env, pulls images and starts services.

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$REPO_DIR/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[voicestack3]${NC} $*"; }
ok()    { echo -e "${GREEN}[voicestack3]${NC} $*"; }
warn()  { echo -e "${YELLOW}[voicestack3]${NC} $*"; }
err()   { echo -e "${RED}[voicestack3]${NC} $*" >&2; }

# ─── Detect platform ────────────────────────────────────────────────────────

OS="$(uname -s)"
ARCH="$(uname -m)"
HAS_NVIDIA=false
PLATFORM="cpu"

if [ "$OS" = "Linux" ]; then
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        HAS_NVIDIA=true
        PLATFORM="cuda"
    fi
elif [ "$OS" = "Darwin" ]; then
    PLATFORM="cpu"  # No GPU passthrough on macOS containers
fi

info "Platform: $OS ($ARCH)"
if [ "$HAS_NVIDIA" = true ]; then
    ok "NVIDIA GPU detected — using CUDA acceleration"
else
    info "No NVIDIA GPU — using CPU mode (still works great, just slower)"
fi
echo ""

# ─── Detect container runtime ────────────────────────────────────────────────

detect_compose() {
    if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
        echo "docker compose"
    elif command -v podman &>/dev/null && podman compose version &>/dev/null 2>&1; then
        echo "podman compose"
    elif command -v podman-compose &>/dev/null; then
        echo "podman-compose"
    else
        echo ""
    fi
}

# ─── Step 1: Install Docker ─────────────────────────────────────────────────

install_docker() {
    COMPOSE_CMD="$(detect_compose)"
    if [ -n "$COMPOSE_CMD" ]; then
        ok "Container runtime found: $COMPOSE_CMD"
        return
    fi

    info "No container runtime found. Installing Docker..."

    if [ "$OS" = "Darwin" ]; then
        if ! command -v brew &>/dev/null; then
            err "Homebrew required. Install it first: https://brew.sh"
            exit 1
        fi
        brew install --cask docker
        info "Docker Desktop installed. Please open Docker Desktop and wait for it to start, then re-run this script."
        exit 0
    elif [ "$OS" = "Linux" ]; then
        info "Installing Docker via get.docker.com..."
        curl -fsSL https://get.docker.com | sh
        sudo systemctl enable --now docker
        sudo usermod -aG docker "$USER"
        warn "You were added to the docker group. You may need to log out and back in."
    fi

    COMPOSE_CMD="$(detect_compose)"
    if [ -z "$COMPOSE_CMD" ]; then
        err "Docker compose not available after install. Please install Docker manually."
        exit 1
    fi
    ok "Docker installed"
}

# ─── Step 2: Install NVIDIA Container Toolkit (Linux only) ──────────────────

install_nvidia_toolkit() {
    if [ "$HAS_NVIDIA" != true ]; then return; fi

    # Check if CDI spec already exists
    if [ -f /etc/cdi/nvidia.yaml ] || [ -f /var/run/cdi/nvidia.yaml ]; then
        ok "NVIDIA CDI spec already configured"
        return
    fi

    # Also check if docker nvidia runtime exists
    if docker info 2>/dev/null | grep -q nvidia; then
        ok "NVIDIA runtime already configured"
        return
    fi

    if ! command -v nvidia-ctk &>/dev/null; then
        info "Installing NVIDIA Container Toolkit..."
        if command -v dnf &>/dev/null; then
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo | \
                sudo tee /etc/yum.repos.d/nvidia-container-toolkit.repo > /dev/null
            sudo dnf install -y nvidia-container-toolkit
        elif command -v apt-get &>/dev/null; then
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
                sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
            curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
                sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
                sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
            sudo apt-get update
            sudo apt-get install -y nvidia-container-toolkit
        fi
    fi

    info "Configuring NVIDIA runtime..."
    sudo nvidia-ctk runtime configure --runtime=docker 2>/dev/null || \
        sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml 2>/dev/null || true
    sudo systemctl restart docker 2>/dev/null || true
    ok "NVIDIA Container Toolkit configured"
}

# ─── Step 3: Configure .env ─────────────────────────────────────────────────

configure_env() {
    if [ -f "$ENV_FILE" ]; then
        ok ".env already exists — keeping your config"
        return
    fi

    info "Creating .env from template..."
    cp "$REPO_DIR/.env.example" "$ENV_FILE"

    # Generate a random API token
    API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null || openssl rand -base64 24)"
    if [ "$OS" = "Darwin" ]; then
        sed -i '' "s|API_TOKEN=changeme|API_TOKEN=$API_TOKEN|" "$ENV_FILE"
    else
        sed -i "s|API_TOKEN=changeme|API_TOKEN=$API_TOKEN|" "$ENV_FILE"
    fi

    # Set platform-appropriate defaults
    if [ "$PLATFORM" = "cuda" ]; then
        if [ "$OS" = "Darwin" ]; then
            sed -i '' "s|WORKER_TAG=cpu|WORKER_TAG=latest|" "$ENV_FILE"
        else
            sed -i "s|WORKER_TAG=cpu|WORKER_TAG=latest|" "$ENV_FILE"
        fi
    else
        if [ "$OS" = "Darwin" ]; then
            sed -i '' "s|WHISPER_COMPUTE_TYPE=float16|WHISPER_COMPUTE_TYPE=int8|" "$ENV_FILE"
            sed -i '' "s|WHISPER_BATCH_SIZE=16|WHISPER_BATCH_SIZE=8|" "$ENV_FILE"
        else
            sed -i "s|WHISPER_COMPUTE_TYPE=float16|WHISPER_COMPUTE_TYPE=int8|" "$ENV_FILE"
            sed -i "s|WHISPER_BATCH_SIZE=16|WHISPER_BATCH_SIZE=8|" "$ENV_FILE"
        fi
    fi

    ok ".env configured"
}

# ─── Step 4: Pull and start ──────────────────────────────────────────────────

start_services() {
    cd "$REPO_DIR"

    COMPOSE_CMD="$(detect_compose)"

    COMPOSE_FILES="-f docker-compose.yml"
    if [ "$HAS_NVIDIA" = true ]; then
        COMPOSE_FILES="$COMPOSE_FILES -f compose.gpu.yml"
    fi

    info "Pulling images (this may take a while on first run)..."
    $COMPOSE_CMD $COMPOSE_FILES pull

    info "Starting services..."
    $COMPOSE_CMD $COMPOSE_FILES up -d

    # Wait for backend health
    info "Waiting for backend to be ready..."
    for i in $(seq 1 30); do
        if curl -sf http://localhost:8000/health &>/dev/null; then
            break
        fi
        sleep 2
    done

    if curl -sf http://localhost:8000/health &>/dev/null; then
        ok "Backend is healthy"
    else
        warn "Backend not responding yet — check logs with: $COMPOSE_CMD logs backend"
    fi
}

# ─── Step 5: Print summary ──────────────────────────────────────────────────

print_summary() {
    COMPOSE_CMD="$(detect_compose)"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ok "VoiceStack3 is running!"
    echo ""
    info "Open in your browser:  http://localhost:3000"
    echo ""
    info "Manage services:"
    if [ "$HAS_NVIDIA" = true ]; then
        info "  Start:   $COMPOSE_CMD -f docker-compose.yml -f compose.gpu.yml up -d"
        info "  Stop:    $COMPOSE_CMD -f docker-compose.yml -f compose.gpu.yml down"
        info "  Logs:    $COMPOSE_CMD -f docker-compose.yml -f compose.gpu.yml logs -f"
    else
        info "  Start:   $COMPOSE_CMD up -d"
        info "  Stop:    $COMPOSE_CMD down"
        info "  Logs:    $COMPOSE_CMD logs -f"
    fi
    echo ""
    info "First-time setup:"
    info "  1. Go to Settings in the UI"
    info "  2. Add your OpenAI API key (or any OpenAI-compatible endpoint)"
    info "  3. Upload an audio file and watch the magic happen"
    echo ""
    if [ "$PLATFORM" = "cpu" ]; then
        info "Running in CPU mode. Models are baked into the images — no downloads needed."
        info "Processing takes ~2-3x the audio length (e.g., 10 min audio ≈ 20-30 min)."
    else
        info "Running with NVIDIA GPU. Models are baked into the images — no downloads needed."
        info "Processing is typically faster than real-time."
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ─── Main ────────────────────────────────────────────────────────────────────

echo ""
echo "  ╦  ╦┌─┐┬┌─┐┌─┐╔═╗┌┬┐┌─┐┌─┐┬┌─  ┌─┐"
echo "  ╚╗╔╝│ ││├─┘├┤ ╚═╗ │ ├─┤│  ├┴┐  ─┤ "
echo "   ╚╝ └─┘┴└  └─┘╚═╝ ┴ ┴ ┴└─┘┴ ┴  └─┘"
echo "                                     v3"
echo ""

install_docker
install_nvidia_toolkit
configure_env
start_services
print_summary
