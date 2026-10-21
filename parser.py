import os
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from supabase import Client, create_client

# Подключение к твоей базе Supabase
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

if not URL or not KEY:
  print("Ошибка: Нет ключей подключения к Supabase!")
  exit(1)

supabase: Client = create_client(URL, KEY)

BASE_URL = "http://xn--80a0ba.xn--90a1af.xn--p1ai"
SCHEDULE_PAGE = f"{BASE_URL}/studentu/ochn"


def get_schedule():
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      )
  }

  print("Заходим на сайт АТТ...")
  response = requests.get(SCHEDULE_PAGE, headers=headers)
  response.encoding = "utf-8"

  if response.status_code != 200:
    print(f"Ошибка загрузки страницы: {response.status_code}")
    return

  soup = BeautifulSoup(response.text, "html.parser")

  # 1. Ищем дату расписания на странице
  date_match = re.search(r"на\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4})", response.text)
  schedule_date = date_match.group(1) if date_match else "Актуальное"
  print(f"Найдена дата: {schedule_date}")

  # 2. Ищем ссылку на расписание групп для 1 и 2 корпуса (Салова)
  target_link = None
  for a_tag in soup.find_all("a", href=True):
    text = a_tag.get_text(strip=True).lower()
    # Ищем ссылку "Расписание групп"
    if "расписание" in text and "групп" in text:
      target_link = urljoin(BASE_URL, a_tag["href"])
      # Берем первую ссылку, так как 1-2 корпус идет первым блоком
      break

  if not target_link:
    print("Не удалось найти прямую ссылку на расписание 1-2 корпуса :(")
    return

  print(f"Ссылка на расписание групп 1-2 корпуса: {target_link}")

  # 3. Базовый шаблон сохранения в Supabase
  # Если ссылка ведет на страницу или документ, логика забирает данные:
  # Пример структуры для отправки:
  sample_data = [{
      "date": schedule_date,
      "building": 1,  # 1 и 2 корпус на Салова
      "group_name": "Тестовая группа",
      "lesson_num": 1,
      "subject": "Проверка связи",
      "room": "Салова, 63",
      "teacher": "Преподаватель",
  }]

  # Отправляем в Supabase
  try:
    supabase.table("schedule").upsert(sample_data).execute()
    print("Успешно приписюнили тестовые данные в Supabase! ГОЛДААА!")
  except Exception as e:
    print(f"Ошибка при записи в Supabase: {e}")


if __name__ == "__main__":
  get_schedule()
  
