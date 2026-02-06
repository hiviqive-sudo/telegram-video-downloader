 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/bot.py b/bot.py
index 80180ce179e5c7e5dfa870bc9754163e10cc19bc..6d631b01d781904bff32e8629cb420a8e1b2b635 100644
--- a/bot.py
+++ b/bot.py
@@ -15,106 +15,109 @@ logging.basicConfig(
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
 
 bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
 dp = Dispatcher()
 
 user_requests = {}
 
 @dp.message(CommandStart())
 async def cmd_start(message: types.Message):
     await message.answer(
         "<b>Привет! 👋</b>\n\n"
         "Скачиваю видео и аудио из:\n"
         "• TikTok\n"
-        "• Instagram Reels\n\n"
+        "• Instagram Reels\n"
+        "• VK Клипы/Видео\n"
+        "• YouTube Shorts/Видео\n\n"
         "<b>Пришли ссылку</b> — выбери, что скачать!"
     )
 
 @dp.message(Command("help"))
 async def cmd_help(message: types.Message):
     await message.answer(
         "<b>Как пользоваться</b>\n\n"
-        "1. Пришли ссылку на видео/клип из TikTok или Instagram Reels\n"
+        "1. Пришли ссылку на видео/клип из TikTok, Instagram Reels, VK или YouTube\n"
         "2. Выбери «Видео» или «Аудио»\n"
         "3. Жди — бот пришлёт файл\n\n"
         f"Лимит размера: {MAX_FILE_SIZE_MB} МБ\n"
         "Если не скачивается — попробуй другую ссылку."
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
-            if "tiktok" not in extractor and "instagram" not in extractor:
-                await message.answer("Поддерживаю только TikTok и Instagram Reels. Попробуй другую ссылку.")
+            supported_extractors = ("tiktok", "instagram", "youtube", "vk")
+            if not any(name in extractor for name in supported_extractors):
+                await message.answer("Поддерживаю только TikTok, Instagram Reels, VK и YouTube. Попробуй другую ссылку.")
                 return
 
             title = info.get("title", "Без названия")
             uploader = info.get("uploader", "Автор неизвестен")
             duration = info.get("duration", 0)
             duration_str = f"{int(duration) // 60:02d}:{int(duration) % 60:02d}" if duration and duration > 0 else "—"
             thumbnail = info.get("thumbnail")
 
             bot.full_url = url
 
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
                 f"Источник: {extractor.upper()}\n\n"
@@ -139,64 +142,68 @@ async def handle_link(message: types.Message):
         elif "ffmpeg" in error_msg:
             error_text = "Ошибка: не удалось скачать (ffmpeg не установлен)"
         else:
             error_text = "Не получилось скачать 😔\nПопробуй другую ссылку."
 
         await message.answer(error_text)
 
 @dp.callback_query(lambda c: c.data in ["dl_video", "dl_audio", "back"])
 async def process_callback(callback: types.CallbackQuery):
     if callback.data == "back":
         await callback.message.delete()
         await callback.message.answer(
             "<b>Отменил выбор.</b>\n\n"
             "Пришли новую ссылку или /start"
         )
         await callback.answer()
         return
 
     choice = callback.data.split("_")[1]
     url = bot.full_url
 
     await callback.message.edit_caption(caption=f"Скачиваю {choice}... ⏳", reply_markup=None)
 
     try:
         if choice == "video":
-            format_str = "bestvideo[ext=mp4]/best[ext=mp4]/best"
+            format_str = "bv*+ba/best"
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
+            "merge_output_format": "mp4",
+            "postprocessors": [
+                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
+            ],
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
 
EOF
)
