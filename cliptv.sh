#!/usr/bin/env bash
# Lanceur cliptv pour Mac et Linux : installe ce qui manque puis ouvre l'app.
#   Mac   : double-clic sur « cliptv-mac.command »
#   Linux : ./cliptv.sh   (ou : bash cliptv.sh)
set -euo pipefail
cd "$(dirname "$0")"
echo
echo "  === cliptv ==="
echo

find_python() {
  for c in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$c"; return 0
    fi
  done
  return 1
}

need_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Installe d'abord Homebrew (https://brew.sh) puis relance ce lanceur."
    exit 1
  fi
}

PY="$(find_python || true)"
if [ -z "$PY" ]; then
  if [ "$(uname)" = "Darwin" ]; then
    need_brew; echo "Installation de Python…"; brew install python@3.12
    PY="$(find_python || true)"
  else
    echo "Python 3.10 ou plus récent introuvable. Installe-le puis relance, par exemple :"
    echo "  sudo apt install python3 python3-venv      (Debian / Ubuntu)"
    echo "  sudo dnf install python3                   (Fedora)"
    exit 1
  fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  if [ "$(uname)" = "Darwin" ]; then
    need_brew; echo "Installation de ffmpeg…"; brew install ffmpeg
  else
    echo "ffmpeg introuvable. Installe-le puis relance, par exemple :"
    echo "  sudo apt install ffmpeg        (Debian / Ubuntu)"
    echo "  sudo dnf install ffmpeg        (Fedora, dépôt RPM Fusion)"
    exit 1
  fi
fi

if [ ! -x .venv/bin/python ]; then
  echo "Création de l'environnement Python…"
  if ! "$PY" -m venv .venv; then
    echo "Échec : sur Debian/Ubuntu, installe le module venv : sudo apt install python3-venv"
    rm -rf .venv
    exit 1
  fi
fi
echo "Installation / mise à jour des dépendances (la première fois : quelques minutes)…"
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[all]"

exec .venv/bin/python -m clipbot app --host 0.0.0.0 --open "$@"
