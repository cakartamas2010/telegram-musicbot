import asyncio
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import speech_recognition as sr
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

# --- 1. ИНИЦИАЛИЗАЦИЯ И ОКРУЖЕНИЕ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("Ошибка: BOT_TOKEN не найден в переменных окружения или файле .env!")
    sys.exit(1)

# Создание папки для временных файлов
TEMP_DIR = Path("temp_music")
TEMP_DIR.mkdir(exist_ok=True)

BANNED_FILE = Path("banned.txt")

# Настройка логирования
logging.basicConfig(
    filename="log.txt",
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    encoding="utf-8",
)

# --- 2. УНИВЕРСАЛЬНЫЙ ПОИСК FFPEG (КОРЕНЬ ПРОЕКТА ИЛИ PATH) ---
def setup_ffmpeg_path():
    current_dir = Path(__file__).resolve().parent
    local_ffmpeg_win = current_dir / "ffmpeg.exe"
    local_ffmpeg_lin = current_dir / "ffmpeg"

    if local_ffmpeg_win.exists():
        ffmpeg_bin_dir = str(current_dir)
        os.environ["PATH"] += os.pathsep + ffmpeg_bin_dir
        logging.info(f"Обнаружен локальный FFmpeg в корне проекта (Windows): {ffmpeg_bin_dir}")
    elif local_ffmpeg_lin.exists():
        ffmpeg_bin_dir = str(current_dir)
        os.environ["PATH"] += os.pathsep + ffmpeg_bin_dir
        os.chmod(local_ffmpeg_lin, 0o755)
        logging.info(f"Обнаружен локальный FFmpeg в корне проекта (Unix): {ffmpeg_bin_dir}")
    else:
        logging.info("Локальный FFmpeg в корне проекта не найден. Используется системный PATH.")

setup_ffmpeg_path()

# Конфигурация администраторов (Замените ID 123456789 на свой реальный Telegram ID)
ADMIN_IDS = [5893041927]

banned_users = set()
request_counts = defaultdict(list)

