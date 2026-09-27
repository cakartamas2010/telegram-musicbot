  # 🎵 Aiogram Music & Video Downloader Bot

Powerful Telegram bot built with *Aiogram 3* for searching, processing, and downloading media from YouTube and TikTok.

## ✨ Features

*   🔍 *Smart Search:* Find songs on YouTube directly via chat.
*   🎤 *Voice Recognition:* Search for music using voice messages (Google STT).
*   📥 *Link Downloader:* Support for *TikTok*, *YouTube*, and *Shorts*.
*   🌀 *Audio Effects:* Integrated FFmpeg filters:
    *   *Slow + Reverb*
    *   *Nightcore* (Speed up)
    *   *Bass Boost*
    *   *8D Audio*
*   🛡️ *Security:* Auto-ban system for spammers (>5 req/min) and admin protection.
*   💾 *Performance:* LRU Caching for search results and media links.

## 🛠 Tech Stack

*   *Framework:* Aiogram 3.x
*   *Engine:* yt-dlp, FFmpeg
*   *Speech-to-Text:* SpeechRecognition
*   *Database:* Local file-based (txt) storage

## 🚀 Quick Start

1. *Install Dependencies:*
bash
pip install aiogram yt-dlp SpeechRecognition python-dotenv

2. *System Requirements:*
Install [FFmpeg](https://ffmpeg.org/) and ensure it's in your PATH or project folder.

3. *Configuration:*
Create a `.env` file in the root directory:
env
BOTTOKEN=YOURTELEGRAMBOTTOKEN

4. *Run:*
bash
python bot.py

## 📂 Structure
* `bot.py` — Core logic
* `temp_music/` — Temporary processing folder
* `banned.txt` / `users.txt` — Simple DB files
* `log.txt` — System logs

## 📜 License
Educational purposes only. All rights belong to respective content owners.              

