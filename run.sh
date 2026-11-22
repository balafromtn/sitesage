#!/usr/bin/env bash
# ======================================================================
#                    SiteSage - One-Click Launcher (Linux/macOS)
# ======================================================================

set -e

# Change to script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================================"
echo "                    SiteSage - One-Click Launcher"
echo "======================================================================"
echo ""

# 1. Check for Python installation
PYTHON_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    echo "[ERROR] Python was not found in PATH."
    echo "Please install Python 3.10 or higher (e.g. sudo apt install python3 python3-venv python3-pip)."
    exit 1
fi

# 2. Check Python version (>= 3.10)
PY_VER=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo "[OK] Found Python $PY_VER ($PYTHON_CMD)"

if ! $PYTHON_CMD -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
    echo "[ERROR] SiteSage requires Python 3.10 or higher. Found $PY_VER."
    exit 1
fi

# 3. Check / Create Virtual Environment
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[*] Virtual environment '$VENV_DIR' not found. Creating a new one..."
    $PYTHON_CMD -m venv "$VENV_DIR" || {
        echo "[ERROR] Failed to create virtual environment."
        echo "You may need to install the venv package (e.g. sudo apt install python3-venv)."
        exit 1
    }
    echo "[OK] Virtual environment created successfully."
else
    echo "[OK] Virtual environment '$VENV_DIR' already exists."
fi

# 4. Activate Virtual Environment
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate" || {
    echo "[ERROR] Failed to activate virtual environment."
    exit 1
}
echo "[OK] Virtual environment activated."

# 5. Ensure .env exists
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "[*] Initializing .env configuration from .env.example..."
    cp ".env.example" ".env"
    echo "[OK] Created .env configuration file."
fi

# 6. Install / Verify Dependencies
echo "[*] Checking dependencies from requirements.txt..."
python -m pip install --upgrade pip >/dev/null 2>&1 || true
python -m pip install -r requirements.txt || {
    echo ""
    echo "[ERROR] Failed to install dependencies from requirements.txt."
    exit 1
}
echo "[OK] All dependencies installed and up to date."

# 7. Optional Gemini API Key Configuration
echo ""
echo "[*] Checking AI polish configuration..."

if python -c "import os, sys; from dotenv import load_dotenv; load_dotenv('.env'); k = (os.environ.get('GEMINI_API_KEY') or '').strip().lower(); sys.exit(0 if (k and not k.startswith('your_') and 'api_key' not in k and 'placeholder' not in k and len(k) >= 15) else 1)" >/dev/null 2>&1; then
    echo "[OK] Gemini API key is already configured in environment or .env."
else
    echo "[INFO] No valid Gemini API key configured."
    echo ""
    echo "======================================================================"
    echo " Would you like to enable Gemini AI-enhanced responses?"
    echo "  [1] Yes - Enter API key securely for this session"
    echo "  [2] No  - Continue with 100% deterministic evidence search"
    echo "======================================================================"
    echo ""
    read -r -p "Select an option [1=Yes, 2=No]: " AI_CHOICE
    case "$AI_CHOICE" in
        1|[yY]|[yY][eE][sS])
            echo ""
            echo "[*] Please enter your Gemini API key below (input hidden):"
            read -r -s -p "Gemini API Key: " TEMP_GEMINI_KEY
            echo ""
            if [ -n "$TEMP_GEMINI_KEY" ]; then
                export GEMINI_API_KEY="$TEMP_GEMINI_KEY"
                export AI_POLISH_ENABLED="true"
                echo "[OK] Gemini API key configured in memory for this session."
                echo "[NOTE] Key is kept in memory only and will not be written to .env, SQLite, or disk."
            else
                echo "[WARN] No API key provided. AI enhancement disabled."
                export AI_POLISH_ENABLED="false"
            fi
            ;;
        *)
            export AI_POLISH_ENABLED="false"
            echo ""
            echo "[INFO] AI enhancement disabled. SiteSage will run in 100% deterministic mode."
            ;;
    esac
fi

# 8. Launch SiteSage Application
echo ""
echo "======================================================================"
echo " Starting SiteSage Application Server..."
echo " Local URL:  http://127.0.0.1:8000"
echo " Press Ctrl+C to terminate the server."
echo "======================================================================"
echo ""

exec python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