def load_banned_users():
    if BANNED_FILE.exists():
        try:
            with open(BANNED_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    uid = line.strip()
                    if uid.isdigit():
                        banned_users.add(int(uid))
            logging.info(f"Загружено забаненных пользователей: {len(banned_users)}")
        except Exception as e:
            logging.error(f"Ошибка при загрузке banned.txt: {e}")

def save_banned_users():
    try:
        with open(BANNED_FILE, "w", encoding="utf-8") as f:
            for uid in banned_users:
                f.write(f"{uid}\n")
    except Exception as e:
        logging.error(f"Ошибка при сохранении banned.txt: {e}")

load_banned_users()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# --- 3. MIDDLEWARE ДЛЯ АВТОБАНА И SILENT BAN ---
@router.message.middleware()
async def security_and_flood_middleware(handler, event, data):
    if not isinstance(event, Message):
        return await handler(event, data)

    user_id = event.from_user.id

    if user_id in banned_users:
        logging.info(f"Silent ban сработал для пользователя ID: {user_id}. Сообщение проигнорировано.")
        return

    if user_id in ADMIN_IDS:
        return await handler(event, data)

    now = time.time()
    timestamps = request_counts[user_id]
    timestamps = [t for t in timestamps if now - t < 10.0]
    timestamps.append(now)
    request_counts[user_id] = timestamps

    if len(timestamps) > 6:
        banned_users.add(user_id)
        save_banned_users()
        logging.warning(f"Пользователь ID {user_id} заблокирован автоматически системой антифлуда.")
        return

    return await handler(event, data)


# --- 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ПРОВЕРКИ ССЫЛОК И ЗАПРОСОВ ---
def is_url(text: str) -> bool:
    """Проверяет, является ли текст ссылкой на YouTube или TikTok."""
    t_lower = text.lower()
    return "http://" in t_lower or "https://" in t_lower or "youtu.be" in t_lower or "tiktok.com" in t_lower


def parse_group_query(text: str, is_group: bool):
    """
    Правила для групп и лички:
    - Если это ссылка (YouTube/TikTok), она принимается МГНОВЕННО без ключевых слов.
    - Обычный текст в ЛС обрабатывается напрямую.
    - Текстовый поисковый запрос в группе требует ключевых слов. Если их нет — возвращаем None.
    """
    if not text:
        return None

    text_clean = text.strip()

    # Ссылки обрабатываются всегда без префиксов
    if is_url(text_clean):
        return text_clean

    if not is_group:
        return text_clean

    text_lower = text_clean.lower()
    triggers = ["найди песню", "скачай песню", "найди", "скачай"]

    for trigger in triggers:
        if text_lower.startswith(trigger):
            query = text_clean[len(trigger):].strip()
            return query if query else None

    return None


# --- 5. КОМАНДЫ АДМИНИСТРАТОРА И СТАРТ ---
@router.message(Command("start"))
async def cmd_start(message: Message):
    logging.info(f"Пользователь {message.from_user.id} запустил бота.")
    await message.answer(
        "🎵 Привет! Я музыкальный бот.\n\n"
        "🔗 *Ссылки:* Просто скинь ссылку на трек из *YouTube* или *TikTok* (в ЛС или группу), и я мгновенно достану из нее аудиодорожку!\n"
        "🔎 *Поиск по названию:* \n"
        "• В личных сообщениях — просто напиши название или наговори голосовое.\n"
        "• В группах — начни сообщение со слов: *«найди песню»*, *«скачай песню»*, *«найди»* или *«скачай»* (например: `найди песню Король и Шут`). Права администратора в группе не нужны!"
    , parse_mode="Markdown")


@router.message(Command("reboot"))
async def cmd_reboot(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("❌ У вас нет прав для выполнения этой команды.")

    logging.info(f"Администратор {message.from_user.id} инициировал перезагрузку сервера.")
    await message.answer("🔄 Перезагружаю сервер и обновляю бота...")
    
    await asyncio.sleep(1)
    # Корректный перезапуск текущего python-процесса
    os.execv(sys.executable, [sys.executable] + sys.argv)


@router.message(Command("ban"))
async def cmd_ban(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer("⚠️ Неверный формат. Используйте: `/ban [ID человека]`", parse_mode="Markdown")

    target_id = int(args[1])
    if target_id in ADMIN_IDS:
        return await message.answer("❌ Нельзя забанить администратора!")

    banned_users.add(target_id)
    save_banned_users()
    logging.info(f"Администратор {message.from_user.id} забанил пользователя {target_id}.")
    await message.answer(f"✅ Пользователь с ID `{target_id}` успешно забанен.", parse_mode="Markdown")


# --- 6. ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ ---
@router.message(F.voice)
async def handle_voice_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    is_group = message.chat.type in ["group", "supergroup"]

    status_msg = await message.answer("🎙 Распознаю ваш голос...")

    voice_file = await bot.get_file(message.voice.file_id)
    ogg_path = TEMP_DIR / f"voice_{user_id}_{message.message_id}.ogg"
    wav_path = TEMP_DIR / f"voice_{user_id}_{message.message_id}.wav"

    try:
        await bot.download(voice_file, destination=ogg_path)

        import subprocess
        conversion_cmd = [
            "ffmpeg", "-i", str(ogg_path), "-ar", "16000", "-ac", "1", str(wav_path), "-y", "-loglevel", "quiet"
        ]
        process = await asyncio.create_subprocess_exec(*conversion_cmd)
        await process.wait()

        if not wav_path.exists():
            raise Exception("Не удалось конвертировать аудио через FFmpeg.")

        r = sr.Recognizer()
        with sr.AudioFile(str(wav_path)) as source:
            audio_data = r.record(source)
            raw_query = r.recognize_google(audio_data, language="ru-RU")

        query = parse_group_query(raw_query, is_group)
        if not query:
            await status_msg.delete()
            return

        await status_msg.edit_text(f'🔎 Распознано: *"{query}"*. Ищу треки...', parse_mode="Markdown")
        await process_query_router(message, query, state)

    except sr.UnknownValueError:
        await status_msg.edit_text("❌ Не удалось разобрать слова в голосовом сообщении. Попробуйте еще раз.")
    except sr.RequestError as e:
        logging.error(f"Ошибка сервиса распознавания речи: {e}")
        await status_msg.edit_text("❌ Ошибка связи со службой распознавания речи.")
    except Exception as e:
        logging.error(f"Ошибка обработки голосового сообщения: {e}")
        await status_msg.edit_text("❌ Произошла ошибка при обработке голосового сообщения.")
    finally:
        for p in [ogg_path, wav_path]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass


# --- 7. ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ И ССЫЛОК ---
@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: Message, state: FSMContext):
    raw_text = message.text.strip()
    is_group = message.chat.type in ["group", "supergroup"]

    query = parse_group_query(raw_text, is_group)
    if not query:
        return

    logging.info(f"Запрос от пользователя {message.from_user.id} (группа: {is_group}): {query}")
    await process_query_router(message, query, state)


async def process_query_router(message: Message, query: str, state: FSMContext):
    """Определяет, прямая ли это ссылка (YouTube/TikTok) или текстовый поиск."""
    if is_url(query):
        # Если это прямая ссылка, пропускаем этап выбора из 5 треков и сразу предлагаем эффекты
        status_msg = await message.answer("⏳ Анализирую ссылку...", parse_mode="Markdown")
        
        ydl_opts = {"extract_flat": False, "quiet": True, "no_warnings": True}
        try:
            loop = asyncio.get_running_loop()
            def fetch_meta():
                with YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(query, download=False)

            info = await loop.run_in_executor(None, fetch_meta)
            title = info.get("title", "Аудиозапись из ссылки")
            real_url = info.get("webpage_url") or query

            await state.update_data(selected_url=real_url, selected_title=title)
            await status_msg.delete()

            effects_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎶 Original", callback_data="fx_original")],
                [InlineKeyboardButton(text="🌊 Slow + Reverb", callback_data="fx_slowreverb")],
                [InlineKeyboardButton(text="⚡ Nightcore", callback_data="fx_nightcore")],
                [InlineKeyboardButton(text="🔊 Bass Boost", callback_data="fx_bassboost")],
                [InlineKeyboardButton(text="🌌 8D Audio", callback_data="fx_8d")]
            ])

            await message.answer(
                f'🎛 Найдено по ссылке: *"{title}"*\n\nВыбери эффект:',
                reply_markup=effects_keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logging.error(f"Ошибка обработки ссылки '{query}': {e}")
            await status_msg.edit_text("❌ Не удалось получить данные по этой ссылке. Убедитесь, что она корректна.")
    else:
        # Иначе запускаем стандартный поиск по названию (5 вариантов)
        await process_search_query(message, query, state)


# --- 8. ПОИСК ТРЕКОВ НА YOUTUBE (ПО НАЗВАНИЮ) ---
async def process_search_query(message: Message, query: str, state: FSMContext):
    status_msg = await message.answer(f'🔎 Ищу 5 лучших вариантов для: "{query}"...')

    ydl_opts = {
        "extract_flat": True,
        "max_downloads": 5,
        "default_search": "ytsearch5",
        "quiet": True,
        "no_warnings": True,
    }

    try:
        loop = asyncio.get_running_loop()
        def search_yt():
            with YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False)

        info = await loop.run_in_executor(None, search_yt)
        entries = info.get("entries", [])

        if not entries:
            return await status_msg.edit_text("😔 По вашему запросу ничего не найдено.")

        buttons = []
        track_storage = {}

        for idx, entry in enumerate(entries[:5], start=1):
            title = entry.get("title", f"Трек {idx}")
            url = entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}"
            
            cb_key = f"tr_{message.from_user.id}_{int(time.time())}_{idx}"
            track_storage[cb_key] = {"url": url, "title": title}
            
            btn_title = title if len(title) <= 42 else title[:39] + "..."
            buttons.append([InlineKeyboardButton(text=f"{idx}. {btn_title}", callback_data=cb_key)])

        current_data = await state.get_data()
        stored_tracks = current_data.get("tracks", {})
        stored_tracks.update(track_storage)
        await state.update_data(tracks=stored_tracks)

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await status_msg.edit_text(
            f'🔎 Результаты по запросу: *"{query}"*\nВыберите нужный трек из списка:',
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"Ошибка при поиске YouTube для запроса '{query}': {e}")
        await status_msg.edit_text("❌ Произошла ошибка при поиске треков. Попробуйте другой запрос.")


