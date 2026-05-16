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
    FSInputFile,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
import database as db
from downloader import (
    fetch_download_url,
    detect_platform, is_supported_url, CobaltError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()


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


async def check_limit(user_id: int) -> tuple[bool, int]:
    if await db.is_premium(user_id):
        return True, 999
    await db.reset_daily_if_needed(user_id)
    used = await db.get_downloads_today(user_id)
    left = config.FREE_DOWNLOADS_PER_DAY - used
    return left > 0, max(left, 0)


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
        "Скачиваю видео без водяных знаков с:\n"
        "▸ YouTube · TikTok · Instagram · VK\n"
        "▸ Twitter/X · Reddit · Twitch · и ещё 1000+\n\n"
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
        f"🆓 Бесплатно: <b>{config.FREE_DOWNLOADS_PER_DAY} видео/день</b>\n"
        "⭐️ Premium: безлимит"
    )
    await cq.message.edit_text(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML)
    await cq.answer()


@dp.callback_query(F.data == "back_main")
async def cb_back(cq: CallbackQuery):
    await cq.message.edit_text("Отправь мне ссылку на видео 👇", reply_markup=kb_main())
    await cq.answer()


@dp.callback_query(F.data == "show_premium")
async def cb_show_premium(cq: CallbackQuery):
    if await db.is_premium(cq.from_user.id):
        await cq.answer("У тебя уже есть Premium! 🎉", show_alert=True)
        return
    text = (
        "⭐️ <b>VidBot Premium</b>\n\n"
        "✅ Безлимитные скачивания\n"
        "✅ Максимальное качество (4K)\n"
        "✅ Без ожиданий\n\n"
        "Оплата через Telegram Stars:"
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
        description=f"Безлимитное скачивание видео без водяных знаков.",
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
        f"🎉 <b>Premium активирован {days_label}!</b>\n\nТеперь скачивай без ограничений 🚀",
        parse_mode=ParseMode.HTML,
    )


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
            "📎 Отправь мне ссылку на видео.\n"
            "Например: <code>https://youtu.be/dQw4w9WgXcQ</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    can_dl, left = await check_limit(msg.from_user.id)
    if not can_dl:
        await msg.answer(
            f"😔 Бесплатный лимит исчерпан ({config.FREE_DOWNLOADS_PER_DAY}/день).\n\n"
            "⚡️ Купи Premium для безлимита:",
            reply_markup=kb_premium(),
            parse_mode=ParseMode.HTML,
        )
        return

    platform = detect_platform(raw)
    status_msg = await msg.answer(f"⏳ Скачиваю с {platform}... это может занять до 1 минуты")

    filepath = None
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: asyncio.run(fetch_download_url(raw, audio_only=audio_only))
        )
    except CobaltError as e:
        await status_msg.edit_text(f"❌ {e}")
        await db.log_download(msg.from_user.id, raw, platform, "error")
        return

    if result["type"] == "too_large":
        await status_msg.edit_text(
            f"⚠️ Видео слишком большое для отправки в Telegram (>{config.MAX_FILE_SIZE_MB}MB).\n"
            "Попробуй запросить более низкое качество: отправь ссылку снова."
        )
        return

    filepath = result["path"]
    filename = result["filename"]
    title = result.get("title", "Видео")

    await db.increment_downloads(msg.from_user.id)
    await db.log_download(msg.from_user.id, raw, platform, "ok")

    try:
        await status_msg.edit_text(f"📤 Отправляю: {title[:50]}...")
        file = FSInputFile(filepath, filename=filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext in ("mp3", "ogg", "m4a", "flac", "wav", "opus"):
            await msg.answer_audio(file, title=title[:64])
        elif ext == "mp4":
            await msg.answer_video(file, caption=f"📥 {title[:200]}")
        else:
            await msg.answer_document(file, caption=f"📥 {title[:200]}")

        await status_msg.delete()

        # Покажи остаток лимита если не премиум
        if not await db.is_premium(msg.from_user.id):
            used = await db.get_downloads_today(msg.from_user.id)
            left = config.FREE_DOWNLOADS_PER_DAY - used
            if left <= 1:
                b = InlineKeyboardBuilder()
                b.button(text="⚡️ Купить Premium", callback_data="show_premium")
                await msg.answer(
                    f"⚠️ Осталось <b>{left}</b> бесплатных скачиваний сегодня.",
                    reply_markup=b.as_markup(),
                    parse_mode=ParseMode.HTML,
                )

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
    text = (
        "📊 <b>Статистика VidBot</b>\n\n"
        f"👥 Всего пользователей: <b>{s['total_users']}</b>\n"
        f"📅 Новых сегодня: <b>{s['today_users']}</b>\n"
        f"⭐️ Premium: <b>{s['premium_users']}</b>\n\n"
        f"📥 Всего скачиваний: <b>{s['total_downloads']}</b>\n"
        f"📥 Сегодня: <b>{s['today_downloads']}</b>\n\n"
        f"💰 Stars заработано: <b>{s['total_stars']} ⭐️</b>\n"
        f"💵 Примерно: <b>${s['total_stars'] * 0.013:.2f}</b>"
    )
    await msg.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("broadcast"), F.from_user.id == config.ADMIN_ID)
async def cmd_broadcast(msg: Message):
    text = msg.text.replace("/broadcast", "").strip()
    if not text:
        await msg.answer("Использование: /broadcast Текст")
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
        await asyncio.sleep(0.05)
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
        await msg.answer(f"✅ Premium на {days} дней выдан {uid}")
        try:
            await bot.send_message(uid, f"🎁 Тебе выдан Premium на {days} дней!")
        except Exception:
            pass
    except ValueError:
        await msg.answer("Неверные аргументы.")


async def main():
    await db.init_db()
    log.info("Bot started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
