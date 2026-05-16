import asyncio
import os
import logging
import random

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup,
    LabeledPrice, PreCheckoutQuery,
    FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database as db
from downloader import (
    fetch_download_url,
    detect_platform, CobaltError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

ADS = [
    {
        "text": "🎰 <b>1WIN</b> — лучший букмекер!\nБонус 500% на первый депозит 🔥",
        "button": "Забрать бонус",
        "url": "https://1win.com",
    },
    {
        "text": "⚽️ <b>Melbet</b> — ставки на спорт!\nРегистрируйся и получи фрибет 💰",
        "button": "Получить фрибет",
        "url": "https://melbet.com",
    },
]

AD_EVERY_N = 5


def kb_main() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❓ Помощь", callback_data="help")
    b.adjust(1)
    return b.as_markup()


def kb_premium() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, plan in config.PLANS.items():
        b.button(text=f"{plan['label']} — ⭐️ {plan['stars']}", callback_data=f"buy_{key}")
    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def kb_ad(url: str, button_text: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=button_text, url=url)
    return b.as_markup()


def kb_youtube(options: list, audio_url: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for opt in options:
        b.button(text=f"📥 {opt['quality']} ({opt['ext']})", url=opt["url"])
    if audio_url:
        b.button(text="🎵 Только аудио", url=audio_url)
    b.adjust(2)
    return b.as_markup()


async def show_ad(msg: Message):
    total = (await db.get_stats())["total_downloads"]
    if total % AD_EVERY_N == 0 and ADS:
        ad = random.choice(ADS)
        await msg.answer(ad["text"], reply_markup=kb_ad(ad["url"], ad["button"]), parse_mode=ParseMode.HTML)


@dp.message(CommandStart())
async def cmd_start(msg: Message):
    await db.get_or_create_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")
    text = (
        f"👋 Привет, <b>{msg.from_user.first_name}</b>!\n\n"
        "Скачиваю видео без водяных знаков с:\n"
        "▸ YouTube · TikTok · Instagram · VK\n"
        "▸ Twitter/X · Reddit · Twitch · и ещё 1000+\n\n"
        "📎 <b>Просто отправь мне ссылку</b> — и всё!"
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
        "📋 YouTube, TikTok, Instagram, VK, Twitter/X и 1000+ других."
    )
    await cq.message.edit_text(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
    await cq.answer()


@dp.callback_query(F.data == "back_main")
async def cb_back(cq: CallbackQuery):
    await cq.message.edit_text("Отправь мне ссылку на видео 👇", reply_markup=kb_main())
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
        description="Безлимитное скачивание видео.",
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
    await msg.answer(f"🎉 <b>Premium активирован {days_label}!</b>", parse_mode=ParseMode.HTML)


@dp.message(F.text)
async def handle_url(msg: Message):
    await db.get_or_create_user(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name or "")

    raw = msg.text.strip()
    audio_only = False
    if raw.lower().startswith("audio "):
        audio_only = True
        raw = raw[6:].strip()

    if not raw.startswith("http"):
        await msg.answer(
            "📎 Отправь мне ссылку на видео.\nНапример: <code>https://youtu.be/dQw4w9WgXcQ</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    platform = detect_platform(raw)
    status_msg = await msg.answer(f"⏳ Скачиваю с {platform}...")

    filepath = None
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: asyncio.run(fetch_download_url(raw, audio_only=audio_only))
        )
    except CobaltError as e:
        await status_msg.edit_text(f"❌ {e}")
        await db.log_download(msg.from_user.id, raw, platform, "error")
        return

    # YouTube — показываем кнопки качества
    if result["type"] == "youtube_links":
        await status_msg.delete()
        await db.increment_downloads(msg.from_user.id)
        await db.log_download(msg.from_user.id, raw, platform, "ok")

        title = result.get("title", "Видео")[:200]
        options = result.get("options", [])
        audio_url = result.get("audio_url")

        if not options and not audio_url:
            await msg.answer("❌ Не удалось получить ссылки для скачивания.")
            return

        await msg.answer(
            f"🎬 <b>{title}</b>\n\nВыбери качество:",
            reply_markup=kb_youtube(options, audio_url),
            parse_mode=ParseMode.HTML,
        )
        await show_ad(msg)
        return

    if result["type"] == "too_large":
        await status_msg.edit_text(f"⚠️ Файл слишком большой для Telegram (>{config.MAX_FILE_SIZE_MB}MB).")
        return

    filepath = result["path"]
    filename = result["filename"]
    title = result.get("title", "Видео")

    await db.increment_downloads(msg.from_user.id)
    await db.log_download(msg.from_user.id, raw, platform, "ok")

    try:
        await status_msg.edit_text("📤 Отправляю...")
        file = FSInputFile(filepath, filename=filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext in ("mp3", "ogg", "m4a", "flac", "wav", "opus"):
            await msg.answer_audio(file, title=title[:64])
        elif ext == "mp4":
            await msg.answer_video(file, caption=f"📥 {title[:200]}")
        else:
            await msg.answer_document(file, caption=f"📥 {title[:200]}")

        await status_msg.delete()
        await show_ad(msg)

    except Exception as e:
        log.error(f"Send error: {e}")
        await status_msg.edit_text("❌ Не смог отправить файл. Попробуй ещё раз.")
    finally:
        if filepath and os.path.exists(filepath):
            os.unlink(filepath)
            try:
                os.rmdir(os.path.dirname(filepath))
            except Exception:
                pass


@dp.message(Command("stats"), F.from_user.id == config.ADMIN_ID)
async def cmd_stats(msg: Message):
    s = await db.get_stats()
    await msg.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{s['total_users']}</b>\n"
        f"📅 Новых сегодня: <b>{s['today_users']}</b>\n"
        f"📥 Скачиваний всего: <b>{s['total_downloads']}</b>\n"
        f"📥 Сегодня: <b>{s['today_downloads']}</b>",
        parse_mode=ParseMode.HTML,
    )


@dp.message(Command("broadcast"), F.from_user.id == config.ADMIN_ID)
async def cmd_broadcast(msg: Message):
    text = msg.text.replace("/broadcast", "").strip()
    if not text:
        await msg.answer("Использование: /broadcast Текст")
        return
    user_ids = await db.get_all_user_ids()
    sent = failed = 0
    status = await msg.answer(f"📢 Отправляю {len(user_ids)} пользователям...")
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Отправлено: {sent}\n❌ Ошибок: {failed}")


async def main():
    await db.init_db()
    log.info("Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