# --- 9. ВЫБОР ТРЕКА ИЗ СПИСКА -> ВЫБОР ЭФФЕКТОВ ---
@router.callback_query(F.data.startswith("tr_"))
async def handle_track_selection(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tracks = data.get("tracks", {})
    
    track_info = tracks.get(callback.data)
    if not track_info:
        return await callback.answer("⚠️ Ссылка устарела. Сделайте поиск заново.", show_alert=True)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await state.update_data(selected_url=track_info["url"], selected_title=track_info["title"])

    effects_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎶 Original", callback_data="fx_original")],
        [InlineKeyboardButton(text="🌊 Slow + Reverb", callback_data="fx_slowreverb")],
        [InlineKeyboardButton(text="⚡ Nightcore", callback_data="fx_nightcore")],
        [InlineKeyboardButton(text="🔊 Bass Boost", callback_data="fx_bassboost")],
        [InlineKeyboardButton(text="🌌 8D Audio", callback_data="fx_8d")]
    ])

    title = track_info["title"]
    await callback.message.answer(
        f'🎛 Трек: *"{title}"*\n\nВыбери эффект:',
        reply_markup=effects_keyboard,
        parse_mode="Markdown"
    )


# --- 10. ВЫБОР ЭФФЕКТА -> СКАЧИВАНИЕ И ОТПРАВКА АУДИО ---
@router.callback_query(F.data.startswith("fx_"))
async def handle_effect_selection(callback: CallbackQuery, state: FSMContext):
    effect_type = callback.data.split("_")[1]
    data = await state.get_data()
    
    url = data.get("selected_url")
    title = data.get("selected_title")

    if not url or not title:
        return await callback.answer("⚠️ Данные сессии устарели. Повторите запрос.", show_alert=True)

    try:
        await callback.message.delete()
    except Exception:
        pass

    progress_msg = await callback.message.answer(f'⏳ Скачиваю и применяю эффект... Пожалуйста, подождите.', parse_mode="Markdown")

    asyncio.create_task(process_and_send_audio(callback.bot, callback.message.chat.id, progress_msg, url, title, effect_type))


