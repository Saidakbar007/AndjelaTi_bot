# Barber Bot — Telegram-бот для записи к мастеру

Асинхронный Telegram-бот на aiogram 3.x для онлайн-записи клиентов к барберу/парикмахеру.

## Возможности

**Клиент:** запись в 2-3 клика (дата → время → подтверждение телефона), просмотр и отмена своих
записей, авто-напоминание за N часов до визита.

**Мастер (админ-панель, доступна только ADMIN_IDS):** настройка графика работы по дням недели,
объявление выходных (с авто-отменой и уведомлением затронутых клиентов), настройка длительности
услуги, просмотр записей по дате, отмена записи с уведомлением клиента, мгновенное уведомление о
новой записи.

Защита от двойной записи реализована на уровне БД (частичный уникальный индекс на активные записи)
+ обработка `IntegrityError` в транзакции — исключает race condition при одновременном клике двух
клиентов на один слот.

## Структура проекта

```
bot/
  config.py                   # pydantic-settings, .env
  database/
    models.py                 # Master, Client, WorkingHours, DayOff, Booking
    engine.py                 # async engine/session, init_db()
  services/
    schedule_service.py       # график, выходные, свободные слоты
    booking_service.py        # создание/отмена записей, защита от гонки
    reminder_service.py       # фоновая проверка и отправка напоминаний
  middlewares/
    throttling.py             # защита от флуда
    db_session.py             # одна AsyncSession на апдейт
  keyboards/
    client_kb.py / admin_kb.py
  handlers/
    client/                   # меню, запись, "мои записи"
    admin/                    # панель, график, записи
  utils/
    callbacks.py              # CallbackData-схемы
    filters.py                # IsAdmin
    time_helpers.py           # работа с TIMEZONE
main.py                       # точка входа, APScheduler, polling
requirements.txt
.env.example
```

## Установка и запуск (локально / Windows, Python 3.11+)

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt

copy .env.example .env          # заполните BOT_TOKEN и ADMIN_IDS
python main.py
```

По умолчанию используется SQLite (`bot.db` создастся автоматически при первом запуске). Таблицы
создаются сами, мастера синхронизируются из `ADMIN_IDS` — отдельная настройка не требуется.

### Переменные окружения (`.env`)

| Переменная              | Описание                                                        |
|-------------------------|-------------------------------------------------------------------|
| `BOT_TOKEN`             | Токен бота от @BotFather                                         |
| `ADMIN_IDS`             | Telegram ID мастеров через запятую, напр. `111111111,222222222` |
| `DATABASE_URL`          | SQLAlchemy async URL (sqlite+aiosqlite по умолчанию)             |
| `TIMEZONE`              | IANA-таймзона, напр. `Asia/Tashkent`                              |
| `REMINDER_HOURS_BEFORE` | За сколько часов до визита слать напоминание                     |

### Первый запуск мастера

1. Запустите бота, напишите ему `/admin` с Telegram-аккаунта из `ADMIN_IDS`.
2. В разделе «🗓 График работы» задайте часы работы по каждому дню недели (формат `10:00-20:00`,
   либо слово `выходной` для нерабочего дня недели).
3. При необходимости настройте длительность услуги и объявите конкретные выходные дни.

Клиенты сразу видят только те даты/часы, где есть реально свободные слоты.

## Перенос на VPS с PostgreSQL + systemd

1. На сервере установите Python 3.11+, PostgreSQL, создайте БД и пользователя:
   ```bash
   sudo -u postgres psql -c "CREATE USER bot_user WITH PASSWORD 'strong_password';"
   sudo -u postgres psql -c "CREATE DATABASE barber_bot OWNER bot_user;"
   ```
2. Создайте отдельного непривилегированного системного пользователя (бот никогда не должен
   работать от root) и клонируйте проект в его домашний каталог:
   ```bash
   sudo useradd --system --home /opt/barber-bot --shell /usr/sbin/nologin barberbot
   sudo git clone <URL вашего репозитория> /opt/barber-bot
   sudo chown -R barberbot:barberbot /opt/barber-bot
   ```
3. Создайте venv и установите зависимости (`asyncpg` уже в requirements.txt):
   ```bash
   cd /opt/barber-bot
   sudo -u barberbot python3.11 -m venv .venv
   sudo -u barberbot .venv/bin/pip install -r requirements.txt
   ```
4. Создайте `.env` из `.env.example` и заполните реальными значениями (включая `BOT_TOKEN` и
   `ADMIN_IDS` — ID мастера добавляется последним шагом). Для PostgreSQL укажите:
   ```
   DATABASE_URL=postgresql+asyncpg://bot_user:strong_password@localhost:5432/barber_bot
   ```
   Ограничьте права на файл с секретами: `chmod 600 /opt/barber-bot/.env`.
   Таблицы создадутся автоматически при старте (`init_db()`), миграции не требуются для старта
   с нуля. Если же вы остаётесь на SQLite — путь к файлу БД (`DATABASE_URL=sqlite+aiosqlite:///bot.db`)
   теперь всегда resolve-ится относительно каталога проекта (`bot/config.py`), а не текущей
   рабочей директории процесса — бот корректно находит/создаёт свою базу независимо от того,
   из какой директории его запустили (важно именно для systemd).
