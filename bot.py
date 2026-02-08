import asyncio
import logging
import tempfile
import os
import time
import asyncpg
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
DATABASE_URL = os.getenv("DATABASE_URL")  # ← из Railway PostgreSQL
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "120"))
REQUEST_LIMIT_PER_MINUTE = int(os.getenv("REQUEST_LIMIT_PER_MINUTE", "5"))

BOT_LINK = "https://t.me/myyvideodownloader_bot"

# Реклама (замени на свой)
AD_TEXT = (
    "Спасибо за использование! ❤️\n"
    "Подпишись на мой канал:\n"
    "👉 @твой_канал"
)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

user_requests = {}

# Глобальный пул подключения
pool = None

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(dsn=DATABASE_URL)
        async with pool.acquire() as conn:
            await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                premium_until BIGINT DEFAULT 0,
                ref_count INTEGER DEFAULT 0,
                ref_id BIGINT,
                total_downloads INTEGER DEFAULT 0,
                last_active BIGINT
            )
            ''')
    
    user_id = message.from_user.id
    async with pool.acquire() as conn:
        await conn.execute('INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING', user_id)

    ref_link = f"{BOT_LINK}?start=ref{user_id}"

    welcome_text = (
        "✨ <b>Привет, легенда скачиваний! 👋</b> ✨\n\n"
        "Я твой личный помощник по видео и музыке 🔥\n"
        "Скачиваю всё самое крутое из:\n"
        "  • TikTok 🎬\n"
        "  • Instagram Reels 📱\n"
        "  • VK клипы 🎥\n\n"
        "<b>Просто пришли ссылку</b> — и я всё сделаю за секунды! 🚀\n\n"
        "Выбирай качество и наслаждайся! 🌟"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Личный кабинет 📊", callback_data="cabinet")],
        [InlineKeyboardButton(text="Пригласить друга и получить бонус 🎁", callback_data="show_ref")]
    ])

    await message.answer(welcome_text, reply_markup=keyboard, disable_web_page_preview=True)

# Остальной код (handle_link, process_callback, show_ref, show_cabinet и т.д.) — оставь как был
# Просто замени sqlite3 на asyncpg запросы (как в is_premium и add_premium_days ниже)

async def is_premium(user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT premium_until FROM users WHERE user_id = $1', user_id)
        if row:
            return row['premium_until'] > time.time()
        return False

async def add_premium_days(user_id, days):
    async with pool.acquire() as conn:
        current = await conn.fetchval('SELECT premium_until FROM users WHERE user_id = $1', user_id)
        current = current or 0
        new_until = max(current, int(time.time())) + days * 86400
        await conn.execute('INSERT INTO users (user_id, premium_until) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET premium_until = $2', user_id, new_until)

async def increment_ref_count(ref_id):
    async with pool.acquire() as conn:
        await conn.execute('UPDATE users SET ref_count = ref_count + 1 WHERE user_id = $1', ref_id)

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
