import io
import os
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader
import requests
from supabase import Client, create_client

URL = "https://wacvxwqdxoufcbfbldoa.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndhY3Z4d3FkeG91ZmNiZmJsZG9hIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI2MDQyNTMsImV4cCI6MjEwODE4MDI1M30.fhRWe94_JinXEGtvWFhq-hzN3J-um5tM3P5Snj3RojM"

supabase: Client = create_client(URL, KEY)

BASE_URL = "http://xn--80a0ba.xn--90a1af.xn--p1ai"
SCHEDULE_PAGE = f"{BASE_URL}/studentu/ochn"


def clean_text(t):
  return re.sub(r"\s+", " ", t).strip()


def parse_pdf_for_group(pdf_bytes, building_num, schedule_date):
  reader = PdfReader(io.BytesIO(pdf_bytes))
  all_lines = []
  for page in reader.pages:
    text = page.extract_text()
    if text:
      for line in text.split("\n"):
        c = clean_text(line)
        if c:
          all_lines.append(c)

  # Ищет ДА-61, ДА 61, DA-61 в любом регистре
  group_regex = re.compile(r"\b[дdДD][аaАA][\s\-_–—]?61\b", re.IGNORECASE)
  found_idx = -1
  for i, line in enumerate(all_lines):
    if group_regex.search(line):
      found_idx = i
      print(f"[{building_num} корпус] Группа найдена на строке {i}: {line}")
      break

  records = []
  if found_idx != -1:
    next_group_regex = re.compile(
        r"\b[а-яА-Яa-zA-Z]{1,4}[\s\-_–—]?\d{1,3}\b"
    )
    lesson_idx = 1
    for line in all_lines[found_idx + 1 : found_idx + 25]:
      if (
          next_group_regex.search(line)
          and not group_regex.search(line)
          and len(line) < 15
      ):
        break
      if "корпус" in line.lower() or "расписание" in line.lower():
        continue

      room_m = re.search(r"\b(\d{2,3}[а-яА-Я]?|ауд\.?\s*\d+)\b", line)
      default_room = "Салова" if building_num == 1 else "Энергетиков"
      room = room_m.group(0) if room_m else default_room

      subj = line
      if room_m:
        subj = subj.replace(room_m.group(0), "").strip()

      if len(subj) > 2:
        records.append({
            "date": schedule_date,
            "building": building_num,
            "group_name": "ДА-61",
            "lesson_num": lesson_idx,
            "subject": subj[:100],
            "room": room,
            "teacher": "По расписанию",
        })
        lesson_idx += 1
  return records


def get_schedule():
  headers = {"User-Agent": "Mozilla/5.0"}
  print("1. Запрос к сайту...")
  res = requests.get(SCHEDULE_PAGE, headers=headers)
  res.encoding = "utf-8"

  soup = BeautifulSoup(res.text, "html.parser")

  date_m = re.search(r"на\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4})", res.text)
  schedule_date = date_m.group(1) if date_m else "Сегодня"

  pdf_targets = []
  for a in soup.find_all("a", href=True):
    txt = a.get_text(strip=True).lower()
    href = urljoin(BASE_URL, a["href"])
    if "расписание" in txt and "групп" in txt:
      if "3" in txt or "энергетиков" in txt:
        pdf_targets.append((href, 3))
      else:
        pdf_targets.append((href, 1))

  # Очищаем старые записи
  try:
    supabase.table("schedule").delete().eq("group_name", "ДА-61").execute()
  except Exception as e:
    print("Ошибка очистки:", e)

  all_records = []
  for link, b_num in pdf_targets:
    pdf_res = requests.get(link, headers=headers)
    if pdf_res.status_code == 200:
      recs = parse_pdf_for_group(pdf_res.content, b_num, schedule_date)
      all_records.extend(recs)

  if all_records:
    supabase.table("schedule").upsert(all_records).execute()
    print(f"Готово! Записано пар: {len(all_records)}")
  else:
    print("Пар для ДА-61 не найдено.")


if __name__ == "__main__":
  get_schedule()
