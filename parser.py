import io
import os
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader
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
TARGET_GROUP = "ДА-61"


def get_schedule():
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/120.0.0.0 Safari/537.36"
      )
  }

  print("1. Заходим на сайт АТТ...")
  response = requests.get(SCHEDULE_PAGE, headers=headers)
  response.encoding = "utf-8"

  if response.status_code != 200:
    print(f"Ошибка загрузки страницы: {response.status_code}")
    return

  soup = BeautifulSoup(response.text, "html.parser")

  # Ищем дату
  date_match = re.search(r"на\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4})", response.text)
  schedule_date = date_match.group(1) if date_match else "Сегодня"
  print(f"Дата расписания: {schedule_date}")

  # Ищем ссылку на PDF 1-2 корпуса
  target_link = None
  for a_tag in soup.find_all("a", href=True):
    text = a_tag.get_text(strip=True).lower()
    if "расписание" in text and "групп" in text:
      target_link = urljoin(BASE_URL, a_tag["href"])
      break

  if not target_link:
    print("Не найдена ссылка на PDF!")
    return

  print(f"2. Качаем PDF расписания: {target_link}")
  pdf_res = requests.get(target_link, headers=headers)
  if pdf_res.status_code != 200:
    print("Не удалось скачать PDF!")
    return

  # Читаем текст из PDF файла
  pdf_file = io.BytesIO(pdf_res.content)
  reader = PdfReader(pdf_file)

  full_text = ""
  for page in reader.pages:
    full_text += page.extract_text() + "\n"

  print("3. Ищем расписание для группы:", TARGET_GROUP)

  # Ищем блок текста группы ДА-61
  parsed_records = []

  # Регулярка ищет упоминание группы и захватывает последующие строки до следующей группы
  pattern = rf"{TARGET_GROUP}(.*?)(?=[А-Я]{{1,3}}-\d{{1,2}}|\Z)"
  match = re.search(pattern, full_text, re.DOTALL | re.IGNORECASE)

  if match:
    group_content = match.group(1)
    lines = [
        line.strip() for line in group_content.split("\n") if line.strip()
    ]

    lesson_counter = 1
    for line in lines:
      # Пропускаем мусорные короткие строки
      if len(line) < 3 or "корпус" in line.lower():
        continue

      # Пробуем выделить кабинет (обычно цифры в конце строки, например 204 или Сал.63)
      room_match = re.search(r"\b(\d{2,3}[а-яА-Я]?|ауд\.?\s*\d+)\b", line)
      room = room_match.group(0) if room_match else "Салова"

      parsed_records.append({
          "date": schedule_date,
          "building": 1,  # Салова 1-2 корпус
          "group_name": TARGET_GROUP,
          "lesson_num": lesson_counter,
          "subject": line[:80],  # Текст строки с предметом
          "room": room,
          "teacher": "По расписанию",
      })
      lesson_counter += 1
  else:
    print(
        f"Группа {TARGET_GROUP} в текущем PDF не найдена (возможно, выходной или практика)"
    )

  if not parsed_records:
    # Запасная запись, чтобы база не пустовала
    parsed_records.append({
        "date": schedule_date,
        "building": 1,
        "group_name": TARGET_GROUP,
        "lesson_num": 1,
        "subject": "Нет пар или практика (чекни PDF)",
        "room": "—",
        "teacher": "—",
    })

  # Чистим старые записи на эту дату для этой группы перед добавлением свежих
  try:
    supabase.table("schedule").delete().match({
        "date": schedule_date,
        "group_name": TARGET_GROUP,
    }).execute()
  except Exception as e:
    print(f"Заметка по очистке: {e}")

  # Заливаем свежие спарсенные пары в Supabase
  try:
    supabase.table("schedule").upsert(parsed_records).execute()
    print(
  
