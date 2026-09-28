import os
import sys
import json
import uuid
import asyncio
import gc
from datetime import datetime
from collections import OrderedDict

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, FSInputFile, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage

import speech_recognition as sr
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    print("❌ ОШИБКА: Токен бота не найден! Проверь файл .env.")
    sys.exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

ADMIN_IDS = [5893041927]  # Ваш ID для защиты от банов

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_TEMP_DIR = os.path.join(BASE_DIR, "temp_music")
LOG_FILE = os.path.join(BASE_DIR, "log.txt")
BAN_FILE = os.path.join(BASE_DIR, "banned.txt")
USERS_FILE = os.path.join(BASE_DIR, "users.txt")
FFMPEG_PATH = BASE_DIR

os.makedirs(DOWNLOAD_TEMP_DIR, exist_ok=True)

def clean_temp_dir():
    if not os.path.exists(DOWNLOAD_TEMP_DIR):
        return
    for f in os.listdir(DOWNLOAD_TEMP_DIR):
        try:
            os.remove(os.path.join(DOWNLOAD_TEMP_DIR, f))
        except Exception as e:
            log_event(f"ОШИБКА ОЧИСТКИ ТЕМП-ДИРЕКТОРИИ: {e}")

clean_temp_dir()

# LRU Кэш
class LimitedCache(OrderedDict):
    def __init__(self, maxsize=30, *args, **kwargs):
        self.maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]

search_cache = LimitedCache(maxsize=30)
link_cache = LimitedCache(maxsize=30)
user_request_history = {} 

BANNED_USERNAMES = set()
BANNED_IDS = set()
ALL_USERS = set() 

STOP_WORDS = {"привет", "салам", "здорово", "хай", "hello", "как дела", "спасибо", "пока"}
GROUP_COMMANDS = ["найди песню", "скачай песню", "найди", "скачай"]

