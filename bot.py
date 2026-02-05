import asyncio  # Это как "таймер" для ожидания
import logging  # Помогает видеть ошибки
import tempfile  # Для временных файлов (как корзина, которая сама чистится)
import yt_dlp   # Инструмент для скачивания видео
from aiogram import Bot, Dispatcher, types  # Основные штуки для бота
from aiogram.filters import CommandStart   # Для команды /start
from aiogram.types import FSInputFile      # Для отправки файлов

# Включи "дневник ошибок"
logging.basicConfig(level=logging.INFO)

# Здесь вставь свой токен от BotFather
API_TOKEN = '7262666625:AAGlvpwAM9DLaRh0t0o7rAr5r6rWc88Ji1g'  # Замени на свой!

# Создай бота и "диспетчера" (как начальник, который раздаёт задания)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Когда пользователь пишет /start
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("Привет! Просто пришли мне ссылку на видео (TikTok, Instagram, YouTube и т.д.)")

# Когда приходит любое сообщение
@dp.message()
async def download_video(message: types.Message):
    url = message.text.strip()  # Возьми текст сообщения и убери пробелы
    if not url.startswith(('http://', 'https://')):  # Проверь, ссылка ли это
        await message.answer("Это не ссылка! Пришли правильную.")
        return  # Закончи, если не ссылка

    await message.answer("Скачиваю... Подожди чуть-чуть!")  # Скажи, что работаешь

    try:  # Попробуй сделать, если ошибка — поймай
        # Настройки для yt-dlp (как рецепт для скачивания)
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',  # Лучшее видео в mp4
            'outtmpl': '%(id)s.%(ext)s',  # Имя файла
            'quiet': True,  # Не болтай много
            'no_warnings': True,  # Без предупреждений
            'noplaylist': True,  # Только одно видео, не плейлист
        }

        # Создай временную папку (как секретное место)
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts['outtmpl'] = f'{tmpdir}/%(id)s.%(ext)s'  # Скачивай туда

            # Скачай видео
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)  # Получи инфу и скачай
                filename = ydl.prepare_filename(info)  # Имя скачанного файла

            # Отправь видео пользователю
            if info.get('duration', 0) > 0:  # Если это видео (есть длительность)
                await message.answer_video(
                    video=FSInputFile(filename),  # Отправь файл
                    caption=f"Готово! Из {info.get('extractor', 'сайта')} - {info.get('title', 'видео')}"
                )
            else:
                await message.answer("Не получилось скачать. Попробуй другую ссылку.")

    except Exception as e:  # Если ошибка
        logging.error(e, exc_info=True)  # Запиши в дневник
        await message.answer(f"Ой, ошибка: {str(e)}. Может, ссылка сломана?")

# Запусти бота
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
