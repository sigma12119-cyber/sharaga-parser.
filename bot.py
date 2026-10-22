import os
import telebot
from telebot import types
from supabase import create_client, Client

# Твой токен
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8999171482:AAFeju8f-jz3H6G9mrlGOWTd1V_DO52UcfI")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def get_schedule():
    res = supabase.table("schedule") \
        .select("*") \
        .eq("group_name", "ДА-61") \
        .order("lesson_num") \
        .execute()
    
    rows = res.data
    if not rows:
        return "❌ Расписание для ДА-61 пока не найдено в базе.\nВозможно, парсер ещё не обновил данные."

    date = rows[0].get("date", "Сегодня")
    building = rows[0].get("building", 1)
    b_name = "Салова (1-2 корп.)" if building == 1 else "Энергетиков (3 корп.)"

    msg = f"📅 *Расписание на:* {date}\n"
    msg += f"🏢 *Корпус:* {b_name}\n"
    msg += f"👥 *Группа:* ДА-61\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    for r in rows:
        num = r.get("lesson_num", "-")
        subj = r.get("subject", "Пара")
        room = r.get("room", "-")
        msg += f"🔹 *{num} пара:* {subj}\n"
        msg += f"   📍 Кабинет: `{room}`\n\n"

    return msg

@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📖 Пары ДА-61"))
    bot.send_message(
        message.chat.id, 
        f"Салют, {message.from_user.first_name}! 🫡\nЖми кнопку ниже, чтобы получить расписание:", 
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == "📖 Пары ДА-61")
def send_schedule(message):
    text = get_schedule()
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

if __name__ == "__main__":
    print("Бот успешно запущен!")
    bot.infinity_polling()
