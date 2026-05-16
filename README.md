# 🎬 VidBot — Telegram Video Downloader

Бот для скачивания видео без водяных знаков с YouTube, TikTok, Instagram, VK и 20+ платформ.
Freemium модель с оплатой через Telegram Stars.

---

## ⚡️ Быстрый старт

### 1. Создай бота

Открой [@BotFather](https://t.me/botfather) в Telegram:
```
/newbot
```
Получишь токен вида `7123456789:AAHxxx...`

### 2. Клонируй и настрой

```bash
git clone <repo>
cd vidbot

cp .env.example .env
nano .env
```

Заполни `.env`:
```env
BOT_TOKEN=7123456789:AAHxxxxxxxx   # Токен от BotFather
ADMIN_ID=123456789                  # Твой Telegram ID (узнай у @userinfobot)
FREE_DOWNLOADS_PER_DAY=5            # Бесплатных скачиваний в день
MAX_FILE_SIZE_MB=50                 # Макс размер файла
```

### 3. Установи зависимости

```bash
python3 -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 4. Запусти

```bash
python bot.py
```

---

## 🚀 Запуск на сервере (systemd)

Создай файл `/etc/systemd/system/vidbot.service`:

```ini
[Unit]
Description=VidBot Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/vidbot
ExecStart=/home/ubuntu/vidbot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable vidbot
sudo systemctl start vidbot
sudo systemctl status vidbot
```

---

## 📋 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Запуск бота |
| `/stats` | Статистика (только админ) |
| `/broadcast текст` | Рассылка всем (только админ) |
| `/give_premium ID DAYS` | Выдать Premium (только админ) |

**Скачивание аудио:** отправь `audio https://youtu.be/...`

---

## 💰 Монетизация

### Telegram Stars (встроено)
- 7 дней → **50 Stars** (~$0.65)
- 30 дней → **150 Stars** (~$2)
- Навсегда → **500 Stars** (~$6.50)

Вывод Stars → рубли/USDT через Telegram Fragment.

### Как менять цены
В `config.py` → `PLANS`:
```python
PLANS = {
    "week": {"stars": 50, "days": 7, ...},
    "month": {"stars": 150, "days": 30, ...},
    "forever": {"stars": 500, "days": 36500, ...},
}
```

---

## 📊 Рекомендуемые настройки для роста

```env
FREE_DOWNLOADS_PER_DAY=3   # Чем меньше лимит — тем больше конверсия в платных
```

### Стратегия продвижения
1. Создай канал в Telegram, постингуй полезный контент
2. В описании канала → ссылка на бота
3. Покупай рекламу у тематических каналов (мемы, видео, развлечения)
4. Используй `/broadcast` для уведомлений пользователей о новых функциях

---

## 🏗️ Архитектура

```
bot.py         — хэндлеры aiogram, логика бота
config.py      — настройки, цены планов
database.py    — SQLite через aiosqlite
downloader.py  — обёртка над cobalt.tools API
vidbot.db      — база данных (создаётся автоматически)
```

---

## ⚙️ Зависимости

- Python 3.11+
- aiogram 3.13
- aiohttp
- aiosqlite
- python-dotenv

---

Powered by [cobalt.tools](https://cobalt.tools) 🛠
