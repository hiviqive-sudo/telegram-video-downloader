import asyncio
import logging
import tempfile
import os
import time
from datetime import datetime, timedelta
import yt_dlp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Логи в файл + консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_errors.log"),
        logging.StreamHandler()
    ]
)

API_TOKEN = os.getenv('API_TOKEN')
MAX_FILE_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', 100))
REQUEST_LIMIT_PER_MINUTE = int(os.getenv('REQUEST_LIMIT_PER_MINUTE', 5))

# Ссылка на твоего бота (замени на реальный!)
BOT_LINK = "https://t.me/myyvideodownloader_bot"  # ← здесь измени!

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Анти-спам
user_requests = {}

# Качества — твои новые варианты
QUALITIES = {
    '360': 'bestvideo[height<=360]+bestaudio/best[height<=360]',
    '480': 'bestvideo[height<=480]+bestaudio/best[height<=480]',
    '720': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
    '1080': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
    'audio': 'bestaudio/best',
}

@dp.message(CommandStart())
async def start(message: types.Message):
    text = (
        "Привет! Я скачиваю видео без водяных знаков 🎥\n\n"
        "<b>Поддерживаю:</b> YouTube, TikTok, Instagram Reels, X/Twitter и др.\n\n"
        "Просто пришли ссылку на видео!"
    )
    await message.answer(text)

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    text = (
        "Команды:\n"
        "/start — начать\n"
        "/help — помощь\n\n"
        "<b>Как пользоваться:</b>\n"
        "1. Пришли ссылку\n"
        "2. Выбери качество\n"
        "3. Жди — видео придёт\n\n"
        "Если >50 МБ — как файл. Если >" + str(MAX_FILE_SIZE_MB) + " МБ — не скачаю."
    )
    await message.answer(text)

@dp.message()
async def handle_message(message: types.Message):
    url = message.text.strip()
    if not url.startswith(('http://', 'https://')):
        await message.answer("Это не ссылка 😅 Пришли правильную.")
        return

    user_id = message.from_user.id

    # Анти-спам
    now = time.time()
    if user_id not in user_requests:
        user_requests[user_id] = []
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < 60]
    if len(user_requests[user_id]) >= REQUEST_LIMIT_PER_MINUTE:
        await message.answer("Слишком много запросов! Подожди минуту ⏳")
        return
    user_requests[user_id].append(now)

    await message.answer("Получаю информацию... ⏳")

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'retries': 10,
            'fragment_retries': 10,
            'socket_timeout': 60,
            'nocheckcertificate': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            title = info.get('title', 'Видео')
            uploader = info.get('uploader', 'Автор неизвестен')
            duration = info.get('duration', 0)
            duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "?"
            thumbnail_url = info.get('thumbnail')  # ← превью

            # Кнопки качества
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            row = []
            for q_key in QUALITIES:
                btn = InlineKeyboardButton(text=q_key, callback_data=f"quality_{q_key}_{url}")
                row.append(btn)
                if len(row) == 3:  # по 3 кнопки в ряд
                    keyboard.inline_keyboard.append(row)
                    row = []
            if row:
                keyboard.inline_keyboard.append(row)

            caption = (
                f"<b>{title}</b>\n"
                f"Автор: {uploader}\n"
                f"Длительность: {duration_str}\n"
                f"Источник: {info.get('extractor', 'сайт')}\n\n"
                f"Выбери качество:\n\n"
                f"Бот: <a href=\"{BOT_LINK}\">{BOT_LINK.split('/')[-1]}</a>"
            )

            # Отправляем сообщение с превью и кнопками
            if thumbnail_url:
                await message.answer_photo(
                    photo=thumbnail_url,
                    caption=caption,
                    reply_markup=keyboard
                )
            else:
                # Если превью нет — просто текст
                await message.answer(caption, reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Ошибка при обработке {url}: {str(e)}", exc_info=True)
        await message.answer(f"Не получилось получить информацию 😔\nОшибка: {str(e)}")

@dp.callback_query(lambda c: c.data.startswith('quality_'))
async def process_quality(callback: types.CallbackQuery):
    _, q_key, url = callback.data.split('_', 2)
    if q_key not in QUALITIES:
        await callback.answer("Неизвестное качество", show_alert=True)
        return

    await callback.message.edit_caption(caption="Скачиваю в " + q_key + "... ⏳", reply_markup=None)

    try:
        format_str = QUALITIES[q_key]

        ydl_opts = {
            'format': format_str,
            'outtmpl': '%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'retries': 10,
            'socket_timeout': 60,
            'nocheckcertificate': True,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts['outtmpl'] = f'{tmpdir}/%(id)s.%(ext)s'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)

            if file_size_mb > MAX_FILE_SIZE_MB:
                await callback.message.edit_caption(
                    caption=f"Видео слишком большое ({file_size_mb:.1f} МБ > {MAX_FILE_SIZE_MB} МБ). Попробуй другое качество."
                )
                return

            caption = (
                f"<b>{info.get('title', 'Видео')}</b>\n"
                f"Качество: {q_key}\n"
                f"Размер: {file_size_mb:.1f} МБ\n\n"
                f"Бот: <a href=\"{BOT_LINK}\">{BOT_LINK.split('/')[-1]}</a>"
            )

            if file_size_mb > 50:
                await callback.message.answer_document(
                    document=FSInputFile(filename),
                    caption=caption
                )
            else:
                await callback.message.answer_video(
                    video=FSInputFile(filename),
                    caption=caption,
                    supports_streaming=True
                )

            await callback.message.delete()

    except Exception as e:
        logging.error(f"Ошибка скачивания {url} в {q_key}: {str(e)}", exc_info=True)
        await callback.message.edit_caption(f"Не получилось в этом качестве 😔\n{str(e)}")

    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
