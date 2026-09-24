#!/bin/bash
# English OS como app local (ADR-013, opción A).
#
#   scripts/install_app.sh            instala y arranca
#   scripts/install_app.sh uninstall  lo quita todo
#
# No usa sudo y no toca nada fuera de tu usuario: el agente va a
# ~/Library/LaunchAgents y el icono a ~/Applications.
set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.eddieelorza.englishos"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
APP="$HOME/Applications/English OS.app"
PORT=8770

if [[ "${1:-install}" == "uninstall" ]]; then
  launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  rm -rf "$APP"
  echo "desinstalado. El proyecto y data/english.db siguen intactos."
  exit 0
fi

# El build tiene que existir ANTES de arrancar: si no, el servidor levanta y
# la app devuelve 503 sin decir por qué desde el navegador.
if [[ ! -f "$PROJECT/frontend/dist/index.html" ]]; then
  echo "compilando el frontend..."
  npm run build --prefix "$PROJECT/frontend"
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Applications" "$PROJECT/logs"
sed "s|__PROJECT__|$PROJECT|g" "$PROJECT/scripts/englishos.plist.template" > "$PLIST"

# bootout antes de bootstrap: recargar sin descargar deja la definición vieja.
# Y hay que ESPERAR a que se vaya: bootout es asíncrono, y un bootstrap
# encima del servicio que aún se está apagando falla con "Input/output error
# 5", un mensaje que no dice nada de lo que realmente pasa.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
for _ in $(seq 1 60); do
  launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 || break
  sleep 0.25
done
if ! launchctl bootstrap "gui/$UID" "$PLIST"; then
  echo "no se pudo cargar el agente. ¿Sigue vivo de antes?" >&2
  echo "  launchctl print gui/$UID/$LABEL" >&2
  exit 1
fi

# ── El icono del Dock ────────────────────────────────────────────────────
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>English OS</string>
  <key>CFBundleDisplayName</key><string>English OS</string>
  <key>CFBundleIdentifier</key><string>$LABEL.launcher</string>
  <key>CFBundleExecutable</key><string>englishos</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/englishos" <<LAUNCHER
#!/bin/bash
# Abre la app. Si el agente no está corriendo (lo paraste, o el arranque
# falló), lo levanta y espera a que responda en vez de abrir una pestaña
# rota: un navegador con "no se puede conectar" no dice qué hacer.
launchctl kickstart "gui/\$UID/$LABEL" 2>/dev/null || true
for _ in \$(seq 1 120); do
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/today" 2>/dev/null; then
    open "http://127.0.0.1:$PORT/"
    exit 0
  fi
  sleep 0.25
done
osascript -e 'display alert "English OS no arrancó" message "Mira logs/englishos.err.log en el proyecto."'
exit 1
LAUNCHER
chmod +x "$APP/Contents/MacOS/englishos"

# Arranca en ~1.2 s medido, pero se espera hasta 30: un disco frío o una
# migración pendiente tardan más, y decir "listo" sin haber comprobado nada
# es peor que esperar.
echo "esperando al servidor..."
up=0
for _ in $(seq 1 120); do
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/today" 2>/dev/null; then
    up=1; break
  fi
  sleep 0.25
done

if [[ $up -eq 0 ]]; then
  echo
  echo "el agente está instalado pero NO respondió en 30 s." >&2
  echo "mira $PROJECT/logs/englishos.err.log" >&2
  tail -5 "$PROJECT/logs/englishos.err.log" 2>/dev/null | sed 's/^/  /' >&2
  exit 1
fi

echo
echo "listo:"
echo "  app        http://127.0.0.1:$PORT/"
echo "  icono      $APP  (arrástralo al Dock)"
echo "  agente     $PLIST"
echo "  parar      launchctl bootout gui/$UID/$LABEL"
echo "  arrancar   launchctl bootstrap gui/$UID $PLIST"
