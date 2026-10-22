import os
import io
import re
from urllib.parse import urljoin
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import pdfplumber
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
    group_regex = re.compile(r'\b[дdДD][аaАA][\s\-_–—]?61\b', re.IGNORECASE)
    any_group_regex = re.compile(r'^[А-ЯA-Z]{2,4}[\s\-_–—]?\d{2}$')

    records = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            target_word = None
            for w in words:
                if group_regex.search(w['text']):
                    target_word = w
                    break

            if not target_word:
                continue

            # Определяем, в какой из 3 колонок (левая, средняя, правая) находится ДА-61
            W = page.width
            H = page.height
            cx = (target_word['x0'] + target_word['x1']) / 2

            if cx < W * 0.35:
                x0, x1 = 0, W * 0.345
            elif cx < W * 0.68:
                x0, x1 = W * 0.345, W * 0.675
            else:
                x0, x1 = W * 0.675, W

            # Вырезаем прямоугольник ТОЛЬКО нашей группы (от шапки ДА-61 вниз)
            y0 = max(0, target_word['top'] - 5)
            y1 = min(H, target_word['top'] + 260)

            cropped = page.crop((x0, y0, x1, y1))
            text = cropped.extract_text(layout=False)
            if not text:
                continue

            lines = [clean_text(line) for line in text.split('\n') if clean_text(line)]
            print(f"[{building_num} корп.] Вырезанный блок ДА-61:\n" + "\n".join(lines), flush=True)

            current_lesson = None
            lesson_data = {}

            for line in lines[1:]:
                # Если наткнулись на следующую группу снизу (например ДР-33) — стоп!
                if any_group_regex.match(line):
                    break
                if any(day in line.lower() for day in ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота"]):
                    continue

                # Проверяем, начинается ли строка с номера пары (1..6)
                m = re.match(r'^([1-6])(?:\s+(.*))?$', line)
                if m:
                    num = int(m.group(1))
                    rest = (m.group(2) or "").strip()
                    current_lesson = num
                    if rest:
                        lesson_data[current_lesson] = lesson_data.get(current_lesson, "") + " " + rest
                else:
                    # Если это перенос номера кабинета на вторую строчку (например "412" или "ДТ3")
                    if current_lesson is not None:
                        lesson_data[current_lesson] = lesson_data.get(current_lesson, "") + " " + line

            for num in sorted(lesson_data.keys()):
                full_str = clean_text(lesson_data[num])
                if not full_str:
                    continue

                # Вытаскиваем кабинет после слова "каб"
                room_m = re.search(r'(?:каб\.?|ауд\.?)\s*([а-яА-Яa-zA-Z0-9\-]+)', full_str, re.IGNORECASE)
                default_room = "Энергетиков" if building_num == 3 else "Салова"
                room = room_m.group(1) if room_m else default_room

                # Убираем "каб ..." из названия предмета
                subj = re.sub(r',?\s*(?:каб\.?|ауд\.?)\s*[а-яА-Яa-zA-Z0-9\-]+', '', full_str, flags=re.IGNORECASE).strip()

                records.append({
                    "date": schedule_date,
                    "building": building_num,
                    "group_name": "ДА-61",
                    "lesson_num": num,
                    "subject": subj[:100],
                    "room": room,
                    "teacher": "По расписанию"
                })
            break

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

    # Очищаем все старые записи ДА-61
    try:
        supabase.table("schedule").delete().eq("group_name", "ДА-61").execute()
    except Exception as e:
        print(f"Ошибка очистки: {e}", flush=True)

    if all_records:
        supabase.table("schedule").upsert(all_records).execute()
        print(f"Готово! В Supabase сохранено {len(all_records)} пар.", flush=True)
    else:
        print("Внимание: пар для ДА-61 не найдено в PDF.", flush=True)

if __name__ == "__main__":
    get_schedule()
