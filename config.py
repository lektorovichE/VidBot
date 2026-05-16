import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
FREE_DOWNLOADS_PER_DAY = int(os.getenv("FREE_DOWNLOADS_PER_DAY", "5"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
COBALT_API = os.getenv("COBALT_API", "https://api.cobalt.tools/")

# Telegram Stars цены
PLANS = {
    "week": {
        "label": "⚡️ 7 дней безлимит",
        "stars": 50,
        "days": 7,
        "payload": "premium_7d",
    },
    "month": {
        "label": "🔥 30 дней безлимит",
        "stars": 150,
        "days": 30,
        "payload": "premium_30d",
    },
    "forever": {
        "label": "♾️ Навсегда",
        "stars": 500,
        "days": 36500,
        "payload": "premium_forever",
    },
}

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be", "tiktok.com",
    "instagram.com", "vk.com", "vkvideo.ru",
    "twitter.com", "x.com", "reddit.com",
    "twitch.tv", "soundcloud.com", "pinterest.com",
]
