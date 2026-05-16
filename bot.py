import asyncio
import os
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
    BufferedInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database as db
from downloader import (
    fetch_download_url, download_file,
    detect_platform, is_supported_url, CobaltError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


# ── KEYBOARDS ────────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚡️ Premium", callback_data="show_premium")
    b.button(text="❓ Помощь", callback_data="help")
    b.adjust(2)
    return b.as_markup()


def kb_premium() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, plan in config.PLANS.items():
        b.button(
            text=f"{plan['label']} — ⭐️ {plan['stars']}",
            callback_data=f"buy_{key}",
        )
    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def kb_audio_toggle(audio_only: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    label = "🎵 Только аудио: ВКЛ" if audio_only else "🎵 Только аудио: ВЫКЛ"
    b.button(text=label, callback_data=f"toggle_audio_{1 if not audio_only else 0}")
    b.adjust(1)
    return b.as_markup()


def kb_picker(items: list, audio_url: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, item in enumerate(items[:8]):
        label = item.get("quality") or item.get("type") or f"Вариант {i+1}"
        b.button(text=f"📥 {label}", url=item["url"])
    if audio_url:
        b.button(text="🎵 Только аудио", url=audio_url)
    b.adjust(2)
    return b.as_markup()


# ── HELPERS ───────────────────────────────────────────────────────────────────

async def check_limit(user_id: int) -> tuple[bool, int]:
    """Returns (can_download, downloads_left)"""
    if await db.is_premium(user_id):
        return True, 999
    await db.reset_daily_if_needed(user_id)
    used = await db.get_downloads_today(user_id)
    left = config.FREE_DOWNLOADS_PER_DAY - used
    return left > 0, max(left, 0)


async def send_premium_upsell(message: Message, downloads_left: int):
    text = (
        f"😔 Ты использовал все <b>{config.FREE_DOWNLOADS_PER_DAY} бесплатных</b> скачиваний на сегодня.\n\n"
        "🔥 <b>Premium</b> даёт безлимитные скачивания без ожиданий!\n\n"
        "Выбери план:"
    )
    await message.answer(text, reply_markup=kb_premium(), parse_mode=ParseMode.HTML)


# ── START / HELP ──────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    await db.get_or_create_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    premium = await db.is_premium(msg.from_user.id)
    await db.reset_daily_if_needed(msg.from_user.id)
    used = await db.get_downloads_today(msg.from_user.id)
    left = config.FREE_DOWNLOADS_PER_DAY - used

    status = "⭐️ <b>Premium</b>" if premium else f"🆓 Бесплатно: <b>{left}/{config.FREE_DOWNLOADS_PER_DAY}</b> сегодня"

    text = (
        f"👋 Привет, <b>{msg.from_user.first_name}</b>!\n\n"
        "Я скачиваю видео без водяных знаков с:\n"
        "▸ YouTube · TikTok · Instagram · VK\n"
        "▸ Twitter/X · Reddit · Twitch · и ещё 20+\n\n"
        "📎 <b>Просто отправь мне ссылку</b> — и всё!\n\n"
        f"📊 Статус: {status}"
    )
    await msg.answer(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "help")
async def cb_help(cq: CallbackQuery):
    text = (
        "❓ <b>Как пользоваться:</b>\n\n"
        "1. Скопируй ссылку на видео\n"
        "2. Отправь её мне в чат\n"
        "3. Получи файл без водяного знака!\n\n"
        "🎵 <b>Только аудио</b> — добавь перед ссылкой: <code>audio </code>\n"
        "Пример: <code>audio https://youtu.be/xxx</code>\n\n"
        "📋 <b>Поддерживаемые платформы:</b>\n"
        "YouTube, TikTok, Instagram, VK, Twitter/X,\n"
        "Reddit, Twitch, SoundCloud, Pinterest и другие.\n\n"
        f"🆓 Бесплатно: <b>{config.FREE_DOWNLOADS_PER_DAY} видео/день</b>\n"
        "⭐️ Premium: безлимит + приоритет"
    )
    await cq.message.edit_text(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
    await cq.answer()


@dp.callback_query(F.data == "back_main")
async def cb_back(cq: CallbackQuery):
    await cq.message.edit_text(
        "Отправь мне ссылку на видео 👇",
        reply_markup=kb_main(),
    )
    await cq.answer()


# ── PREMIUM FLOW ──────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "show_premium")
async def cb_show_premium(cq: CallbackQuery):
    premium = await db.is_premium(cq.from_user.id)
    if premium:
        await cq.answer("У тебя уже есть Premium! 🎉", show_alert=True)
        return

    text = (
        "⭐️ <b>VidBot Premium</b>\n\n"
        "✅ Безлимитные скачивания\n"
        "✅ Максимальное качество (4K)\n"
        "✅ Без ожиданий\n"
        "✅ Поддержка 20+ платформ\n\n"
        "Оплата через Telegram Stars — быстро и безопасно:"
    )
    await cq.message.edit_text(text, reply_markup=kb_premium(), parse_mode=ParseMode.HTML)
    await cq.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def cb_buy(cq: CallbackQuery):
    plan_key = cq.data.split("_", 1)[1]
    plan = config.PLANS.get(plan_key)
    if not plan:
        await cq.answer("Неизвестный план.", show_alert=True)
        return

    await bot.send_invoice(
        chat_id=cq.from_user.id,
        title=f"VidBot Premium — {plan['label']}",
        description=f"Безлимитное скачивание видео без водяных знаков на {plan['days']} дней.",
        payload=plan["payload"],
        currency="XTR",
        prices=[LabeledPrice(label=plan["label"], amount=plan["stars"])],
    )
    await cq.answer()


@dp.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    await pcq.answer(ok=True)


@dp.message(F.successful_payment)
async def on_payment(msg: Message):
    payload = msg.successful_payment.invoice_payload
    stars = msg.successful_payment.total_amount

    plan = next((p for p in config.PLANS.values() if p["payload"] == payload), None)
    if not plan:
        return

    await db.activate_premium(msg.from_user.id, plan["days"])
    await db.log_payment(msg.from_user.id, stars, payload)

    days_label = "навсегда" if plan["days"] > 1000 else f"на {plan['days']} дней"
    await msg.answer(
        f"🎉 <b>Premium активирован {days_label}!</b>\n\n"
        "Теперь скачивай без ограничений — просто отправляй ссылки 🚀",
        parse_mode=ParseMode.HTML,
    )


# ── DOWNLOAD FLOW ─────────────────────────────────────────────────────────────

@dp.message(F.text)
async def handle_url(msg: Message):
    await db.get_or_create_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")

    raw = msg.text.strip()

    # Audio prefix
    audio_only = False
    if raw.lower().startswith("audio "):
        audio_only = True
        raw = raw[6:].strip()

    # Validate URL
    if not raw.startswith("http"):
        await msg.answer(
            "📎 Отправь мне ссылку на видео.\n"
            "Например: <code>https://youtu.be/dQw4w9WgXcQ</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if not is_supported_url(raw):
        await msg.answer(
            "❌ Эта платформа не поддерживается.\n\n"
            "Поддерживаю: YouTube, TikTok, Instagram, VK, Twitter/X, Reddit, Twitch и другие."
        )
        return

    # Check daily limit
    can_dl, left = await check_limit(msg.from_user.id)
    if not can_dl:
        await send_premium_upsell(msg, left)
        return

    platform = detect_platform(raw)
    status_msg = await msg.answer(f"⏳ Скачиваю с {platform}...")

    try:
        result = await fetch_download_url(raw, audio_only=audio_only)
    except CobaltError as e:
        await status_msg.edit_text(f"❌ {e}")
        await db.log_download(msg.from_user.id, raw, platform, "error")
        return

    await db.increment_downloads(msg.from_user.id)
    await db.log_download(msg.from_user.id, raw, platform, "ok")

    if result["type"] == "picker":
        await status_msg.edit_text(
            f"🎬 Выбери качество для скачивания ({platform}):",
            reply_markup=kb_picker(result["items"], result.get("audio")),
        )
        return

    # Direct download — try to send as file
    url = result["url"]
    filename = result["filename"]

    await status_msg.edit_text("📥 Загружаю файл...")

    try:
        filepath = await download_file(url, filename)
    except Exception as e:
        log.error(f"Download error: {e}")
        filepath = None

    if filepath is None:
        # File too large — send link instead
        premium = await db.is_premium(msg.from_user.id)
        text = (
            f"📁 Файл слишком большой для отправки в Telegram (>{config.MAX_FILE_SIZE_MB}MB).\n\n"
            f"👇 Скачай напрямую по ссылке:"
        )
        b = InlineKeyboardBuilder()
        b.button(text="⬇️ Скачать", url=url)
        await status_msg.edit_text(text, reply_markup=b.as_markup())
        return

    try:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        with open(filepath, "rb") as f:
            data = f.read()

        file = BufferedInputFile(data, filename=filename)

        if ext in ("mp3", "ogg", "m4a", "flac", "wav", "opus"):
            await msg.answer_audio(file, title=filename)
        elif ext == "mp4":
            await msg.answer_video(file)
        else:
            await msg.answer_document(file)

        await status_msg.delete()

    except Exception as e:
        log.error(f"Send error: {e}")
        b = InlineKeyboardBuilder()
        b.button(text="⬇️ Скачать напрямую", url=url)
        await status_msg.edit_text(
            "⚠️ Не смог отправить файл через Telegram.\nСкачай напрямую:",
            reply_markup=b.as_markup(),
        )
    finally:
        if filepath and os.path.exists(filepath):
            os.unlink(filepath)


# ── ADMIN COMMANDS ────────────────────────────────────────────────────────────

@dp.message(Command("stats"), F.from_user.id == config.ADMIN_ID)
async def cmd_stats(msg: Message):
    s = await db.get_stats()
    text = (
        "📊 <b>Статистика VidBot</b>\n\n"
        f"👥 Всего пользователей: <b>{s['total_users']}</b>\n"
        f"📅 Новых сегодня: <b>{s['today_users']}</b>\n"
        f"⭐️ Premium пользователей: <b>{s['premium_users']}</b>\n\n"
        f"📥 Всего скачиваний: <b>{s['total_downloads']}</b>\n"
        f"📥 Скачиваний сегодня: <b>{s['today_downloads']}</b>\n\n"
        f"💰 Заработано Stars: <b>{s['total_stars']} ⭐️</b>\n"
        f"💵 Примерно: <b>${s['total_stars'] * 0.013:.2f}</b>"
    )
    await msg.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("broadcast"), F.from_user.id == config.ADMIN_ID)
async def cmd_broadcast(msg: Message):
    text = msg.text.replace("/broadcast", "").strip()
    if not text:
        await msg.answer("Использование: /broadcast Текст сообщения")
        return

    user_ids = await db.get_all_user_ids()
    sent = 0
    failed = 0

    status = await msg.answer(f"📢 Отправляю {len(user_ids)} пользователям...")

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Rate limit

    await status.edit_text(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")


@dp.message(Command("give_premium"), F.from_user.id == config.ADMIN_ID)
async def cmd_give_premium(msg: Message):
    parts = msg.text.split()
    if len(parts) < 3:
        await msg.answer("Использование: /give_premium USER_ID DAYS")
        return
    try:
        uid = int(parts[1])
        days = int(parts[2])
        await db.activate_premium(uid, days)
        await msg.answer(f"✅ Premium на {days} дней выдан пользователю {uid}")
        try:
            await bot.send_message(uid, f"🎁 Тебе выдан Premium на {days} дней!")
        except Exception:
            pass
    except ValueError:
        await msg.answer("Неверные аргументы.")


# ── MAIN ──────────────────────────────────────────────────────────────────────

async def main():
    await db.init_db()
    log.info("Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