async def process_and_send_audio(bot_instance: Bot, chat_id: int, progress_msg: Message, url: str, title: str, effect_type: str):
    unique_id = f"{int(time.time())}_{os.urandom(3).hex()}"
    raw_output_template = str(TEMP_DIR / f"raw_{unique_id}.%(ext)s")

    audio_filter_arg = "loudnorm=I=-16:TP=-1.5:LRA=11"
    
    if effect_type == "slowreverb":
        audio_filter_arg = "atempo=0.85,aecho=0.8:0.88:60:0.4,loudnorm=I=-16:TP=-1.5:LRA=11"
    elif effect_type == "nightcore":
        audio_filter_arg = "asetrate=44100*1.25,aresample=44100,atempo=1.0,loudnorm=I=-16:TP=-1.5:LRA=11"
    elif effect_type == "bassboost":
        audio_filter_arg = "equalizer=f=100:width_type=h:width=200:g=8,loudnorm=I=-16:TP=-1.5:LRA=11"
    elif effect_type == "8d":
        audio_filter_arg = "pan=stereo|c0=c0|c1=c1,apulsator=mode=sine:hz=0.12:amount=0.8,loudnorm=I=-16:TP=-1.5:LRA=11"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": raw_output_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "postprocessor_args": [
            "-ar", "44100",
            "-af", audio_filter_arg
        ],
        "quiet": True,
        "no_warnings": True,
    }

    final_file = None
    try:
        loop = asyncio.get_running_loop()
        def download_worker():
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                downloaded_file = ydl.prepare_filename(info_dict)
                base, _ = os.path.splitext(downloaded_file)
                return base + ".mp3"

        mp3_filepath_str = await loop.run_in_executor(None, download_worker)
        final_file = Path(mp3_filepath_str)

        if not final_file.exists():
            possible_files = list(TEMP_DIR.glob(f"*{unique_id}*.mp3"))
            if possible_files:
                final_file = possible_files[0]

        if final_file and final_file.exists():
            await progress_msg.edit_text(f'🚀 Отправка файла...', parse_mode="Markdown")
            audio_input = FSInputFile(str(final_file))
            
            await bot_instance.send_audio(
                chat_id=chat_id,
                audio=audio_input,
                title=title,
                performer="Music Bot"
            )
            await progress_msg.delete()
            logging.info(f"Трек '{title}' с эффектом '{effect_type}' успешно отправлен.")
        else:
            await progress_msg.edit_text(f'❌ Не удалось сформировать аудиофайл.', parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Ошибка при обработке трека '{title}' с эффектом '{effect_type}': {e}")
        try:
            await progress_msg.edit_text(f'❌ Произошла ошибка при скачивании или обработке аудио.', parse_mode="Markdown")
        except Exception:
            pass
    finally:
        for temp_file in TEMP_DIR.glob(f"*{unique_id}*"):
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass


# --- 11. ЗАПУСК БОТА ---
async def main():
    logging.info("Музыкальный Telegram-бот успешно запущен и ожидает сообщений.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен пользователем.")