import yt_dlp
import os
import tempfile
import re
from config import MAX_FILE_SIZE_BYTES, SUPPORTED_DOMAINS


class CobaltError(Exception):
    pass


def detect_platform(url: str) -> str:
    mapping = {
        r"(youtube\.com|youtu\.be)": "YouTube",
        r"tiktok\.com": "TikTok",
        r"instagram\.com": "Instagram",
        r"(vk\.com|vkvideo\.ru)": "VK",
        r"(twitter\.com|x\.com)": "X / Twitter",
        r"reddit\.com": "Reddit",
        r"twitch\.tv": "Twitch",
        r"soundcloud\.com": "SoundCloud",
        r"pinterest\.com": "Pinterest",
    }
    for pattern, name in mapping.items():
        if re.search(pattern, url):
            return name
    return "Видео"


def is_supported_url(url: str) -> bool:
    return url.startswith("http")


async def fetch_download_url(url: str, audio_only: bool = False, quality: str = "max") -> dict:
    """Скачивает видео через yt-dlp и возвращает путь к файлу."""

    tmp_dir = tempfile.mkdtemp()
    out_template = os.path.join(tmp_dir, "%(title).50s.%(ext)s")

    if audio_only:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    else:
        if quality == "max":
            fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        else:
            fmt = f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][ext=mp4]/best[height<={quality}]"

        ydl_opts = {
            "format": fmt,
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "merge_output_format": "mp4",
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

            # Если аудио — ищем mp3
            if audio_only:
                filename = os.path.splitext(filename)[0] + ".mp3"

            # Найти реальный файл если имя немного другое
            if not os.path.exists(filename):
                files = os.listdir(tmp_dir)
                if files:
                    filename = os.path.join(tmp_dir, files[0])
                else:
                    raise CobaltError("Файл не найден после скачивания.")

            size = os.path.getsize(filename)
            if size > MAX_FILE_SIZE_BYTES:
                os.unlink(filename)
                os.rmdir(tmp_dir)
                return {"type": "too_large", "title": info.get("title", "Видео")}

            return {
                "type": "file",
                "path": filename,
                "filename": os.path.basename(filename),
                "title": info.get("title", "Видео"),
            }

    except yt_dlp.utils.DownloadError as e:
        err = str(e).lower()
        if "private" in err:
            raise CobaltError("Видео приватное — доступ закрыт.")
        if "not available" in err or "unavailable" in err:
            raise CobaltError("Видео недоступно (удалено или заблокировано).")
        if "sign in" in err or "login" in err:
            raise CobaltError("Видео требует авторизации.")
        if "copyright" in err:
            raise CobaltError("Видео заблокировано по авторским правам.")
        raise CobaltError(f"Не удалось скачать: {str(e)[:150]}")
    except Exception as e:
        raise CobaltError(f"Ошибка: {str(e)[:150]}")


async def download_file(url: str, filename: str):
    pass  # Не используется с yt-dlp
