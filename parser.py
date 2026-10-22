import os
import io
import re
from urllib.parse import urljoin
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from supabase import create_client, Client

print("--- ЗАПУСК ПАРСЕРА ---", flush=True)

URL = os.environ.get("SUPABASE_URL") or "https://wacvxwqdxoufcbfbldoa.supabase.co"
KEY = os.environ.get("SUPABASE_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndhY3Z4d3FkeG91ZmNiZmJsZG9hIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI2MDQyNTMsImV4cCI6MjEwODE4MDI1M30.fhRWe94_JinXEGtvWFhq-hzN3J-um5tM3P5Snj3RojM"

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

    group_regex = re.compile(r'\b[дdДD][аaАA][\s\-_–—]?61\b', re.IGNORECASE)
    any_group_regex = re.compile(r'\b[а-яА-Яa-zA-Z]{1,4}[\s\-_–—]?\d{2}\b')

    found_idx = -1
    col_index = 0
    total_cols = 1

    for i, line in enumerate(all_lines):
        if group_regex.search(line):
            found_idx = i
            # Считаем все группы в этой строке (например: ДА-61 ДА-62 ДА-63)
            groups_in_row = any_group_regex.findall(line)
            if groups_in_row:
                total_cols = len(groups_in_row)
                for idx, g in enumerate(groups_in_row):
                    if group_regex.search(g):
                        col_index = idx
                        break
            print(f"[{building_num} корп.] Найдена ДА-61 на стр. {i}: '{line}' (Колонка {col_index+1} из {total_cols})", flush=True)
            break

    records = []
    if found_idx != -1:
        for line in all_lines[found_idx + 1:found_idx + 25]:
            # Если началась следующая строка групп (например ДР-41 ДР-42) — выходим
            if any_group_regex.search(line) and not re.search(r'каб|ауд', line.lower()):
                break
            if any(w in line.lower() for w in ["пятница", "понедельник", "вторник", "среда", "четверг", "суббота"]):
                continue

            # Ищем строку, которая начинается с номера пары (1, 2, 3, 4, 5, 6)
            m_num = re.match(r'^([1-6])\s+(.*)', line)
            if not m_num:
                continue

            lesson_num = int(m_num.group(1))
            # Если в строке только цифры типа "5 5 5" или "6 6 6" — значит пар нет, пропускаем
            if re.match(r'^[1-6](\s+[1-6])+$', line):
                continue

            # Разбиваем склеенную строку по номеру пары (например, по " 1 ", " 2 ", " 3 ")
            parts = re.split(rf'\b{lesson_num}\s+', line)
            parts = [p.strip() for p in parts if p.strip()]

            if not parts:
                continue

            # Берем именно нашу колонку
            my_part = parts[col_index] if col_index < len(parts) else parts[0]

            # Вытаскиваем кабинет
            room_m = re.search(r'(?:каб\.?|ауд\.?)\s*([0-9]{2,3}[а-яА-Я]?|[а-яА-Я0-9\-]+)', my_part, re.IGNORECASE)
            default_room = "Энергетиков" if building_num == 3 else "Салова"
            room = room_m.group(1) if room_m else default_room

            # Очищаем название предмета от слова "каб ..."
            subj = re.sub(r',?\s*(?:каб\.?|ауд\.?)\s*([0-9]{2,3}[а-яА-Я]?|[а-яА-Я0-9\-]+).*', '', my_part, flags=re.IGNORECASE).strip()

            if len(subj) > 2:
                records.append({
                    "date": schedule_date,
                    "building": building_num,
                    "group_name": "ДА-61",
                    "lesson_num": lesson_num,
                    "subject": subj[:100],
                    "room": room,
                    "teacher": "По расписанию"
                })

    return records

def get_schedule():
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(SCHEDULE_PAGE, headers=headers)
    res.encoding = "utf-8"

    soup = BeautifulSoup(res.text, "html.parser")
    
    date_m = re.search(r'на\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4})', res.text)
    schedule_date = date_m.group(1) if date_m else "23 октября"

    now = datetime.now()
    target_date = now + timedelta(days=1) if now.hour >= 14 else now
    target_weekday = target_date.weekday()

    target_building = 3 if target_weekday in [0, 3] else 1

    pdf_targets = []
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True).lower()
        href = urljoin(BASE_URL, a['href'])
        if "расписание" in txt and "групп" in txt:
            if "3" in txt or "энергетиков" in txt:
                pdf_targets.append((href, 3))
            else:
                pdf_targets.append((href, 1))

    pdf_targets.sort(key=lambda x: 0 if x[1] == target_building else 1)

    all_records = []
    for link, b_num in pdf_targets:
        print(f"Проверяем {b_num} корпус: {link}", flush=True)
        try:
            pdf_res = requests.get(link, headers=headers)
            if pdf_res.status_code == 200:
                recs = parse_pdf_for_group(pdf_res.content, b_num, schedule_date)
                if recs:
                    all_records = recs
                    print(f"Успех! Найдено расписание в {b_num} корпусе ({len(recs)} пар)", flush=True)
                    break
        except Exception as e:
            print(f"Ошибка PDF: {e}", flush=True)

    # Полная очистка старых записей перед вставкой новых
    try:
        supabase.table("schedule").delete().neq("lesson_num", -999).execute()
    except Exception as e:
        print(f"Ошибка очистки: {e}", flush=True)

    if all_records:
        supabase.table("schedule").insert(all_records).execute()
        print(f"Готово! В Supabase сохранено {len(all_records)} пар.", flush=True)
    else:
        print("Внимание: пар для ДА-61 не найдено в PDF.", flush=True)

if __name__ == "__main__":
    get_schedule()
