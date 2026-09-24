#!/bin/bash
source ~/.zshrc 2>/dev/null

SCRIPT_DIR="$HOME/Desktop/English_Automation_v2"
RUN_ALL="$SCRIPT_DIR/run_all.py"
LOG_FILE="$SCRIPT_DIR/logs/watcher.log"

mkdir -p "$SCRIPT_DIR/logs"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }
log "🟢 Watcher iniciado"

anki_was_open=false
while true; do
    if pgrep -x "Anki" > /dev/null 2>&1; then
        if [ "$anki_was_open" = false ]; then
            log "📖 Anki detectado abierto"
            anki_was_open=true
        fi
    else
        if [ "$anki_was_open" = true ]; then
            log "🔒 Anki cerrado — corriendo pipeline..."
            anki_was_open=false
            python3 "$RUN_ALL" morning >> "$LOG_FILE" 2>&1
            if [ $? -eq 0 ]; then
                log "✅ Pipeline completado"
                osascript -e 'display notification "Pipeline de inglés completado ✅" with title "English Automation"'
            else
                log "❌ Pipeline falló"
                osascript -e 'display notification "⚠️ Algo falló, revisa el log" with title "English Automation"'
            fi
        fi
    fi
    sleep 10
done
