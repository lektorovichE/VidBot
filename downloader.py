import yt_dlp
import aiohttp
import os
import tempfile
import re
from config import MAX_FILE_SIZE_BYTES

COBALT_INSTANCES = [
    "https://cobalt.tools/",
    "https://co.wuk.sh/",
    "https://cobalt.api.timelessnesses.me/",
]


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
    }
    for pattern, name in mapping.items():
        if re.search(pattern, url):
            return name
    return "Видео"


def is_youtube(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url))


def is_supported_url(url: str) -> bool:
    return url.startswith("http")


async def fetch_youtube_cobalt(url: str, audio_only: bool = False) -> dict:
    """Пробуем разные cobalt инстансы для YouTube."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = {
        "url": url,
        "downloadMode": "audio" if audio_only else "auto",
        "videoQuality": "1080",
    }

    async with aiohttp.ClientSession() as session:
        for instance in COBALT_INSTANCES:
            try:
                async with session.post(
                    instance,
                    json=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                    status = data.get("status", "")

                    if status in ("redirect", "tunnel"):
                        return {
                            "type": "youtube_links",
                            "title": "YouTube видео",
                            "options": [{"quality": "Лучшее качество", "url": data["url"], "ext": "mp4"}],
                            "audio_url": None,
                        }
                    if status == "picker":
                        options = []
                        for item in data.get("picker", [])[:5]:
                            options.append({
                                "quality": item.get("quality", "Скачать"),
                                "url": item["url"],
                                "ext": "mp4",
                            })
                        return {
                            "type": "youtube_links",
                            "title": "YouTube видео",
                            "options": options,
                            "audio_url": data.get("audio"),
                        }
            except Exception:
                continue

    raise CobaltError("YouTube временно недоступен. Попробуй позже.")


async def fetch_download_url(url: str, audio_only: bool = False, quality: str = "max") -> dict:
    # YouTube — через cobalt
    if is_youtube(url):
        return await fetch_youtube_cobalt(url, audio_only=audio_only)

    # Остальные платформы — через yt-dlp
    tmp_dir = tempfile.mkdtemp()
    out_template = os.path.join(tmp_dir, "%(title).50s.%(ext)s")

    if audio_only:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "no_check_certificates": True,
        }
    else:
        fmt = "best[ext=mp4]/best" if quality == "max" else f"best[height<={quality}][ext=mp4]/best[height<={quality}]/best"
        ydl_opts = {
            "format": fmt,
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "no_check_certificates": True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

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
        raise CobaltError(f"Не удалось скачать: {str(e)[:150]}")
    except Exception as e:
        raise CobaltError(f"Ошибка: {str(e)[:150]}")


async def download_file(url: str, filename: str):
    pass