5. Готовый unit-файл уже лежит в репозитории — [`deploy/barber-bot.service`](deploy/barber-bot.service).
   Скопируйте его, при необходимости поправьте пути/имя пользователя и включите:
   ```bash
   sudo cp deploy/barber-bot.service /etc/systemd/system/barber-bot.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now barber-bot
   sudo systemctl status barber-bot
   journalctl -u barber-bot -f
   ```
   `Restart=always` + `RestartSec=5` возвращают бота в строй после любого сбоя/перезагрузки VPS;
   `aiogram` сам корректно обрабатывает `SIGTERM`/`SIGINT` от `systemctl stop`/`restart`
   (останавливает polling и закрывает HTTP-сессию), так что отдельный код для graceful
   shutdown не нужен. Логи идут в journald (`journalctl -u barber-bot`) и переживают перезапуск
   службы — отдельный файл логов не требуется.

## Масштабирование на несколько мастеров

Все сущности графика и записей привязаны к `master_id`. Чтобы добавить второго мастера, просто
добавьте его Telegram ID в `ADMIN_IDS` и перезапустите бота — профиль мастера создастся
автоматически. Если у бота больше одного активного мастера, клиент при записи сначала выбирает
мастера, затем дату и время.

## Безопасность

- Секреты не хранятся в коде — только в `.env` (исключён из git через `.gitignore`, как и `*.db`,
  `.venv/`, логи).
- Админ-панель и все `adm_*`-колбэки доступны только пользователям из `ADMIN_IDS` (фильтр `IsAdmin`,
  применяется централизованно на уровне роутера).
- Защита от флуда — единый `ThrottlingMiddleware` на сообщения и callback-клики (общий счётчик на
  пользователя, чтобы его нельзя было обойти чередованием типов событий).
- Защита от двойной записи — частичный уникальный индекс в БД + обработка `IntegrityError` внутри
  транзакции (см. `bot/database/models.py`).
- Межмастерская изоляция — каждое админ-действие над записью/графиком проверяет, что ресурс
  (booking, день, переопределение) принадлежит именно тому мастеру, который нажал кнопку, а не
  предполагается из того, что «кнопку мог сформировать только наш бот» (Telegram-клиент технически
  может отправить произвольный `callback_data` для любого сообщения бота).
- Все данные, под контролем пользователя (имя клиента/мастера из профиля Telegram), экранируются
  (`html.escape`) перед вставкой в сообщения с `parse_mode="HTML"` — иначе «битый» HTML в имени
  профиля мог сломать рендер карточки дня у админа.
- В логи не пишутся телефоны, имена и текст сообщений — только технические события и ID.
- `requirements.txt` фиксирует точные версии всех зависимостей, включая транзитивный `aiohttp`
  (закрывает известные CVE в HTTP-парсере; в любом случае неприменимо напрямую — бот никогда не
  поднимает aiohttp как сервер, только как клиент к `api.telegram.org`).
- `.env` на проде должен иметь права `600` (`chmod 600 .env`), сервис — работать от отдельного
  непривилегированного системного пользователя (см. `deploy/barber-bot.service`).
