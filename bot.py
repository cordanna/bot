import asyncio
import re
import sqlite3
from datetime import date, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ChatType

# ================== НАСТРОЙКИ ==================

TOKEN = "8585669142:AAEgCDQi2a52Ksy2HXl27NXhAcuDuiGNaZk"

# ================== БАЗА ДАННЫХ ==================

conn = sqlite3.connect("habits.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS logs (
    user_id INTEGER,
    username TEXT,
    habit TEXT,
    value INTEGER,
    log_date TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS norms (
    user_id INTEGER,
    habit TEXT,
    target INTEGER,
    UNIQUE(user_id, habit)
)
""")

conn.commit()

# ================== BOT ==================

bot = Bot(token=TOKEN)
dp = Dispatcher()

LOG_PATTERN = re.compile(r"^([а-яА-Яa-zA-Z]+)\s*([+-]?\d+)$")
NORM_PATTERN = re.compile(r"^норма\s+([а-яА-Яa-zA-Z]+)\s+(\d+)$", re.IGNORECASE)

# ================== ВСПОМОГАТЕЛЬНЫЕ ==================

def period_start(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()

# ================== ОБРАБОТКА СООБЩЕНИЙ ==================

@dp.message()
async def handle_message(message: types.Message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    if not message.text:
        return

    text = message.text.strip()
    text_l = text.lower()

    user = message.from_user
    user_id = user.id
    username = user.first_name
    today = date.today().isoformat()

    # ---------- АЛЕРТ ----------
    if text_l == "алерт":
        await send_alert(message)
        return

    # ---------- ИТОГИ ----------
    if text_l == "итоги":
        await send_personal_totals(message, user_id, username, today)
        return

    if text_l == "итоги неделя":
        await send_personal_period_totals(
            message, user_id, username,
            period_start(6), today, "Неделя"
        )
        return

    if text_l == "итоги месяц":
        await send_personal_period_totals(
            message, user_id, username,
            period_start(29), today, "Месяц"
        )
        return

    if text_l == "итоги все":
        await send_group_totals(message, today)
        return

    if text_l == "итоги все неделя":
        await send_group_period_totals(
            message, period_start(6), today, "Неделя"
        )
        return

    if text_l == "итоги все месяц":
        await send_group_period_totals(
            message, period_start(29), today, "Месяц"
        )
        return

    # ---------- НОРМА ----------
    norm_match = NORM_PATTERN.match(text)
    if norm_match:
        habit, target = norm_match.groups()
        target = int(target)
        habit = habit.lower()

        cursor.execute("""
            INSERT INTO norms (user_id, habit, target)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, habit)
            DO UPDATE SET target = excluded.target
        """, (user_id, habit, target))
        conn.commit()

        await message.reply(f"{username} — норма для «{habit}»: {target}")
        return

    # ---------- ЛОГ ----------
    log_match = LOG_PATTERN.match(text)
    if not log_match:
        return

    habit, value = log_match.groups()
    habit = habit.lower()
    value = int(value)

    cursor.execute(
        "INSERT INTO logs VALUES (?, ?, ?, ?, ?)",
        (user_id, username, habit, value, today)
    )
    conn.commit()

    cursor.execute("""
        SELECT SUM(value)
        FROM logs
        WHERE user_id = ? AND habit = ? AND log_date = ?
    """, (user_id, habit, today))

    total = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT target FROM norms
        WHERE user_id = ? AND habit = ?
    """, (user_id, habit))
    row = cursor.fetchone()

    if row:
        target = row[0]
        percent = min(100, int(total / target * 100))
        suffix = f" — {percent}% от нормы"
    else:
        suffix = ""

    await message.reply(
        f"{username} — {habit} {value:+d} (итого {total} сегодня){suffix}"
    )

