# main.py
# -*- coding: utf-8 -*-
# Единственный сервис для Render:
# - FastAPI endpoint /gc/webhook принимает колбэки из GetCourse (подписка/отписка)
# - Telegram-бот шлёт ежедневный отчёт о подписках/отписках
#
# Развёртывание: Render.com (Web Service)
# Переменные окружения: см. .env.example

import os
import sqlite3
from datetime import datetime, timedelta, time
from typing import Optional

import pytz
from dotenv import load_dotenv
from fastapi import FastAPI, Request
import uvicorn

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    Application,
)

# ========= База данных =========
DB_PATH = "subs.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Лог событий подписки/отписки
    cur.execute('''
        CREATE TABLE IF NOT EXISTS subs_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            user_id TEXT,
            event TEXT,       -- 'subscribe' | 'unsubscribe'
            source TEXT,      -- 'getcourse'
            ts TEXT           -- ISO с таймзоной
        )
    ''')
    conn.commit()
    conn.close()

def now_iso(tz_str: str) -> str:
    tz = pytz.timezone(tz_str)
    return datetime.now(tz).isoformat()

def add_event(email: Optional[str], user_id: Optional[str], event: str, source: str, tz_str: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO subs_audit (email, user_id, event, source, ts) VALUES (?, ?, ?, ?, ?)",
        (email, user_id, event, source, now_iso(tz_str))
    )
    conn.commit()
    conn.close()

def get_yesterday_counts(tz_str: str):
    tz = pytz.timezone(tz_str)
    now = datetime.now(tz)
    start = tz.localize(datetime.combine((now - timedelta(days=1)).date(), time(0,0)))
    end = tz.localize(datetime.combine(now.date(), time(0,0)))

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subs_audit WHERE event='subscribe' AND ts >= ? AND ts < ?", (start.isoformat(), end.isoformat()))
    subs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM subs_audit WHERE event='unsubscribe' AND ts >= ? AND ts < ?", (start.isoformat(), end.isoformat()))
    unsubs = cur.fetchone()[0]
    conn.close()
    return subs, unsubs, start.date()

def get_totals():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subs_audit WHERE event='subscribe'")
    total_subs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM subs_audit WHERE event='unsubscribe'")
    total_unsubs = cur.fetchone()[0]
    conn.close()
    return total_subs, total_unsubs

# ========= FastAPI (вебхук от GetCourse) =========
app = FastAPI()

@app.post("/gc/webhook")
async def gc_webhook(request: Request):
    """
    Универсальный входящий вебхук от GetCourse.
    В GetCourse можно настроить callback POST с полями формы (или JSON).
    Передавайте:
      - event: subscribe / unsubscribe
      - user_email: {email} или {user.email}
      - telegram_id: {telegram_id} (если храните как доп.поле)
    """
    load_dotenv()  # на всякий
    tz_str = os.getenv("REPORT_TZ", "Europe/Moscow")
    ctype = request.headers.get("content-type","")
    if ctype.startswith("application/x-www-form-urlencoded") or ctype.startswith("multipart/form-data"):
        data = await request.form()
    else:
        try:
            data = await request.json()
        except Exception:
            data = {}

    # Приводим к словарю обычному (на случай FormData)
    data = dict(data)

    event = (str(data.get("event","")).strip().lower())
    email = (str(data.get("user_email","") or data.get("email","")).strip() or None)
    tg_id = (str(data.get("telegram_id","")).strip() or None)

    if event not in ("subscribe", "unsubscribe"):
        return {"status": "ignored", "reason": "unknown event", "received_event": event, "data": data}

    add_event(email=email, user_id=tg_id, event=event, source="getcourse", tz_str=tz_str)
    return {"status": "ok"}

# ========= Telegram-бот для ежедневного отчёта =========
bot_app: Optional[Application] = None

async def stats_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    total_subs, total_unsubs = get_totals()
    label = os.getenv("REPORT_LABEL", "Подписки")
    await update.message.reply_text(
        f"🧾 Отчёт: {label}\n"
        f"✅ Всего подписок: {total_subs}\n"
        f"🚪 Всего отписок: {total_unsubs}"
    )


async def today_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    tz_str = os.getenv("REPORT_TZ", "Europe/Moscow")
    tz = pytz.timezone(tz_str)
    now = datetime.now(tz)
    start = tz.localize(datetime.combine(now.date(), dtime(0,0)))
    end = tz.localize(datetime.combine(now.date(), dtime(23,59,59)))
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subs_audit WHERE event='subscribe' AND ts >= ? AND ts <= ?", (start.isoformat(), end.isoformat()))
    subs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM subs_audit WHERE event='unsubscribe' AND ts >= ? AND ts <= ?", (start.isoformat(), end.isoformat()))
    unsubs = cur.fetchone()[0]
    conn.close()
    label = os.getenv("REPORT_LABEL", "Подписки")
    await update.message.reply_text(
        f"🧾 Отчёт: {label}\n"
        f"📅 Сегодня: {now.strftime('%d.%m.%Y')}\n"
        f"✅ Подписки: {subs}\n"
        f"🚪 Отписки: {unsubs}"
    )
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    tz_str = os.getenv("REPORT_TZ", "Europe/Moscow")
    label = os.getenv("REPORT_LABEL", "Подписки")
    admin_raw = os.getenv("ADMIN_ID", "")
    admin_ids = [int(x.strip()) for x in admin_raw.split(",") if x.strip().isdigit()]
    subs, unsubs, y_date = get_yesterday_counts(tz_str)
    msg = (
        f"🧾 Отчёт: {label}\n"
        f"📅 Дата: {y_date.strftime('%d.%m.%Y')}\n"
        f"✅ Новые подписки: {subs}\n"
        f"🚪 Отписки: {unsubs}"
    )
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=msg)
        except Exception as e:
            print(f"Ошибка отправки админу {admin_id}: {e}")

def schedule_bot_jobs(app: Application):
    import pytz as _pytz
    tz_str = os.getenv("REPORT_TZ", "Europe/Moscow")
    hour = int(os.getenv("REPORT_HOUR", "9"))
    minute = int(os.getenv("REPORT_MINUTE", "0"))
    tz = _pytz.timezone(tz_str)
    app.job_queue.run_daily(send_daily_report, time=time(hour=hour, minute=minute, tzinfo=tz))

async def start_bot():
    global bot_app
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Переменная окружения BOT_TOKEN не задана")
    application = (
        ApplicationBuilder()
        .token(token)
        .build()
    )
    application.add_handler(CommandHandler("stats", stats_cmd))
    application.add_handler(CommandHandler("today", today_cmd))
    schedule_bot_jobs(application)
    bot_app = application
    await application.initialize()
    await application.start()
    print("Telegram bot started")

# ========= Локальный/Render запуск =========
def main():
    load_dotenv()
    init_db()

    # Запускаем Telegram-бот и HTTP-сервер вместе
    import asyncio
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())

    host = "0.0.0.0"
    port = int(os.getenv("PORT", "10000"))  # Render предоставляет PORT
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
