#!/bin/bash
# install.sh - richtet kushim auf macOS (Apple Silicon) ein. Gegenstück zu install.ps1 (Windows).
#
# Aufruf im Projektordner:
#     ./install.sh            (oder: bash install.sh)
#
# Schalter:
#     --check           Nur prüfen, was fehlt. Ändert nichts, lädt nichts.
#     --no-prompt       Keine Rückfragen (der Vault wird dann NICHT angelegt).
#     --skip-shortcuts  Keine Startdateien (kushim.command, kushim NOTAUS.command) auf dem Schreibtisch.
#     --skip-path       Den Befehl `kushim` NICHT als Link in ~/.local/bin anlegen.
#
# Wiederholbar: Was schon da und geprüft ist, wird übersprungen.
# Netzwerk nur während der Installation und nur zu: pypi.org (Python-Pakete), github.com (Wake-Word-Modelle),
# huggingface.co (Whisper, Stimme Kokoro "Martin"). Danach arbeitet kushim offline (außer Claude Code selbst).
# Unterschiede zu Windows: keine NVIDIA-GPU/CUDA. Whisper und die Stimme laufen auf dem Prozessor (Apple Silicon).
# Der Vault-Schlüssel liegt im macOS-Schlüsselbund. Den legt NUR du an (Rückfrage am Ende).
set -euo pipefail

CHECK=0; NOPROMPT=0; SKIPSHORTCUTS=0; SKIPPATH=0
for a in "$@"; do
    case "$a" in
        --check) CHECK=1 ;;
        --no-prompt) NOPROMPT=1 ;;
        --skip-shortcuts) SKIPSHORTCUTS=1 ;;
        --skip-path) SKIPPATH=1 ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "Unbekannter Schalter: $a" >&2; exit 2 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")" && pwd -P)"
cd "$ROOT"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
KVENV="$ROOT/tools/kokoro/venv"
KPY="$KVENV/bin/python"
KREQ="$ROOT/scripts/kokoro-requirements-macos.txt"
PROBLEMS=()

step()    { printf '\n\033[36m== %s\033[0m\n' "$1"; }
ok()      { printf '   \033[32mok:\033[0m %s\n' "$1"; }
info()    { printf '   %s\n' "$1"; }
warn()    { printf '   \033[33mACHTUNG:\033[0m %s\n' "$1"; PROBLEMS+=("$1"); }
missing() { printf '   \033[33mFEHLT:\033[0m %s\n' "$1"; PROBLEMS+=("Fehlt: $1"); }
ask() {
    [ "$NOPROMPT" = 1 ] || [ "$CHECK" = 1 ] && return 1
    local a; read -r -p "$1 (j/N) " a || return 1
    [[ "$a" =~ ^(j|ja|y|yes)$ ]]
}

# ---------------------------------------------------------------- 1. Voraussetzungen
step "1/8 Voraussetzungen"
if [ "$(uname -s)" != "Darwin" ]; then
    warn "Dieses Skript ist für macOS. Unter Windows: install.ps1."
fi
[ "$(uname -m)" = "arm64" ] && ok "Apple Silicon ($(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo arm64))" \
    || warn "Kein Apple Silicon: die Sprachausgabe-Pakete (scripts/kokoro-requirements-macos.txt) gibt es nur für arm64."
SYSPY=""
for cand in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12; do
    if command -v "$cand" >/dev/null 2>&1; then
        v="$("$cand" -c 'import sys;print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
        if [ "$v" = "3.12" ]; then SYSPY="$(command -v "$cand")"; ok "Python 3.12 ($SYSPY)"; break; fi
    fi
done
if [ -z "$SYSPY" ] && [ ! -x "$PY" ]; then
    warn "Python 3.12 nicht gefunden. Installieren: brew install python@3.12 (oder von python.org), dann erneut starten."
    [ "$CHECK" = 1 ] || exit 1
fi
FREE_GB="$(df -g "$ROOT" | awk 'NR==2 {print $4}')"
if [ "${FREE_GB:-0}" -lt 10 ]; then warn "Nur ${FREE_GB} GB frei, empfohlen sind mindestens 10 GB."; else ok "${FREE_GB} GB frei"; fi
if command -v claude >/dev/null 2>&1; then ok "Claude Code: $(claude --version 2>/dev/null | head -1)"; else warn "Claude Code nicht gefunden (installieren und 'claude auth login')."; fi

# ---------------------------------------------------------------- 2. venv
step "2/8 Python-Umgebung (.venv)"
if [ -x "$PY" ]; then ok ".venv vorhanden"
elif [ "$CHECK" = 1 ]; then missing ".venv"
else
    info "lege .venv an ..."
    "$SYSPY" -m venv "$VENV"
    ok ".venv angelegt"
fi

# ---------------------------------------------------------------- 3. Pakete
step "3/8 Python-Pakete (feste Versionen, von pypi.org)"
if [ -x "$PY" ]; then
    if "$PY" -c "import faster_whisper, sherpa_onnx, sentencepiece, sounddevice, openwakeword, sqlcipher3, keyring" 2>/dev/null; then
        ok "alle Pakete importierbar"
    elif [ "$CHECK" = 1 ]; then missing "Python-Pakete"
    else
        info "installiere Pakete (kann einige Minuten dauern) ..."
        "$PY" -m pip install --timeout 120 --retries 10 --upgrade pip
        "$PY" -m pip install --timeout 120 --retries 10 -e ".[dev,voice]"
        # openWakeWord ohne Abhängigkeiten: tflite-runtime wird nicht gebraucht, wir nutzen ONNX.
        "$PY" -m pip install --timeout 120 --retries 10 "openwakeword==0.6.0" --no-deps
        ok "Pakete installiert"
    fi
