import asyncio
import logging
import tempfile
import os
import time
import sqlite3
import yt_dlp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Логирование
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
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", None)  # ← ID твоего канала для логов (например -1001234567890)

BOT_LINK = "https://t.me/myyvideodownloader_bot"  # ← username твоего бота

# Реклама после скачивания (замени на свою)
AD_TEXT = (
    "Спасибо за использование! ❤️\n"
    "Подпишись на мой основной канал для крутого контента:\n"
    "👉 @твой_канал\n"
    "Ещё больше полезного — заходи!"
)

# Качества видео (гибкие, без ошибок)
QUALITIES = {
    "360": "bestvideo[height<=360][ext=mp4]/best[ext=mp4]",
    "480": "bestvideo[height<=480][ext=mp4]/best[ext=mp4]",
    "720": "bestvideo[height<=720][ext=mp4]/best[ext=mp4]",
    "1080": "bestvideo[height<=1080][ext=mp4]/best[ext=mp4]",
    "Аудио": "bestaudio[ext=m4a]/bestaudio/best",
}

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_requests = {}

# База данных для пользователей (SQLite)
conn = sqlite3.connect('downloads.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS downloads (
    user_id INTEGER PRIMARY KEY,
    count INTEGER DEFAULT 0,
    last_download DATE
)
''')
conn.commit()

async def update_download_count(user_id):
    today = time.strftime('%Y-%m-%d')
    cursor.execute('SELECT count, last_download FROM downloads WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        count, last_date = row
        if last_date != today:
            count = 1
            cursor.execute('UPDATE downloads SET count = 1, last_download = ? WHERE user_id = ?', (today, user_id))
        else:
            count += 1
            cursor.execute('UPDATE downloads SET count = ? WHERE user_id = ?', (count, user_id))
    else:
        count = 1
        cursor.execute('INSERT INTO downloads (user_id, count, last_download) VALUES (?, 1, ?)', (user_id, today))
    conn.commit()
    return count

# Прогресс-хук
def progress_hook(d, progress_msg: types.Message):
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', '0%')
        try:
            asyncio.create_task(progress_msg.edit_caption(caption=f"Скачиваю... {percent}"))
        except Exception:
            pass
    elif d['status'] == 'finished':
        try:
            asyncio.create_task(progress_msg.edit_caption(caption="Готово! Отправляю файл... ⏳"))
        except Exception:
            pass

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "<b>Привет! 👋</b>\n\n"
        "Скачиваю видео и аудио из TikTok и Instagram Reels.\n\n"
        "<b>Пришли ссылку</b> — выбери качество!"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "<b>Как пользоваться</b>\n\n"
        "1. Пришли ссылку на видео/клип из TikTok или Instagram Reels\n"
        "2. Выбери качество (360, 480, 720, 1080, Audio)\n"
        "3. Жди — бот пришлёт файл\n\n"
        f"Лимит размера: {MAX_FILE_SIZE_MB} МБ\n"
        "Если ошибка — попробуй другую ссылку."
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
            if "tiktok" not in extractor and "instagram" not in extractor:
                await message.answer("Поддерживаю только TikTok и Instagram Reels. Попробуй другую ссылку.")
                return

            title = info.get("title", "Без названия")
            uploader = info.get("uploader", "Автор неизвестен")
            duration = info.get("duration", 0)
            duration_str = f"{int(duration) // 60:02d}:{int(duration) % 60:02d}" if duration and duration > 0 else "—"
            thumbnail = info.get("thumbnail")

            bot.full_url = url

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="360", callback_data="dl_360"),
                    InlineKeyboardButton(text="480", callback_data="dl_480"),
                    InlineKeyboardButton(text="720", callback_data="dl_720")
                ],
                [
                    InlineKeyboardButton(text="1080", callback_data="dl_1080"),
                    InlineKeyboardButton(text="Аудио", callback_data="dl_audio")
                ],
                [
                    InlineKeyboardButton(text="Назад", callback_data="back")
                ]
            ])

            caption = (
                f"<b>{title}</b>\n"
                f"Автор: {uploader}\n"
                f"Длительность: {duration_str}\n"
                f"Источник: {info.get('extractor_key', 'сайт')}\n\n"
                f"Выбери качество:\n\n"
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

@dp.callback_query(lambda c: c.data in ["dl_360", "dl_480", "dl_720", "dl_1080", "dl_audio", "back"])
async def process_callback(callback: types.CallbackQuery):
    if callback.data == "back":
        await callback.message.delete()
        await callback.message.answer("<b>Отменил выбор.</b>\n\nПришли новую ссылку или /start")
        await callback.answer()
        return

    choice = callback.data.split("_")[1]
    url = bot.full_url

    progress_msg = await callback.message.edit_caption(caption="Скачиваю... ⏳", reply_markup=None)

    try:
        format_str = QUALITIES.get(choice, "best[ext=mp4]/best")

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
                await progress_msg.edit_caption(caption=f"Файл слишком большой ({file_size_mb:.1f} МБ)")
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
                f"Тип: {'Аудио' if choice == 'Аудио' else 'Видео'}\n\n"
                f"🤖 <a href=\"{BOT_LINK}\">Ещё</a>"
            )

            if choice == "Аудио":
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

            await progress_msg.delete()

            # Автоматическое удаление файла после отправки
            os.remove(filename)

            # Реклама после скачивания
            await callback.message.answer(AD_TEXT)

    except Exception as e:
        logger.error(f"Ошибка скачивания {url} ({choice}): {str(e)}", exc_info=True)
        await progress_msg.edit_caption(caption="Не получилось скачать 😔\nПопробуй другую ссылку.")

    await callback.answer()

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
