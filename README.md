🎵 AIOGRAM MUSIC & VIDEO DOWNLOADER BOT

Powerful Telegram bot built with *Aiogram 3* for searching, processing, and downloading media from YouTube and TikTok.


✨ FEATURES

–   🔍 *Smart Search:* Find songs on YouTube directly via chat.
–   🎤 *Voice Recognition:* Search for music using voice messages (Google STT).
–   📥 *Link Downloader:* Support for *TikTok*, *YouTube*, and *Shorts*.
–   🌀 *Audio Effects:* Integrated FFmpeg filters:
    *   *Slow + Reverb*
    *   *Nightcore* (Speed up)
    *   *Bass Boost*
    *   *8D Audio*
–   🛡️ *Security:* Auto-ban system for spammers (>5 req/min) and admin protection.
–   💾 *Performance:* LRU Caching for search results and media links.


🛠 TECH STACK

–   *Framework:* Aiogram 3.x
–   *Engine:* yt-dlp, FFmpeg
–   *Speech-to-Text:* SpeechRecognition
–   *Database:* Local file-based (txt) storage


🚀 QUICK START

1. *Clone the Repository:*
git clone https://github.com/cakartamas2010/telegram-musicbot.git
cd telegram-musicbot


2. *Install Dependencies:*
pip install aiogram yt-dlp SpeechRecognition python-dotenv


3. *System Requirements:*
Install FFmpeg and ensure it's in your PATH or project folder.

4. *Configuration:*
Create a .env file in the root directory:
BOTTOKEN=YOURTELEGRAMBOTTOKEN


5. *Run:*
python bot.py



📂 STRUCTURE
– bot.py — Core logic
– temp_music/ — Temporary processing folder
– banned.txt / users.txt — Simple DB files
– log.txt — System logs


📜 LICENSE
Educational purposes only. All rights belong to respective content owners.  
