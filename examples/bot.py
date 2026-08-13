#!/usr/bin/env python3
"""Telegram bot example that uses the Bypass API (with job polling).

pip install python-telegram-bot==21.9 requests
BOT_TOKEN=xxx API_BASE=https://your-app.onrender.com python bot.py
"""
import os
import time

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

API_BASE = os.getenv("API_BASE", "https://your-app.onrender.com").rstrip("/")
BOT_TOKEN = os.environ["BOT_TOKEN"]


def resolve(short_url: str, max_wait: int = 300) -> dict:
    """Call the API and poll the job until it finishes."""
    r = requests.get(f"{API_BASE}/api", params={"bypass": short_url}, timeout=120)
    data = r.json()
    if data.get("success") or not data.get("pending"):
        return data

    job_id = data["job_id"]
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(3)
        data = requests.get(f"{API_BASE}/job", params={"id": job_id}, timeout=30).json()
        if data.get("status") != "running":
            return data
    return {"success": False, "error": "timed out waiting for the job"}


async def handle(update: Update, _):
    text = (update.message.text or "").strip().split()[-1]
    if not text.startswith("http"):
        await update.message.reply_text("Send a supported shortlink.")
        return
    msg = await update.message.reply_text("Bypassing... (may take 1-3 min)")
    data = resolve(text)
    if data.get("success"):
        await msg.edit_text(f"✅ {data['bypassed']}\n⏱ {data.get('took')}s")
    else:
        await msg.edit_text(f"❌ {data.get('error', 'failed')}")


async def start(update: Update, _):
    sites = requests.get(f"{API_BASE}/", timeout=30).json().get("supported", [])
    await update.message.reply_text("Send me a shortlink.\nSupported: " + ", ".join(sites))


app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("bypass", handle))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
app.run_polling()
