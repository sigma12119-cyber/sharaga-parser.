import os
from supabase import create_client, Client
import telebot
from telebot import types

# Читаем ключи из переменных окружения
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not TELEGRAM_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
    print("Ошибка: Не заданы переменные окружения!")
    exit(1)

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_schedule_text():
    # Забираем пары группы ДА-61, сортируем по номеру урока
    res = supabase.table("schedule") \
        .select("*") \
        .eq("group_name", "ДА-61") \
        .order("lesson_num") \
        .execute()
    
    rows = res.data
    if not rows:
        return "❌ Расписание для группы ДА-61 пока не найдено в базе.\nВозможно, парсер ещё не обновил данные или сегодня выходной!"

    date = rows[0].get("date", "Сегодня")
    building = rows[0].get("building", 1)
    b_name = "Салова (1-2 корп.)" if building == 1 else "Энергетиков (3 корп.)"

    text = f"📅 *Расписание на:* {date}\n"
    text += f"🏢 *Корпус:* {b_name}\n"
    text += f"👥 *Группа:* ДА-61\n"
    text += "━" * 20 + "\n\n"

    for r in rows:
        num = r.get("lesson_num", "-")
        subj = r.get("subject", "Пара")
        room = r.get("room", "Ауд.")
        text += f"🔹 *{num} пара:* {subj}\n"
        text += f"   📍 Кабинет: `{room}`\n\n"

    return text

@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("📖 Пары ДА-61")
    markup.add(btn1)
    bot.send_message(
        message.chat.id, 
        f"Здорово, {message.from_user.first_name}! 🫡\nНажимай кнопку внизу, чтобы узнать актуальные пары:", 
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "📖 Пары ДА-61")
def send_schedule(message):
    text = get_schedule_text()
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

if __name__ == "__main__":
    print("Бот запущен и готов к работе...")
    bot.infinity_polling()
