import aiohttp
import os
import tempfile
import re
from config import COBALT_API, MAX_FILE_SIZE_BYTES, SUPPORTED_DOMAINS


class CobaltError(Exception):
    pass


ERROR_MAP = {
    "error.api.url.invalid": "Неверная ссылка. Проверь URL и попробуй снова.",
    "error.api.url.unsupported": "Эта платформа не поддерживается.",
    "error.api.content.unavailable": "Видео недоступно (удалено или приватное).",
    "error.api.content.age_restricted": "Видео с возрастным ограничением — не могу скачать.",
    "error.api.content.private": "Видео приватное — доступ закрыт.",
    "error.api.rate_exceeded": "Слишком много запросов. Подожди немного.",
    "error.api.unreachable": "Сервис временно недоступен. Попробуй через минуту.",
}


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
    return "Unknown"


def is_supported_url(url: str) -> bool:
    return any(d in url for d in SUPPORTED_DOMAINS)


async def fetch_download_url(url: str, audio_only: bool = False, quality: str = "max") -> dict:
    """
    Returns dict:
        {"type": "direct", "url": "...", "filename": "..."}
        {"type": "picker", "items": [...], "audio": "..."}
    Raises CobaltError on failure.
    """
    body = {"url": url}

    if audio_only:
        body["downloadMode"] = "audio"
    else:
        body["downloadMode"] = "auto"

    if quality != "max":
        body["videoQuality"] = quality

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                COBALT_API, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as e:
            raise CobaltError(f"Ошибка подключения к сервису: {e}")

    status = data.get("status", "")

    if status == "error":
        code = data.get("error", {}).get("code", "")
        msg = ERROR_MAP.get(code, f"Ошибка: {code or 'неизвестная'}")
        raise CobaltError(msg)

    if status in ("redirect", "tunnel"):
        return {
            "type": "direct",
            "url": data["url"],
            "filename": data.get("filename", "video"),
        }

    if status == "picker":
        return {
            "type": "picker",
            "items": data.get("picker", []),
            "audio": data.get("audio"),
        }

    raise CobaltError("Неожиданный ответ от сервиса. Попробуй ещё раз.")


async def download_file(url: str, filename: str) -> str | None:
    """
    Downloads file to a temp path. Returns path or None if too large.
    Caller must delete the file after use.
    """
    tmp = tempfile.mktemp(suffix="_" + filename[-20:])
    downloaded = 0

    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            # Check Content-Length if available
            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > MAX_FILE_SIZE_BYTES:
                return None

            with open(tmp, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 64):
                    downloaded += len(chunk)
                    if downloaded > MAX_FILE_SIZE_BYTES:
                        f.close()
                        os.unlink(tmp)
                        return None
                    f.write(chunk)

    return tmp
