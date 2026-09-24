"""Shadowing sobre vídeo de YouTube (M20).

Pegas una URL, se baja **sólo el audio**, se transcribe con marcas de tiempo y
te queda una lista de líneas para repetir una por una.

## Lo que se midió antes de construir esto

Sobre una canción real de 3.4 min, con `faster-whisper`:

| configuración | palabras | confianza |
|---|---|---|
| `small` **con** VAD | 31 | -0.78 |
| `small` **sin** VAD | **282** | **-0.22** |
| `medium` sin VAD | 295 | -0.38 |

El `vad_filter` está pensado para alguien hablando a un micrófono; con música
decide que la canción entera es "sin habla" y se la come. Apagado, la
transcripción pasa de inservible a fiable. Y `medium` **no compensa**: más
repeticiones, peor confianza y cinco veces más lento que `small`.

No hace falta ffmpeg: se pide un formato de sólo-audio (`m4a`/`webm`) que PyAV
—que ya venía con faster-whisper— decodifica directamente.

## Lo que NO hace

No baja vídeo, no guarda imagen y no republica nada: el audio y su
transcripción se quedan en el disco de Eddie para estudiar. Bajar audio de
YouTube va contra sus términos de servicio; queda dicho en el README.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db, speaking  # noqa: E402

MEDIA_DIR = BASE / "data" / "media" / "shadow"

# Media hora. Transcribir va a ~0.17x, así que 30 min de audio son ~5 min de
# espera: más allá de eso la pantalla parecería colgada sin remedio.
MAX_SECONDS = 30 * 60

# Una línea de shadowing tiene que caber en una respiración. Whisper devuelve
# tramos de ~7 s de media, pero suelta alguno de 20 s que es imposible repetir.
MAX_LINE_SECONDS = 14.0

_URL_RE = re.compile(r"^https?://", re.I)


class DownloadError(RuntimeError):
    pass


def _check_url(url: str) -> str:
    url = (url or "").strip()
    if not _URL_RE.match(url):
        raise ValueError("La URL tiene que empezar por http:// o https://")
    return url


def probe(url: str) -> dict:
    """Metadatos sin bajar nada. Sirve para negarse pronto y con motivo."""
    import yt_dlp
    url = _check_url(url)
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                               "skip_download": True}) as y:
            info = y.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 — red, vídeo privado, geobloqueo…
        raise DownloadError(f"No pude leer ese vídeo: {exc}") from exc
    return {"video_id": info.get("id"), "title": info.get("title"),
            "channel": info.get("uploader"),
            "seconds": float(info.get("duration") or 0)}


def _download(url: str, video_id: str) -> Path:
    import yt_dlp
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    target = MEDIA_DIR / f"{video_id}.m4a"
    if target.exists():
        return target
    opts = {"format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": str(MEDIA_DIR / f"{video_id}.%(ext)s"),
            "quiet": True, "no_warnings": True, "noprogress": True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.download([url])
    except Exception as exc:  # noqa: BLE001
        raise DownloadError(f"No pude bajar el audio: {exc}") from exc
    if target.exists():
        return target
    # Si el mejor audio no era m4a, yt-dlp deja otra extensión.
    for candidate in MEDIA_DIR.glob(f"{video_id}.*"):
        return candidate
    raise DownloadError("La descarga no dejó ningún archivo")


def split_long(segments: list, limit: float = MAX_LINE_SECONDS) -> list:
    """Parte los tramos que no caben en una respiración.

    Se corta por palabras y se reparte el tiempo proporcionalmente: no es
    exacto al milisegundo, pero un tramo de 20 s es imposible de repetir y una
    marca con medio segundo de deriva no molesta a nadie.
    """
    out = []
    for s in segments:
        span = s["end"] - s["start"]
        if span <= limit:
            out.append(s)
            continue
        words = s["text"].split()
        pieces = max(2, int(span // limit) + 1)
        size = max(1, len(words) // pieces)
        chunks = [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
        chunks = [c for c in chunks if c]
        step = span / max(1, len(chunks))
        for i, chunk in enumerate(chunks):
            out.append({"start": round(s["start"] + i * step, 2),
                        "end": round(s["start"] + (i + 1) * step, 2),
                        "text": chunk, "confidence": s.get("confidence")})
    return out


def create(conn: sqlite3.Connection, url: str) -> dict:
    """Baja, transcribe y guarda. Idempotente por vídeo."""
    meta = probe(url)
    if not meta["video_id"]:
        raise DownloadError("Ese enlace no parece un vídeo")
    if meta["seconds"] > MAX_SECONDS:
        raise ValueError(
            f"Ese vídeo dura {meta['seconds'] / 60:.0f} min; el tope son "
            f"{MAX_SECONDS // 60}. Transcribirlo tardaría demasiado.")

    existing = conn.execute("SELECT id FROM shadow_sessions WHERE video_id=?",
                            (meta["video_id"],)).fetchone()
    if existing:
        return get(conn, existing["id"])

    audio = _download(url, meta["video_id"])
    # vad=False a propósito: ver el docstring del módulo.
    heard = speaking.transcribe(audio, vad=False, segments_out=True)
    lines = split_long(heard.get("segments") or [])
    if not lines:
        raise ValueError("No se transcribió nada — ¿el vídeo tiene voz?")

    confs = [ln["confidence"] for ln in lines if ln.get("confidence") is not None]
    cur = conn.execute(
        "INSERT INTO shadow_sessions (url, video_id, title, channel, seconds, "
        "audio_path, confidence, date, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (url, meta["video_id"], meta["title"], meta["channel"],
         heard["duration_seconds"], f"shadow/{audio.name}",
         round(sum(confs) / len(confs), 3) if confs else None,
         db.study_day(), db.now_iso(), db.now_iso()))
    sid = cur.lastrowid
    for i, ln in enumerate(lines):
        conn.execute(
            "INSERT INTO shadow_lines (session_id, idx, start_s, end_s, text, "
            "confidence) VALUES (?,?,?,?,?,?)",
            (sid, i, ln["start"], ln["end"], ln["text"], ln.get("confidence")))
    conn.commit()
    return get(conn, sid)


def get(conn: sqlite3.Connection, session_id: int) -> dict:
    row = conn.execute("SELECT * FROM shadow_sessions WHERE id=?",
                       (session_id,)).fetchone()
    if row is None:
        raise ValueError("esa sesión no existe")
    lines = [dict(r) for r in conn.execute(
        "SELECT id, idx, start_s, end_s, text, confidence, done_at "
        "FROM shadow_lines WHERE session_id=? ORDER BY idx", (session_id,))]
    return {**dict(row), "lines": lines,
            "done": sum(1 for ln in lines if ln["done_at"])}


def recent(conn: sqlite3.Connection, limit: int = 20) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT s.id, s.title, s.channel, s.seconds, s.confidence, s.date, "
        "  (SELECT COUNT(*) FROM shadow_lines l WHERE l.session_id=s.id) AS lines, "
        "  (SELECT COUNT(*) FROM shadow_lines l WHERE l.session_id=s.id "
        "     AND l.done_at IS NOT NULL) AS done "
        "FROM shadow_sessions s ORDER BY s.id DESC LIMIT ?", (limit,))]


def mark(conn: sqlite3.Connection, line_id: int, done: bool = True) -> dict:
    conn.execute("UPDATE shadow_lines SET done_at=? WHERE id=?",
                 (db.now_iso() if done else None, line_id))
    conn.commit()
    row = conn.execute("SELECT session_id FROM shadow_lines WHERE id=?",
                       (line_id,)).fetchone()
    if row is None:
        raise ValueError("esa línea no existe")
    return get(conn, row["session_id"])
