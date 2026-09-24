#!/bin/bash
# Respaldo diario de data/english.db.
#
# `english.db` está en .gitignore, así que git NO lo cubre: 3,100+ palabras y
# su historial de repasos son lo único irreemplazable del proyecto. Hasta
# ahora los únicos respaldos eran los que se hacían a mano antes de tocar algo.
#
#   scripts/backup_db.sh            respalda una vez
#   scripts/backup_db.sh install    lo agenda a diario con launchd
#   scripts/backup_db.sh uninstall  lo desagenda
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$PROJECT/data/english.db"
DEST="$PROJECT/data/backups"
LABEL="com.eddieelorza.englishos-backup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
KEEP=14

case "${1:-run}" in
uninstall)
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "respaldo diario desagendado (los archivos existentes se quedan)"
  exit 0
  ;;
install)
  mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/logs"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$PROJECT/scripts/backup_db.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <!-- 05:00. Si el Mac duerme a esa hora, launchd lo corre al despertar:
       una hora fija sin esa garantía perdería los días que no estás. -->
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>5</integer><key>Minute</key><integer>0</integer></dict>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>StandardOutPath</key><string>$PROJECT/logs/backup.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/logs/backup.log</string>
</dict>
</plist>
PLIST
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  for _ in $(seq 1 60); do
    launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 || break
    sleep 0.25
  done
  launchctl bootstrap "gui/$UID" "$PLIST"
  echo "agendado a las 05:00 · $PLIST"
  exec "$0" run
  ;;
esac

[[ -f "$DB" ]] || { echo "no existe $DB" >&2; exit 1; }
mkdir -p "$DEST"
OUT="$DEST/english-auto-$(date +%Y%m%d-%H%M%S).db"

# `.backup` y NO `cp`: con WAL activo, copiar el archivo suelto deja fuera lo
# que todavía vive en el -wal y produce una copia vieja en silencio. Ya pasó
# una vez y costó un "38 de 10" fantasma.
sqlite3 "$DB" ".backup '$OUT'"

# Verificar y consultar abre la copia, y abrirla en modo WAL le crea sus
# archivos laterales. Quedaban tirados junto a cada respaldo: basura que
# confunde al restaurar (¿cuál de los tres archivos es el respaldo?).
cleanup_sidecars() { rm -f "$OUT-wal" "$OUT-shm"; }
trap cleanup_sidecars EXIT

# Verificar antes de contar con él: un respaldo que no se abre es peor que
# ninguno, porque te hace creer que estás cubierto.
if [[ "$(sqlite3 "$OUT" 'PRAGMA integrity_check;' 2>&1 | head -1)" != "ok" ]]; then
  echo "[$(date '+%F %T')] RESPALDO CORRUPTO, descartado: $OUT" >&2
  rm -f "$OUT"
  exit 1
fi
WORDS=$(sqlite3 "$OUT" "SELECT COUNT(*) FROM words;")
REVS=$(sqlite3 "$OUT" "SELECT COUNT(*) FROM review_history;")
if [[ "$WORDS" -lt 100 ]]; then
  echo "[$(date '+%F %T')] RESPALDO SOSPECHOSO ($WORDS palabras), descartado" >&2
  rm -f "$OUT"
  exit 1
fi

# Rota SOLO los automáticos: los `english-pre-*` marcan hitos (cut-over,
# apagado de Notion) y no se tocan nunca.
ls -1t "$DEST"/english-auto-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old" "$old-wal" "$old-shm"
  echo "[$(date '+%F %T')] rotado: $(basename "$old")"
done

echo "[$(date '+%F %T')] ok: $(basename "$OUT") · $WORDS palabras · $REVS repasos · $(du -h "$OUT" | cut -f1)"