fi

# ---------------------------------------------------------------- 4. Sprachausgabe
# Kokoro "Martin" läuft als eigener Prozess mit eigenem venv (onnxruntime für den Prozessor; macOS hat keine CUDA).
# Nur Wheels, feste Versionen, jede Datei per SHA-256 geprüft (--require-hashes).
step "4/8 Sprachausgabe (Kokoro, eigenes venv)"
kokoro_ok=0
if [ -x "$KPY" ] && "$KPY" -I -c "import onnxruntime, kokoro_onnx, espeakng_loader" 2>/dev/null; then kokoro_ok=1; fi
if [ "$kokoro_ok" = 1 ]; then ok "tools/kokoro/venv vorhanden (onnxruntime, kokoro-onnx, espeak-ng)"
elif [ "$CHECK" = 1 ]; then missing "Sprachausgabe-venv (tools/kokoro/venv)"
else
    if [ ! -x "$KPY" ]; then
        [ -n "$SYSPY" ] || { echo "Die Sprachausgabe braucht Python 3.12." >&2; exit 1; }
        info "lege tools/kokoro/venv an ..."
        mkdir -p "$(dirname "$KVENV")"
        "$SYSPY" -m venv "$KVENV"
    fi
    info "installiere Pakete der Sprachausgabe ..."
    "$KPY" -m pip install --timeout 120 --retries 10 --no-deps --require-hashes --only-binary=:all: -r "$KREQ"
    ok "Sprachausgabe-venv bereit"
fi

# ---------------------------------------------------------------- 5. Modelle
step "5/8 Modelle: Whisper, Stimme, Wake Words (geprüft per SHA-256)"
if [ -x "$PY" ]; then
    if [ "$CHECK" = 1 ]; then "$PY" scripts/fetch_models.py --check || missing "Modelle (scripts/fetch_models.py ausführen)"
    else "$PY" scripts/fetch_models.py; fi
fi

# ---------------------------------------------------------------- 6. Icon
step "6/8 Logo und Icon"
if [ -f "$ROOT/assets/kushim.ico" ]; then ok "Icon vorhanden"
elif [ "$CHECK" = 1 ]; then missing "assets/kushim.ico"
elif [ -x "$PY" ]; then "$PY" scripts/make_icon.py && ok "Icon erzeugt"; fi

# ---------------------------------------------------------------- 7. Startdateien und Befehl
step "7/8 Startdateien und Befehl 'kushim'"
chmod +x "$ROOT/bin/kushim"
if [ "$SKIPSHORTCUTS" = 1 ]; then info "übersprungen (--skip-shortcuts)"
elif [ "$CHECK" = 1 ]; then info "(im Check-Modus nicht angelegt)"
else
    DESK="$HOME/Desktop"
    if [ -d "$DESK" ]; then
        q="$(printf '%q' "$ROOT")"
        printf '#!/bin/sh\n# kushim starten: Claude Code, Zuhören und Oberfläche\ncd %s && exec ./bin/kushim start\n' "$q" > "$DESK/kushim.command"
        printf '#!/bin/sh\n# kushim NOTAUS\ncd %s && exec ./bin/kushim kill\n' "$q" > "$DESK/kushim NOTAUS.command"
        chmod 755 "$DESK/kushim.command" "$DESK/kushim NOTAUS.command"
        ok "kushim.command und 'kushim NOTAUS.command' auf dem Schreibtisch (Doppelklick öffnet Terminal)"
    else info "kein Schreibtisch-Ordner gefunden, übersprungen"; fi
fi
if [ "$SKIPPATH" = 1 ]; then info "Befehl 'kushim' übersprungen (--skip-path)"
elif [ "$CHECK" = 1 ]; then
    [ -L "$HOME/.local/bin/kushim" ] && ok "~/.local/bin/kushim vorhanden" || info "~/.local/bin/kushim fehlt"
else
    mkdir -p "$HOME/.local/bin"
    ln -sfn "$ROOT/bin/kushim" "$HOME/.local/bin/kushim"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ok "Befehl 'kushim' (~/.local/bin/kushim)" ;;
        *) ok "~/.local/bin/kushim angelegt"; info "~/.local/bin ist nicht im PATH: in ~/.zshrc ergänzen: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
fi

# ---------------------------------------------------------------- 8. Vault
step "8/8 Vault (nur du)"
if [ -x "$PY" ]; then
    if "$PY" -m kushim.cli memory info >/dev/null 2>&1; then ok "Vault vorhanden"
    elif [ "$CHECK" = 1 ]; then missing "Vault (kushim memory init)"
    elif ask "Vault jetzt anlegen? Das erzeugt einen Schlüssel im macOS-Schlüsselbund"; then
        "$PY" -m kushim.cli memory init
        echo
        printf '   \033[33mWICHTIG:\033[0m Sichere jetzt den Schlüssel in deinem Passwortmanager:\n'
        echo "   ./bin/kushim key export"
        echo "   (Ohne Schlüssel sind die Daten bei einem neuen Mac verloren.)"
    else info "Später: ./bin/kushim memory init"; fi
    "$PY" -m kushim.cli doctor || true
fi

echo
if [ "${#PROBLEMS[@]}" -gt 0 ]; then
    printf '\033[33mFertig mit Hinweisen:\033[0m\n'
    for p in "${PROBLEMS[@]}"; do printf '  - %s\n' "$p"; done
else printf '\033[32mFertig.\033[0m\n'; fi
echo "Nächste Schritte stehen in der README (Abschnitt 'macOS')."
echo "Beim ersten Start fragt macOS, ob Terminal das Mikrofon benutzen darf: erlauben."