# ================== ИТОГИ ==================
async def send_personal_totals(message, user_id, username, today):
    cursor.execute("""
        SELECT habit, SUM(value)
        FROM logs
        WHERE user_id = ? AND log_date = ?
        GROUP BY habit
    """, (user_id, today))

    rows = cursor.fetchall()
    if not rows:
        await message.reply("Сегодня пока нет записей")
        return

    lines = [f"Итоги за сегодня — {username}:"]
    for habit, total in rows:
        cursor.execute("""
            SELECT target FROM norms
            WHERE user_id = ? AND habit = ?
        """, (user_id, habit))
        row = cursor.fetchone()
        if row:
            target = row[0]
            percent = min(100, int(total / target * 100))
            lines.append(f"• {habit}: {total}/{target} ({percent}%)")
        else:
            lines.append(f"• {habit}: {total}")

    await message.reply("\n".join(lines))


async def send_personal_period_totals(message, user_id, username, start, end, title):
    cursor.execute("""
        SELECT habit, SUM(value)
        FROM logs
        WHERE user_id = ?
          AND log_date BETWEEN ? AND ?
        GROUP BY habit
    """, (user_id, start, end))

    rows = cursor.fetchall()
    if not rows:
        await message.reply(f"{title}: данных нет")
        return

    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    lines = [f"{title} — {username}:"]

    for habit, total in rows:
        cursor.execute("""
            SELECT target FROM norms
            WHERE user_id = ? AND habit = ?
        """, (user_id, habit))
        row = cursor.fetchone()
        if row:
            target = row[0] * days
            percent = min(100, int(total / target * 100))
            lines.append(f"• {habit}: {total}/{target} ({percent}%)")
        else:
            lines.append(f"• {habit}: {total}")

    await message.reply("\n".join(lines))


async def send_group_totals(message, today):
    cursor.execute("""
        SELECT username, habit, SUM(value)
        FROM logs
        WHERE log_date = ?
        GROUP BY user_id, habit
        ORDER BY username
    """, (today,))

    rows = cursor.fetchall()
    if not rows:
        await message.reply("Сегодня пока нет записей")
        return

    data = {}
    for username, habit, total in rows:
        data.setdefault(username, []).append((habit, total))

    lines = ["Итоги за сегодня — все:"]
    for username, habits in data.items():
        lines.append(f"\n{username}:")
        for habit, total in habits:
            lines.append(f"  • {habit}: {total}")

    await message.reply("\n".join(lines))


async def send_group_period_totals(message, start, end, title):
    cursor.execute("""
        SELECT username, habit, SUM(value)
        FROM logs
        WHERE log_date BETWEEN ? AND ?
        GROUP BY user_id, habit
        ORDER BY username
    """, (start, end))

    rows = cursor.fetchall()
    if not rows:
        await message.reply(f"{title}: данных нет")
        return

    data = {}
    for username, habit, total in rows:
        data.setdefault(username, []).append((habit, total))

    lines = [f"{title} — все:"]
    for username, habits in data.items():
        lines.append(f"\n{username}:")
        for habit, total in habits:
            lines.append(f"  • {habit}: {total}")

    await message.reply("\n".join(lines))

# ================== АЛЕРТ ==================

async def send_alert(message):
    today = date.today().isoformat()

    cursor.execute("""
        SELECT DISTINCT user_id, username
        FROM logs
    """)
    users = cursor.fetchall()

    lines = ["Алерт за сегодня:"]
    has_alerts = False

    for user_id, username in users:
        cursor.execute("""
            SELECT habit, target
            FROM norms
            WHERE user_id = ?
        """, (user_id,))
        norms_rows = cursor.fetchall()

        if not norms_rows:
            continue

        user_lines = []
        for habit, target in norms_rows:
            cursor.execute("""
                SELECT SUM(value)
                FROM logs
                WHERE user_id = ?
                AND habit = ?
                  AND log_date = ?
            """, (user_id, habit, today))

            total = cursor.fetchone()[0] or 0

            if total < target:
                user_lines.append(f"• {habit}: {total}/{target} ❌")
                has_alerts = True
            else:
                user_lines.append(f"• {habit}: {total}/{target} ✅")

        if user_lines:
            lines.append(f"\n{username}:")
            lines.extend(user_lines)

    if not has_alerts:
        await message.reply("Алерт: все уложились в нормы ✅")
        return

    await message.reply("\n".join(lines))

# ================== ЗАПУСК ==================

async def main():
    await dp.start_polling(bot)

if name == "__main__":
    asyncio.run(main())
