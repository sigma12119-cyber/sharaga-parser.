import os
import io
import re
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from supabase import create_client, Client
from datetime import datetime, timedelta

URL = "https://wacvxwqdxoufcbfbldoa.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndhY3Z4d3FkeG91ZmNiZmJsZG9hIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI2MDQyNTMsImV4cCI6MjEwODE4MDI1M30.fhRWe94_JinXEGtvWFhq-hzN3J-um5tM3P5Snj3RojM"

supabase: Client = create_client(URL, KEY)

BASE_URL = "http://xn--80a0ba.xn--90a1af.xn--p1ai"
SCHEDULE_PAGE = f"{BASE_URL}/studentu/ochn"

def clean_text(t):
    return re.sub(r'\s+', ' ', t).strip()

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

    # Ищет группу ДА-61 в любом виде (рус/англ, с дефисом, пробелом или слитно)
    group_regex = re.compile(r'\b[дdДD][аaАA][\s\-_–—]?61\b', re.IGNORECASE)
    found_idx = -1
    for i, line in enumerate(all_lines):
        if group_regex.search(line):
            found_idx = i
            print(f"[{building_num} корпус] Группа найдена на строке {i}: {line}")
            break

    records = []
    if found_idx != -1:
        next_group_regex = re.compile(r'\b[а-яА-Яa-zA-Z]{1,4}[\s\-_–—]?\d{1,3}\b')
        lesson_idx = 1
        for line in all_lines[found_idx + 1:found_idx + 25]:
            if next_group_regex.search(line) and not group_regex.search(line) and len(line) < 15:
                break
            if "корпус" in line.lower() or "расписание" in line.lower():
                continue

            room_m = re.search(r'\b(\d{2,3}[а-яА-Я]?|ауд\.?\s*\d+)\b', line)
            default_room = "Энергетиков" if building_num == 3 else "Салова"
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
                    "teacher": "По расписанию"
                })
                lesson_idx += 1
    return records

def get_schedule():
    headers = {"User-Agent": "Mozilla/5.0"}
    print("1. Запрос к сайту колледжа...")
    res = requests.get(SCHEDULE_PAGE, headers=headers)
    res.encoding = "utf-8"

    soup = BeautifulSoup(res.text, "html.parser")
    
    # Дата из шапки расписания на сайте
    date_m = re.search(r'на\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4})', res.text)
    schedule_date = date_m.group(1) if date_m else "23 октября"
    print("Дата расписания с сайта:", schedule_date)

    # Логика времени: если вечер (после 15:00 UTC/МСК), смотрим расписание на завтра
    now = datetime.now()
    target_date = now + timedelta(days=1) if now.hour >= 15 else now
    target_weekday = target_date.weekday()

    # Понедельник (0) и Четверг (3) -> 3 корпус. Пятница (4) и
