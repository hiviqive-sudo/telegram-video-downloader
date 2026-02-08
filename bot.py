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
DATABASE_URL = os.getenv("DATABASE_URL")  # ← автоматически добавлено Railway
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

# Глобальный пул подключения к базе
pool = None

async def init_db():
    global pool
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

# Запускаем подключение к базе один раз при старте
asyncio.create_task(init_db())

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

async def increment_download_count(user_id):
    now = int(time.time())
    async with pool.acquire() as conn:
        await conn.execute('UPDATE users SET total_downloads = total_downloads + 1, last_active = $1 WHERE user_id = $2', now, user_id)

async def get_user_stats(user_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow('SELECT premium_until, ref_count, total_downloads, last_active FROM users WHERE user_id = $1', user_id)
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
            await increment_ref_count(ref_id)
            await add_premium_days(ref_id, 10)
            await bot.send_message(ref_id, "🎉 Твой друг перешёл по реферальной ссылке! Тебе +10 дней премиум!")
    await cmd_start(message)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
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

# Остальные функции (handle_link, process_callback, show_ref, show_cabinet и т.д.) — такие же, как в предыдущей версии
# Просто замени sqlite3 на asyncpg запросы (как в is_premium и add_premium_days выше)

# Пример show_cabinet
@dp.callback_query(lambda c: c.data == "cabinet")
async def show_cabinet(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    premium_days, ref_count, total_downloads, last_active = await get_user_stats(user_id)

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

# ... (остальной код — handle_link, process_callback и т.д. — оставь как был)

async def main():
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
