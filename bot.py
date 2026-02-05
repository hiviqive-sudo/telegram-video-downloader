import asyncio
import logging
import tempfile
import os
import time
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

# Переменные из Railway
API_TOKEN = os.getenv("API_TOKEN")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "120"))
REQUEST_LIMIT_PER_MINUTE = int(os.getenv("REQUEST_LIMIT_PER_MINUTE", "5"))

# ОБЯЗАТЕЛЬНО ИЗМЕНИТЬ!
BOT_LINK = "https://t.me/myyvideodownloader_bot"  # ← ваш реальный username бота

# Качества видео
QUALITIES = {
    "360":  "bestvideo[height<=360][ext=mp4]/best[height<=360]/bestvideo[ext=mp4]+bestaudio/best",
    "480":  "bestvideo[height<=480][ext=mp4]/best[height<=480]/bestvideo[ext=mp4]+bestaudio/best",
    "720":  "bestvideo[height<=720][ext=mp4]/best[height<=720]/bestvideo[ext=mp4]+bestaudio/best",
    "1080": "bestvideo[height<=1080][ext=mp4]/best[height<=1080]/bestvideo[ext=mp4]+bestaudio/best",
    "Audio": "bestaudio[ext=m4a]/bestaudio/best",
}

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_requests = {}

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "<b>Привет! 👋</b>\n\n"
        "Скачиваю видео из TikTok, Instagram Reels, YouTube, Twitter/X и других сайтов.\n"
        "Без водяных знаков (где возможно).\n\n"
        "<b>Пришли ссылку</b> на видео!"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "<b>Как пользоваться</b>\n\n"
        "1. Пришли ссылку\n"
        "2. Выбери качество (360, 480, 720, 1080, Audio)\n"
        "3. Жди — бот пришлёт файл\n\n"
        f"Лимиты:\n"
        f"• До 50 МБ → видео\n"
        f"• 50–{MAX_FILE_SIZE_MB} МБ → документ\n"
        f"• Больше → не скачаю\n\n"
        "Для Instagram используй cookies (если не работает — обнови их)."
    )

@dp.message()
async def handle_link(message: types.Message):
    url = message.text.strip()
    if not url.startswith(("http://", "https://")):
        await message.answer("Это не ссылка. Пришли правильную ссылку на видео.")
        return

    user_id = message.from_user.id
    now = time.time()

    if user_id not in user_requests:
        user_requests[user_id] = []
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < 60]
    if len(user_requests[user_id]) >= REQUEST_LIMIT_PER_MINUTE:
        await message.answer("Слишком много запросов. Подожди минуту ⏳")
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
            "cookiefile": "cookies.txt",  # Для Instagram / TikTok
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            title = info.get("title", "Без названия")
            uploader = info.get("uploader", "Автор неизвестен")
            duration = info.get("duration", 0)
            # Безопасное форматирование длительности
            duration_str = (
                f"{int(duration) // 60:02d}:{int(duration) % 60:02d}"
                if duration and duration > 0
                else "—"
            )
            thumbnail = info.get("thumbnail")

            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            row = []
            for q_name in QUALITIES:
                btn = InlineKeyboardButton(
                    text=q_name,
                    callback_data=f"dl_{q_name}_{url}"
                )
                row.append(btn)
                if len(row) == 3:
                    keyboard.inline_keyboard.append(row)
                    row = []
            if row:
                keyboard.inline_keyboard.append(row)

            caption = (
                f"<b>{title}</b>\n"
                f"Автор: {uploader}\n"
                f"Длительность: {duration_str}\n"
                f"Источник: {info.get('extractor_key', 'сайт')}\n\n"
                f"Выбери качество:\n\n"
                f"🤖 <a href=\"{BOT_LINK}\">Ещё видео</a>"
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
        await message.answer(
            "Не получилось обработать эту ссылку 😔\n"
            "Попробуй другую или пришли /help"
        )

@dp.callback_query(lambda c: c.data.startswith("dl_"))
async def process_download(callback: types.CallbackQuery):
    try:
        _, quality, url = callback.data.split("_", 2)
    except:
        await callback.answer("Ошибка запроса", show_alert=True)
        return

    if quality not in QUALITIES:
        await callback.answer("Такого качества нет", show_alert=True)
        return

    await callback.message.edit_caption(
        caption=f"Скачиваю в {quality}... ⏳",
        reply_markup=None
    )

    try:
        ydl_opts = {
            "format": QUALITIES[quality],
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
                await callback.message.edit_caption(
                    caption=f"Файл слишком большой ({file_size_mb:.1f} МБ)"
                )
                return

            title = info.get("title", "Видео")
            caption = (
                f"<b>{title}</b>\n"
                f"Качество: {quality}\n"
                f"Размер: {file_size_mb:.1f} МБ\n\n"
                f"🤖 <a href=\"{BOT_LINK}\">Ещё видео</a>"
            )

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

    except Exception as e:
        logger.error(f"Ошибка скачивания {url} ({quality}): {str(e)}", exc_info=True)
        await callback.message.edit_caption(
            caption="Не получилось скачать в этом качестве 😔\nПопробуй другое."
        )

    await callback.answer()

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