def load_bans_and_users():
    global BANNED_IDS, BANNED_USERNAMES, ALL_USERS
    if os.path.exists(BAN_FILE):
        try:
            with open(BAN_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    item = line.strip().lower()
                    if item:
                        if item.isdigit():
                            BANNED_IDS.add(int(item))
                        else:
                            BANNED_USERNAMES.add(item)
        except Exception as e:
            log_event(f"ОШИБКА ЗАГРУЗКИ BANS: {e}")
    
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                ALL_USERS = {int(line.strip()) for line in f if line.strip().isdigit()}
        except Exception as e:
            log_event(f"ОШИБКА ЗАГРУЗКИ USERS: {e}")

def save_bans():
    try:
        with open(BAN_FILE, "w", encoding="utf-8") as f:
            for b_id in BANNED_IDS:
                f.write(f"{b_id}\n")
            for b_name in BANNED_USERNAMES:
                f.write(f"{b_name}\n")
    except Exception as e:
        log_event(f"ОШИБКА СОХРАНЕНИЯ BANS: {e}")

def add_user_to_all_users(user_id):
    if user_id not in ALL_USERS:
        ALL_USERS.add(user_id)
        try:
            with open(USERS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{user_id}\n")
        except Exception as e:
            log_event(f"ОШИБКА СОХРАНЕНИЯ ЮЗЕРА: {e}")

load_bans_and_users()

def log_event(text):
    msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n"
    print(msg.strip())
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass

def is_banned(u_id, u_name):
    if u_id in ADMIN_IDS:
        return False
    if u_id in BANNED_IDS:
        return True
    if u_name and u_name.lower() in BANNED_USERNAMES:
        return True
    return False

async def check_auto_ban(u_id, u_name, c_id):
    now = asyncio.get_event_loop().time()
    if u_id not in user_request_history:
        user_request_history[u_id] = []
    user_request_history[u_id] = [t for t in user_request_history[u_id] if now - t < 60]
    user_request_history[u_id].append(now)
    
    if len(user_request_history[u_id]) > 5:
        BANNED_IDS.add(u_id)
        if u_name:
            BANNED_USERNAMES.add(u_name.lower())
        save_bans()
        log_event(f"🚨 АВТО-БАН: ID {u_id} ЗАБАНЕН ЗА СПАМ (>5 зап/мин)")
        try:
            await bot.send_message(c_id, "🚫 Вы заблокированы за спам.")
        except Exception:
            pass
        return True
    return False

async def get_search_results(query, max_results=5):
    log_event(f'ПОИСК YOUTUBE: "{query}"')
    cmd = [
        "yt-dlp",
        f"ytsearch10:{query}",
        "--dump-single-json",
        "--flat-playlist",
        "--no-check-certificates"
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            proc.kill()
            log_event("ОШИБКА ПОИСКА: Таймаут yt-dlp")
            return []

        if not stdout:
            return []
        data = json.loads(stdout.decode('utf-8', errors='ignore'))
        entries = data.get("entries", [data]) if data else []
        results = []
        for e in entries:
            if not e: continue
            dur = e.get("duration")
            if dur and dur > 1200:
                continue
            title = e.get("title", "No Name")
            url = e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={e.get('id')}"
            dur_str = f"{int(dur)//60}:{int(dur)%60:02d}" if dur else ""
            results.append({"title": title, "url": url, "duration": dur_str})
            if len(results) == max_results: break
        return results
    except Exception as err:
        log_event(f"ОШИБКА ПОИСКА: {err}")
        return []

async def get_media_duration(url):
    cmd = ["yt-dlp", "--dump-single-json", "--no-playlist", "--no-check-certificates", url]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if not stdout:
            return 0
        data = json.loads(stdout.decode('utf-8', errors='ignore'))
        return data.get("duration", 0)
    except Exception: 
        return 0

async def download_media(url, f_prefix, is_video=False):
    log_event(f"СКАЧИВАНИЕ ({'ВИДЕО' if is_video else 'АУДИО'}): {url}")
    uniq_id = uuid.uuid4().hex[:6]
    full_prefix = f"{f_prefix}_{uniq_id}"
    out = os.path.join(DOWNLOAD_TEMP_DIR, f"{full_prefix}_%(title)s.%(ext)s")
    
    cmd = ["yt-dlp", "--no-playlist", "--no-check-certificates", "-o", out]
    
    if is_video:
        cmd.extend(["-f", "b[filesize<50M][ext=mp4]/best[ext=mp4]/best"])
    else:
        cmd.extend([
            "-x", 
            "--audio-format", "mp3", 
            "--audio-quality", "0"
        ])
        
    if "tiktok.com" not in url.lower():
        cmd.extend(["--extractor-args", "youtube:player_client=android"])
    
    if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
        cmd.extend(["--ffmpeg-location", FFMPEG_PATH])
    cmd.append(url)
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)
        if os.path.exists(DOWNLOAD_TEMP_DIR):
            files = [os.path.join(DOWNLOAD_TEMP_DIR, f) for f in os.listdir(DOWNLOAD_TEMP_DIR) if f.startswith(full_prefix)]
            if files: return files[0]
    except asyncio.TimeoutError:
        proc.kill()
        log_event("ОШИБКА СКАЧИВАНИЯ: Превышено время ожидания yt-dlp")
    except Exception as err:
        log_event(f"ОШИБКА СКАЧИВАНИЯ: {err}")
    return None

async def apply_audio_effect(input_path, effect_type):
    if effect_type == "orig":
        return input_path

    output_path = input_path.replace(".mp3", f"_{effect_type}.mp3")
    ffmpeg_bin = "ffmpeg"
    if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
        possible_path = os.path.join(FFMPEG_PATH, "ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
        if os.path.exists(possible_path):
            ffmpeg_bin = possible_path

    filter_str = ""
    if effect_type == "slow":
        filter_str = "atempo=0.85,aecho=0.8:0.88:60:0.4"
    elif effect_type == "nightcore":
        filter_str = "asetrate=44100*1.2,atempo=1/1.2"
    elif effect_type == "bass":
        filter_str = "bass=g=10:f=110:w=0.6,volume=0.85"
    elif effect_type == "8d":
        filter_str = "apulsator=mode=sine:hz=0.15"

    cmd = [ffmpeg_bin, "-y", "-i", input_path]
    if filter_str:
        cmd.extend(["-filter:a", filter_str])
    cmd.extend(["-b:a", "320k", output_path])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.communicate(), timeout=40)
        if os.path.exists(output_path):
            return output_path
    except Exception as err:
        log_event(f"ОШИБКА ОБРАБОТКИ ФАЙЛА ({effect_type}): {err}")
    
    return input_path

# --- ОСНОВНЫЕ ХЭНДЛЕРЫ ---

@dp.message(F.text == '/start')
async def send_welcome(m: Message):
    add_user_to_all_users(m.from_user.id)
    if is_banned(m.from_user.id, m.from_user.username): return
    log_event(f"КОМАНДА /start от ID {m.from_user.id}")
    await m.answer(
        "Салам! 👋 Я твой музыкальный бот.\n\n"
        "Вот что я умею:\n"
        "🎵 Искать музыку из YouTube\n"
        "🎤 Понимать голосовые сообщения\n"
        "📥 Скачивать видео или музыку по ссылке из TikTok/YouTube\n"
        "👥 Работать в группах по запросу «найди песню» или «скачай песню»\n\n"
        "Просто напиши название, отправь голосовое или вставь ссылку!",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(F.voice)
async def handle_voice_message(m: Message):
    add_user_to_all_users(m.from_user.id)
    u_id = m.from_user.id
    c_id = m.chat.id
    u_name = m.from_user.username
    is_group = m.chat.type in ['group', 'supergroup']
    if is_banned(u_id, u_name): return
    if await check_auto_ban(u_id, u_name, c_id): return
    
    f_info = await bot.get_file(m.voice.file_id)
    temp_media_filename = f"media_{c_id}_{m.message_id}_{uuid.uuid4().hex[:6]}.ogg"
    file_path = os.path.join(DOWNLOAD_TEMP_DIR, temp_media_filename)
    
    try: 
        await bot.download_file(f_info.file_path, file_path)
    except Exception as err:
        log_event(f"ОШИБКА ЗАГРУЗКИ ГОЛОСОВОГО: {err}")
        await m.answer("❌ Не удалось загрузить голосовое сообщение.")
        return
    
    status_msg = await m.answer("🎤 Распознаю голос...")
    
    txt = await recognize_voice_message(file_path)
    try:
        if os.path.exists(file_path): os.remove(file_path)
    except Exception: pass
    
    if not txt:
        if not is_group: 
            await bot.edit_message_text("❌ Не удалось распознать голос.", chat_id=c_id, message_id=status_msg.message_id)
        else:
            try: await bot.delete_message(c_id, status_msg.message_id)
            except Exception: pass
        return
        
    txt_lower = txt.lower()
    query = ""
    if is_group:
        has_cmd = False
        for cmd in GROUP_COMMANDS:
            if txt_lower.startswith(cmd):
                has_cmd = True
                query = txt_lower.replace(cmd, "", 1).strip()
                break
        if not has_cmd: 
            try: await bot.delete_message(c_id, status_msg.message_id)
            except Exception: pass
            return
    else: 
        query = txt
        
    if not query: 
        try: await bot.delete_message(c_id, status_msg.message_id)
        except Exception: pass
        return
        
    await status_msg.edit_text(f'🎤 Ищу по голосу: "{txt}"...')
    await process_query(c_id, status_msg.message_id, query)

async def recognize_voice_message(file_path):
    log_event("РАСПОЗНАВАНИЕ ГОЛОСА: Начато")
    r = sr.Recognizer()
    
    wav_path = os.path.join(DOWNLOAD_TEMP_DIR, f"voice_temp_{uuid.uuid4().hex[:6]}.wav")
    ffmpeg_bin = "ffmpeg"
    if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
        possible_path = os.path.join(FFMPEG_PATH, "ffmpeg.exe" if os.name == 'nt' else "ffmpeg")
        if os.path.exists(possible_path):
            ffmpeg_bin = possible_path
    cmd = [ffmpeg_bin, "-y", "-i", file_path, wav_path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.communicate(), timeout=15)
        
        def _recognize():
            with sr.AudioFile(wav_path) as source:
                audio_data = r.record(source)
                return r.recognize_google(audio_data, language="ru-RU")
            
        text = await asyncio.to_thread(_recognize)
        try: os.remove(wav_path)
        except Exception: pass
        log_event(f'РАСПОЗНАВАНИЕ ГОЛОСА УСПЕШНО: "{text}"')
        return text
    except Exception as err:
        log_event(f"ОШИБКА РАСПОЗНАВАНИЯ ГОЛОСА: {err}")
        try:
            if os.path.exists(wav_path): os.remove(wav_path)
        except Exception: pass
        return None

@dp.message(F.text)
async def handle_text(m: Message):
    add_user_to_all_users(m.from_user.id)
    u_id = m.from_user.id
    c_id = m.chat.id
    u_name = m.from_user.username
    is_group = m.chat.type in ['group', 'supergroup']
    if is_banned(u_id, u_name): return
    if await check_auto_ban(u_id, u_name, c_id): return
    
    q = m.text.strip()
    q_lower = q.lower()
    
    if q_lower in STOP_WORDS:
        if not is_group:
            await m.answer("Салам! 👋 Напиши название песни, отправь голосовое или пришли ссылку!", reply_markup=ReplyKeyboardRemove())
        return
        
    if "tiktok.com" in q_lower or "youtube.com/watch" in q_lower or "youtu.be" in q_lower or "youtube.com/shorts" in q_lower:
        dur = await get_media_duration(q)
        if dur > 1200:
            await m.answer("⚠️ Видео длиннее 20 минут не поддерживаются.")
            return
            
        msg = await m.answer("🔗 Ссылка принята! Что именно скачать?")
        link_key = f"{c_id}_{msg.message_id}"
        link_cache[link_key] = q
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🎵 Аудио (MP3)", callback_data=f"get_audio_{msg.message_id}")
        builder.button(text="🎬 Видео (MP4)", callback_data=f"get_video_{msg.message_id}")
        builder.adjust(2)
        
        await bot.edit_message_reply_markup(chat_id=c_id, message_id=msg.message_id, reply_markup=builder.as_markup())
        return

    query = ""
    if is_group:
        has_cmd = False
        for cmd in GROUP_COMMANDS:
            if q_lower.startswith(cmd):
                has_cmd = True
                query = q[len(cmd):].strip()
                break
        if not has_cmd: return
    else: 
        query = q
    
    if not query: return
    log_event(f"ЗАПРОС: \"{query}\" от ID {u_id}")
    msg = await m.answer("🔎 Ищу...")
    await process_query(c_id, msg.message_id, query)

@dp.callback_query(F.data.startswith("get_"))
async def handle_link_format_choice(call: CallbackQuery):
    u_id = call.from_user.id
    c_id = call.message.chat.id
    u_name = call.from_user.username
    if is_banned(u_id, u_name): return
        
    try: await call.answer()
    except Exception: pass
        
    parts = call.data.split("_")
    mode = parts[1]
    orig_msg_id = parts[2]
    
    link_key = f"{c_id}_{orig_msg_id}"
    url = link_cache.get(link_key)
    
    if not url:
        try: await bot.edit_message_text("❌ Ссылка устарела. Отправь её заново.", chat_id=c_id, message_id=call.message.message_id)
        except Exception: pass
        return

    is_vid = (mode == "video")
    type_text = "видео 🎬" if is_vid else "аудио 🎵"
    
    try: await bot.edit_message_text(f"📥 Скачиваю {type_text}...", chat_id=c_id, message_id=call.message.message_id, reply_markup=None)
    except Exception: pass

    pfx = f"{c_id}_{orig_msg_id}"
    f_path = await download_media(url, pfx, is_video=is_vid)
    
    if f_path and os.path.exists(f_path):
        try: await bot.edit_message_text("🚀 Отправляю...", chat_id=c_id, message_id=call.message.message_id)
        except Exception: pass
            
        media_file = FSInputFile(f_path)
        
        if is_vid:
            await bot.send_video(c_id, media_file)
        else:
            await bot.send_audio(c_id, media_file)
            
        try: os.remove(f_path)
        except Exception: pass
        
        try: await bot.delete_message(c_id, call.message.message_id)
        except Exception: pass
            
        link_cache.pop(link_key, None)
        gc.collect()
    else:
        try: await bot.edit_message_text("❌ Не удалось скачать файл по ссылке.", chat_id=c_id, message_id=call.message.message_id)
        except Exception: pass

@dp.callback_query(F.data.startswith("dl_"))
async def handle_track_selection(call: CallbackQuery):
    u_id = call.from_user.id
    c_id = call.message.chat.id
    u_name = call.from_user.username
    if is_banned(u_id, u_name): return
    
    try: await call.answer()
    except Exception: pass

    parts = call.data.split("_")
    track_idx = int(parts[1])
    orig_msg_id = parts[2]

    cache_key = f"{c_id}_{orig_msg_id}"
    res = search_cache.get(cache_key)
    if not res:
        try: await bot.edit_message_text("❌ Результаты поиска устарели. Повтори поиск.", chat_id=c_id, message_id=call.message.message_id)
        except Exception: pass
        return
    
    track = res[track_idx]
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎵 Оригинал", callback_data=f"remix_orig_{track_idx}_{orig_msg_id}")
    builder.button(text="🌌 Slow + Reverb", callback_data=f"remix_slow_{track_idx}_{orig_msg_id}")
    builder.button(text="⚡ Nightcore", callback_data=f"remix_nightcore_{track_idx}_{orig_msg_id}")
    builder.button(text="🔊 Bass Boost", callback_data=f"remix_bass_{track_idx}_{orig_msg_id}")
    builder.button(text="🌀 8D Audio", callback_data=f"remix_8d_{track_idx}_{orig_msg_id}")
    builder.adjust(2, 2, 1)

    try:
        await bot.edit_message_text(
            text=f"📌 Трек: <b>{track['title']}</b>\n\nВыбери вариант обработки:",
            chat_id=c_id,
            message_id=call.message.message_id,
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception: pass

@dp.callback_query(F.data.startswith("remix_"))
async def handle_remix_choice(call: CallbackQuery):
    u_id = call.from_user.id
    c_id = call.message.chat.id
    u_name = call.from_user.username
    if is_banned(u_id, u_name): return
    
    try: await call.answer()
    except Exception: pass

    parts = call.data.split("_")
    effect_type = parts[1]
    track_idx = int(parts[2])
    orig_msg_id = parts[3]

    cache_key = f"{c_id}_{orig_msg_id}"
    res = search_cache.get(cache_key)
    if not res:
        try: await bot.edit_message_text("❌ Результаты устарели. Повтори поиск.", chat_id=c_id, message_id=call.message.message_id)
        except Exception: pass
        return
    
    track = res[track_idx]

    try:
        await bot.edit_message_text(
            text="📥 Скачиваю и обрабатываю...",
            chat_id=c_id,
            message_id=call.message.message_id,
            reply_markup=None
        )
    except Exception: pass

    pfx = f"{c_id}_{orig_msg_id}"
    f_path = await download_media(track['url'], pfx, is_video=False)
    
    if f_path and os.path.exists(f_path):
        processed_path = await apply_audio_effect(f_path, effect_type)
        
        try: await bot.edit_message_text(text="🚀 Отправляю трек...", chat_id=c_id, message_id=call.message.message_id)
        except Exception: pass

        # Использование чистого названия песни без префиксов
        clean_title = f"{track['title']}.mp3"

        audio_file = FSInputFile(processed_path, filename=clean_title)
        await bot.send_audio(c_id, audio_file, title=track['title'])
        
        try: 
            if os.path.exists(f_path): os.remove(f_path)
            if os.path.exists(processed_path) and processed_path != f_path: os.remove(processed_path)
        except Exception: pass
            
        try: 
            await bot.delete_message(c_id, call.message.message_id)
        except Exception: pass
            
        search_cache.pop(cache_key, None)
        gc.collect()
    else:
        try: await bot.edit_message_text(text="❌ Ошибка скачивания трека.", chat_id=c_id, message_id=call.message.message_id)
        except Exception: pass

async def process_query(c_id, msg_id, q):
    res = await get_search_results(q)
    if not res:
        await bot.edit_message_text("Ничего не найдено (или все результаты длиннее 20 минут).", chat_id=c_id, message_id=msg_id)
        return
    
    search_cache[f"{c_id}_{msg_id}"] = res
    builder = InlineKeyboardBuilder()
    for idx, item in enumerate(res):
        dur = f" [{item['duration']}]" if item['duration'] else ""
        builder.button(text=f"{idx+1}. {item['title'][:35]}...{dur}", callback_data=f"dl_{idx}_{msg_id}")
    builder.adjust(1)
    await bot.edit_message_text("Выбери трек:", chat_id=c_id, message_id=msg_id, reply_markup=builder.as_markup())

async def main():
    log_event("=== СЕРВЕР ЗАПУЩЕН ===")
    
    while True:
        try:
            try:
                await bot.delete_webhook(drop_pending_updates=True)
            except Exception:
                pass
            
            log_event("🔄 Запуск пуллинга сообщений...")
            await dp.start_polling(bot)
            
        except Exception as e:
            log_event(f"💥 СЕТЕВАЯ ОШИБКА ИЛИ ОБРЫВ СВЯЗИ: {e}")
            log_event("⏳ Переподключение через 3 секунды...")
            await asyncio.sleep(3)
        except KeyboardInterrupt:
            log_event("=== СЕРВЕР ОСТАНОВЛЕН ПОЛЬЗОВАТЕЛЕМ ===")
            break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log_event("=== СЕРВЕР ОСТАНОВЛЕН ===")
    except Exception as e:
        log_event(f"💥 ФАТАЛЬНАЯ ОШИБКА ПРИЛОЖЕНИЯ: {e}")
        print(f"\n[ФАТАЛЬНАЯ ОШИБКА]: {e}")
    finally:
        input("\n[ПРОЦЕСС ЗАВЕРШЕН] Нажмите Enter для выхода...")