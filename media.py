"""Отримання аудіо: завантаження з YouTube (yt-dlp) і конвертація в WAV (ffmpeg)."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import yt_dlp


def _noop(*args, **kwargs):
    pass


def is_url(text: str) -> bool:
    return bool(re.match(r"^https?://", text.strip(), re.IGNORECASE))


def safe_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:max_len].rstrip(" .") or "audio"


def download_youtube(url: str, tmp_dir, on_status=_noop):
    """Завантажує лише аудіодоріжку. Повертає (шлях_до_файлу, назва_відео)."""
    tmp_dir = Path(tmp_dir)

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes")
            if total and done is not None:
                on_status(f"Завантаження: {done * 100 / total:.0f}%", log=False)

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    on_status("Завантаження аудіо з YouTube…")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except Exception as e:
        raise RuntimeError(
            f"Не вдалося завантажити відео: {e}\n"
            "Перевірте посилання. Якщо воно правильне, спробуйте оновити yt-dlp: "
            "pip install -U yt-dlp"
        ) from e

    if not path.exists():
        matches = list(tmp_dir.glob(f"{info.get('id', '*')}.*"))
        if not matches:
            raise RuntimeError("Завантажений файл не знайдено.")
        path = matches[0]
    return path, info.get("title") or info.get("id") or "youtube_audio"


def to_wav(src, tmp_dir) -> Path:
    """Перетворює будь-який аудіо/відео файл на моно WAV зі збереженням частоти дискретизації."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg не знайдено. Встановіть: winget install -e --id Gyan.FFmpeg.Shared "
            "і перезапустіть програму з нового термінала."
        )
    out = Path(tmp_dir) / "input.wav"
    cmd = [ffmpeg, "-y", "-i", str(src), "-vn", "-ac", "1", "-acodec", "pcm_s16le", str(out)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if result.returncode != 0 or not out.exists():
        tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        raise RuntimeError(f"ffmpeg не зміг обробити файл:\n{tail}")
    return out
