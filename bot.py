import asyncio
import logging
import tempfile
import os
import time
import random
import sqlite3
import yt_dlp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_errors.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv("API_TOKEN")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "120"))
REQUEST_LIMIT_PER_MINUTE = int(os.getenv("REQUEST_LIMIT_PER_MINUTE", "5"))

BOT_LINK = "https://t.me/myyvideodownloader_bot"  # ← username твоего бота

# Реклама после скачивания (замени на свой канал)
AD_TEXT = (
    "Спасибо за использование! ❤️\n"
    "Подпишись на мой основной канал для крутого контента:\n"
    "👉 @твой_канал\n"
    "Ещё больше полезного — заходи!"
)

# Мотивационные цитаты / шутки после скачивания
MOTIVATION = [
    "Ты сегодня молодец! Продолжай в том же духе 💪",
    "Музыка — это жизнь, а ты её скачал! 🎶",
    "Каждое видео — маленький шаг к хорошему настроению 😄",
    "Не останавливайся — впереди ещё больше крутого контента!",
    "Ты — легенда скачивания! 🏆",
    "Шутка дня: Почему программисты путают Хэллоуин и Рождество? Потому что Oct 31 == Dec 25 😂"
]

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_requests = {}

# База данных (SQLite)
conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    premium_until INTEGER DEFAULT 0,  -- timestamp до которого премиум
    last_notification INTEGER DEFAULT 0,  -- timestamp последнего уведомления о функциях
    ref_count INTEGER DEFAULT 0,
    ref_id INTEGER
)
''')
conn.commit()

def is_premium(user_id):
    cursor.execute('SELECT premium_until FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        return row[0] > time.time()
    return False

def add_premium_days(user_id, days):
    new_until = int(time.time()) + days * 86400
    cursor.execute('INSERT OR REPLACE INTO users (user_id, premium_until) VALUES (?, ?)', (user_id, new_until))
    conn.commit()

def increment_ref_count(ref_id):
    cursor.execute('UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?', (ref_id,))
    conn.commit()

def get_ref_id(user_id):
    cursor.execute('SELECT ref_id FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None

def update_notification_time(user_id):
    now = int(time.time())
    cursor.execute('UPDATE users SET last_notification = ? WHERE user_id = ?', (now, user_id))
    conn.commit()

def should_send_notification(user_id):
    cursor.execute('SELECT last_notification FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0]:
        return time.time() - row[0] > 7 * 86400  # 7 дней
    return True

@dp.message(CommandStart(deep_link=True))
async def cmd_start_ref(message: types.Message):
    user_id = message.from_user.id
    ref_id = message.get_args()  # ref123456
    if ref_id and ref_id.isdigit():
        ref_id = int(ref_id)
        if ref_id != user_id:
            increment_ref_count(ref_id)
            add_premium_days(ref_id, 10)  # +10 дней премиум
            await message.answer("Спасибо за приглашение друга! Тебе +10 дней премиум 🎉")
    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()

    ref_link = f"{BOT_LINK}?start=ref{user_id}"
    await message.answer(
        "<b>Привет! 👋</b>\n\n"
        f"Скачиваю видео и аудио из TikTok, Instagram Reels и VK клипов.\n\n"
        f"<b>Твоя реферальная ссылка</b> (приглашай друзей — +10 дней премиум за каждого):\n"
        f"{ref_link}\n\n"
        "<b>Пришли ссылку</b> — выбери, что скачать!"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "<b>Как пользоваться</b>\n\n"
        "1. Пришли ссылку на видео/клип\n"
        "2. Выбери «Видео 🎥» или «Аудио 🎵»\n"
        "3. Жди — бот пришлёт файл\n\n"
        "Приглашай друзей — +10 дней премиум за каждого!"
    )

@dp.message()
async def handle_link(message: types.Message):
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        await message.answer("Пришли ссылку на видео/клип.")
        return

    if "t.me/" in url.lower():
        await message.answer("Это ссылка на Telegram. Пришли ссылку на видео/клип!")
        return

    user_id = message.from_user.id
    now = time.time()
    if user_id not in user_requests:
        user_requests[user_id] = []
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < 60]
    if len(user_requests[user_id]) >= REQUEST_LIMIT_PER_MINUTE:
        await message.answer("Подожди минуту ⏳")
        return
    user_requests[user_id].append(now)

    await message.answer("Получаю информацию... ⏳")

    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 10,
            "fragment_retries": 5,
            "socket_timeout": 60,
            "nocheckcertificate": True,
            "cookiefile": "cookies.txt",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            extractor = info.get("extractor_key", "").lower()
            supported = ["tiktok", "instagram", "vk"]
            if not any(s in extractor for s in supported):
                await message.answer("Поддерживаю только TikTok, Instagram Reels и VK клипы. Попробуй другую ссылку.")
                return

            title = info.get("title", "Без названия")
            uploader = info.get("uploader", "Автор неизвестен")
            duration = info.get("duration", 0)
            duration_str = f"{int(duration) // 60:02d}:{int(duration) % 60:02d}" if duration and duration > 0 else "—"
            thumbnail = info.get("thumbnail")

            bot.full_url = url

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Видео 🎥", callback_data="dl_video"),
                    InlineKeyboardButton(text="Аудио 🎵", callback_data="dl_audio")
                ],
                [
                    InlineKeyboardButton(text="Назад ⬅️", callback_data="back")
                ]
            ])

            caption = (
                f"<b>{title}</b>\n"
                f"Автор: {uploader}\n"
                f"Длительность: {duration_str}\n"
                f"Источник: {info.get('extractor_key', 'сайт')}\n\n"
                f"Что скачать:\n\n"
                f"🤖 <a href=\"{BOT_LINK}\">Ещё</a>"
            )

            if thumbnail:
                await message.answer_photo(
                    photo=thumbnail,
                    caption=caption,
                    reply_markup=keyboard
                )
            else:
                await message.answer(caption, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Ошибка обработки {url}: {str(e)}", exc_info=True)
        await message.answer("Не получилось обработать эту ссылку 😔\nПопробуй другую или /help")

@dp.callback_query(lambda c: c.data in ["dl_video", "dl_audio", "back"])
async def process_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if callback.data == "back":
        await callback.message.delete()
        await callback.message.answer("<b>Отменил выбор.</b>\n\nПришли новую ссылку или /start")
        await callback.answer()
        return

    choice = callback.data.split("_")[1]
    url = bot.full_url

    await callback.message.edit_caption(caption=f"Скачиваю {choice}... ⏳", reply_markup=None)

    try:
        if choice == "video":
            format_str = "best[ext=mp4]/best"
        else:
            format_str = "bestaudio[ext=m4a]/bestaudio/best"

        ydl_opts = {
            "format": format_str,
            "outtmpl": "%(id)s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 10,
            "socket_timeout": 60,
            "nocheckcertificate": True,
            "cookiefile": "cookies.txt",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts["outtmpl"] = os.path.join(tmpdir, "%(id)s.%(ext)s")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)

            if file_size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_caption(caption=f"Файл слишком большой ({file_size_mb:.1f} МБ)")
                return

            title = info.get("title", "Файл")
            uploader = info.get("uploader", "Автор неизвестен")
            duration = info.get("duration", 0)
            duration_str = f"{int(duration) // 60:02d}:{int(duration) % 60:02d}" if duration and duration > 0 else "—"

            caption = (
                f"<b>{title}</b>\n"
                f"Автор: {uploader}\n"
                f"Длительность: {duration_str}\n"
                f"Размер: {file_size_mb:.1f} МБ\n"
                f"Тип: {'Аудио' if choice == 'audio' else 'Видео'}\n\n"
                f"🤖 <a href=\"{BOT_LINK}\">Ещё</a>"
            )

            if choice == "audio":
                await callback.message.answer_audio(
                    audio=FSInputFile(filename),
                    caption=caption,
                    title=title,
                    performer=uploader
                )
            else:
                if file_size_mb <= 50:
                    await callback.message.answer_video(
                        video=FSInputFile(filename),
                        caption=caption,
                        supports_streaming=True
                    )
                else:
                    await callback.message.answer_document(
                        document=FSInputFile(filename),
                        caption=caption
                    )

            await callback.message.delete()

            # Автоматическое удаление файла после отправки
            os.remove(filename)

            # Реклама после скачивания
            await callback.message.answer(AD_TEXT)

    except Exception as e:
        logger.error(f"Ошибка скачивания {url} ({choice}): {str(e)}", exc_info=True)
        await callback.message.edit_caption(caption="Не получилось скачать 😔\nПопробуй другую ссылку.")

    await callback.answer()

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
