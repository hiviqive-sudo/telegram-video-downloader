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

# Реклама для бесплатных пользователей (замени на свой канал)
AD_TEXT = (
    "Спасибо за использование! ❤️\n"
    "Подпишись на мой основной канал для крутого контента:\n"
    "👉 @твой_канал\n"
    "Ещё больше полезного — заходи!"
)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_requests = {}

# База данных (SQLite)
conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    premium_until INTEGER DEFAULT 0,
    ref_count INTEGER DEFAULT 0,
    ref_id INTEGER,
    total_downloads INTEGER DEFAULT 0,
    last_active TIMESTAMP
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
    current_until = 0
    cursor.execute('SELECT premium_until FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        current_until = row[0]
    new_until = max(current_until, int(time.time())) + days * 86400
    cursor.execute('UPDATE users SET premium_until = ? WHERE user_id = ?', (new_until, user_id))
    conn.commit()

def increment_ref_count(ref_id):
    cursor.execute('UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?', (ref_id,))
    conn.commit()

def increment_download_count(user_id):
    now = int(time.time())
    cursor.execute('UPDATE users SET total_downloads = total_downloads + 1, last_active = ? WHERE user_id = ?', (now, user_id))
    conn.commit()

def get_user_stats(user_id):
    cursor.execute('SELECT premium_until, ref_count, total_downloads, last_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        premium_until, ref_count, total_downloads, last_active = row
        premium_days = max(0, int((premium_until - time.time()) / 86400)) if premium_until else 0
        last_active_str = time.strftime('%d.%m.%Y %H:%M', time.localtime(last_active)) if last_active else "Никогда"
        return premium_days, ref_count, total_downloads, last_active_str
    return 0, 0, 0, "Никогда"

@dp.message(CommandStart(deep_link=True))
async def cmd_start_ref(message: types.Message):
    args = message.text.split(' ', 1)[1] if len(message.text.split(' ', 1)) > 1 else None
    if args and args.startswith("ref"):
        ref_id = int(args.replace("ref", ""))
        if ref_id != message.from_user.id:
            increment_ref_count(ref_id)
            add_premium_days(ref_id, 10)
            # Уведомление ТОЛЬКО пригласившему
            await bot.send_message(ref_id, "🎉 Твой друг перешёл по реферальной ссылке! Тебе +10 дней премиум!")
    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    cursor.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
    conn.commit()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Личный кабинет 📊", callback_data="cabinet")],
        [InlineKeyboardButton(text="Пригласить друга и получить бонус 🎁", callback_data="show_ref")]
    ])

    await message.answer(
        "✨ <b>Привет, легенда скачиваний! 👋</b> ✨\n\n"
        "Я твой личный помощник по видео и музыке 🔥\n"
        "Скачиваю всё самое крутое из:\n"
        "  • TikTok 🎬\n"
        "  • Instagram Reels 📱\n"
        "  • VK клипы 🎥\n\n"
        "<b>Просто пришли ссылку</b> — и я всё сделаю за секунды! 🚀\n\n"
        "Выбирай качество и наслаждайся! 🌟",
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@dp.callback_query(lambda c: c.data == "cabinet")
async def show_cabinet(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    premium_days, ref_count, total_downloads, last_active = get_user_stats(user_id)

    premium_status = f"Премиум активен: <b>{premium_days} дней</b> 💎" if premium_days > 0 else "Премиум не активен 😔"

    cabinet_text = (
        "📊 <b>Личный кабинет</b> 📊\n\n"
        f"{premium_status}\n"
        f"Всего скачиваний: <b>{total_downloads}</b>\n"
        f"Приглашено друзей: <b>{ref_count}</b>\n"
        f"Последняя активность: <b>{last_active}</b>\n\n"
        "Приглашай друзей — +10 дней премиум за каждого! 🎉"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Скачать ещё", callback_data="download")],
        [InlineKeyboardButton(text="Пригласить друга и получить бонус 🎁", callback_data="show_ref")],
        [InlineKeyboardButton(text="Назад ⬅️", callback_data="back")]
    ])

    await callback.message.edit_text(cabinet_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "download")
async def download_from_cabinet(callback: types.CallbackQuery):
    await callback.message.edit_text("Пришли новую ссылку для скачивания!")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "show_ref")
async def show_ref(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ref_link = f"{BOT_LINK}?start=ref{user_id}"

    ref_text = (
        "Вот твоя уникальная реферальная ссылка! 📩\n"
        f"<code>{ref_link}</code>\n\n"
        "Нажми на ссылку выше → выбери «Скопировать»\n\n"
        "Отправь её друзьям — как только они начнут пользоваться ботом, тебе +10 дней премиум 🎉\n\n"
        "Чем больше друзей — тем дольше премиум! 💎"
    )

    await callback.message.answer(ref_text, disable_web_page_preview=True)
    await callback.answer("Ссылка отправлена! Нажми на неё и скопируй 📋")

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

            # Счётчик скачиваний
            user_id = callback.from_user.id
            increment_download_count(user_id)

            # Реклама после скачивания (только для бесплатных)
            if not is_premium(user_id):
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
