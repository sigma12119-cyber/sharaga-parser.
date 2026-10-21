import io
import os
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader
import requests
from supabase import Client, create_client

# Укажи адрес своего проекта Supabase
URL = os.environ.get("SUPABASE_URL") or "https://ТВОЙ_ПРОЕКТ.supabase.co"
KEY = os.environ.get("SUPABASE_KEY")

if not URL or not KEY:
  print("Ошибка: Нет ключей Supabase!")
  exit(1)

supabase: Client = create_client(URL, KEY)

BASE_URL = "http://xn--80a0ba.xn--90a1af.xn--p1ai"
SCHEDULE_PAGE = f"{BASE_URL}/studentu/ochn"
TARGET_GROUP = "ДА-61"


def get_schedule():
  headers = {"User-Agent": "Mozilla/5.0"}
  print("1. Запрос к сайту...")
  res = requests.get(SCHEDULE_PAGE, headers=headers)
  res.encoding = "utf-8"

  if res.status_code != 200:
    print("Ошибка загрузки сайта")
    return

  soup = BeautifulSoup(res.text, "html.parser")

  date_match = re.search(r"на\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4})", res.text)
  schedule_date = date_match.group(1) if date_match else "Сегодня"
  print("Дата:", schedule_date)

  target_link = None
  for a in soup.find_all("a", href=True):
    txt = a.get_text(strip=True).lower()
    if "расписание" in txt and "групп" in txt:
      target_link = urljoin(BASE_URL, a["href"])
      break

  if not target_link:
    print("Ссылка на PDF не найдена")
    return

  print("2. Скачивание PDF:", target_link)
  pdf_res = requests.get(target_link, headers=headers)
  if pdf_res.status_code != 200:
    print("Ошибка скачивания файла")
    return

  reader = PdfReader(io.BytesIO(pdf_res.content))
  full_text = ""
  for page in reader.pages:
    txt = page.extract_text()
    if txt:
      full_text += txt + "\n"

  print("3. Поиск группы:", TARGET_GROUP)
  records = []
  pattern = rf"{TARGET_GROUP}(.*?)(?=[А-Я]{{1,3}}-\d{{1,2}}|\Z)"
  match = re.search(pattern, full_text, re.DOTALL | re.IGNORECASE)

  if match:
    lines = [
        ln.strip() for ln in match.group(1).split("\n") if len(ln.strip()) > 3
    ]
    idx = 1
    for ln in lines:
      if "корпус" in ln.lower():
        continue
      room_m = re.search(r"\b(\d{2,3}[а-яА-Я]?|ауд\.?\s*\d+)\b", ln)
      room = room_m.group(0) if room_m else "Салова"
      records.append({
          "date": schedule_date,
          "building": 1,
          "group_name": TARGET_GROUP,
          "lesson_num": idx,
          "subject": ln[:80],
          "room": room,
          "teacher": "По расписанию",
      })
      idx += 1

  if not records:
    records.append({
        "date": schedule_date,
        "building": 1,
        "group_name": TARGET_GROUP,
        "lesson_num": 1,
        "subject": "Расписание уточняется (чекни PDF)",
        "room": "—",
        "teacher": "—",
    })

  try:
    supabase.table("schedule").delete().match({
        "date": schedule_date,
        "group_name": TARGET_GROUP,
    }).execute()
  except Exception as e:
    print("Очистка старых строк:", e)

  try:
    supabase.table("schedule").upsert(records).execute()
    print("Успешно записано строк:", len(records))
  except Exception as e:
    print("Ошибка Supabase:", e)


if __name__ == "__main__":
  get_schedule()
  
