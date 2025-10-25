# Telegram подписки: GetCourse → Webhook → Telegram-отчёт

## Что делает
- Принимает события из GetCourse (подписка/отписка) по URL **/gc/webhook**
- Складывает события в `subs.db` (SQLite)
- Каждый день присылает отчёт в Telegram-бот @tg_subscribe_LP_bot

## Файлы
- `main.py` — FastAPI + Telegram-бот
- `requirements.txt` — зависимости
- `.env.example` — пример переменных окружения (в Render → Environment)

## Render.com (Web Service)
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`

## Настройка GetCourse → Callback (вебхук)
В GetCourse создайте Callback (POST) на URL:
```
https://<ИМЯ-СЕРВИСА>.onrender.com/gc/webhook
```
И передавайте поля (form-data или JSON):
```
event=subscribe          # или unsubscribe
user_email={email}       # или {user.email}
telegram_id={telegram_id}# если храните доп.поле с tg id
```

## Проверка
- Откройте логи Render: увидите "Telegram bot started" и "Uvicorn running".
- Отправьте тестовый POST на /gc/webhook и дождитесь кода 200.
- В Telegram боте /stats показывает суммарные значения.
