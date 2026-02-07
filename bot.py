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

BOT_LINK = "https://t.me/myyvideodownloader_bot"

# Список публичных @username (для приватных — используем только ссылки в кнопках)
REQUIRED_CHANNELS = ["@jgfdfdgdg"]  # ← публичные каналы (если есть)

# Ссылки-приглашения на приватные каналы
CHANNEL_LINKS = [
    "https://t.me/+AfKNOoS0oz82MzJi",  # канал 1 (приватный)
    "https://t.me/jgfdfdgdg"           # канал 2 (публичный или приватный)
]

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_requests = {}

async def is_subscribed(user_id: int) -> bool:
    """Проверяет подписку на публичные каналы"""
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception as e:
            logger.error(f"Ошибка проверки подписки на {channel}: {str(e)}")
            return False
    return True

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        "<b>Привет! 👋</b>\n\n"
        "Скачиваю видео и аудио из TikTok и Instagram Reels.\n\n"
        "<b>Пришли ссылку</b> — выбери, что скачать!"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "<b>Как пользоваться</b>\n\n"
        "1. Пришли ссылку на видео/клип из TikTok или Instagram Reels\n"
        "2. Подпишись на каналы (если нужно)\n"
        "3. Выбери «Видео» или «Аудио»\n"
        "4. Жди — бот пришлёт файл\n\n"
        f"Лимит размера: {MAX_FILE_SIZE_MB} МБ"
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

            # Проверяем подписку
            if not await is_subscribed(user_id):
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Подписаться на канал 1", url="https://t.me/+AfKNOoS0oz82MzJi")],
                    [InlineKeyboardButton(text="Подписаться на канал 2", url="https://t.me/jgfdfdgdg")],
                    [InlineKeyboardButton(text="Проверить подписку", callback_data="check_sub")]
                ])
                await message.answer(
                    "Чтобы скачать, подпишись на каналы и нажми «Проверить подписку»!",
                    reply_markup=keyboard
                )
                return

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Видео", callback_data="dl_video"),
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

@dp.callback_query(lambda c: c.data in ["dl_video", "dl_audio", "back", "check_sub"])
async def process_callback(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    if callback.data == "back":
        await callback.message.delete()
        await callback.message.answer(
            "<b>Отменил выбор.</b>\n\n"
            "Пришли новую ссылку или /start"
        )
        await callback.answer()
        return

    if callback.data == "check_sub":
        if await is_subscribed(user_id):
            await callback.message.edit_text(
                "Подписка проверена! Теперь пришли ссылку снова, чтобы скачать."
            )
        else:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Подписаться на канал 1", url="https://t.me/+AfKNOoS0oz82MzJi")],
                [InlineKeyboardButton(text="Подписаться на канал 2", url="https://t.me/jgfdfdgdg")],
                [InlineKeyboardButton(text="Проверить подписку", callback_data="check_sub")]
            ])
            await callback.message.edit_text(
                "Ещё не подписан на все каналы. Подпишись и нажми «Проверить»!",
                reply_markup=keyboard
            )
        await callback.answer()
        return

    choice = callback.data.split("_")[1]
    url = bot.full_url

    await callback.message.edit_text("Скачиваю... ⏳")

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
                await callback.message.edit_text(f"Файл слишком большой ({file_size_mb:.1f} МБ)")
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

    except Exception as e:
        logger.error(f"Ошибка скачивания {url} ({choice}): {str(e)}", exc_info=True)
        await callback.message.edit_text("Не получилось скачать 😔\nПопробуй другую ссылку.")

    await callback.answer()

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
