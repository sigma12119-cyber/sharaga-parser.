import os
import io
import re
from urllib.parse import urljoin
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup
import pdfplumber
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

def parse_cropped_lines(lines, building_num, schedule_date):
    any_group_regex = re.compile(r'^[А-ЯA-Z]{2,4}[\s\-_–—]?\d{2}$')
    current_lesson = None
    lesson_data = {}

    for line in lines:
        if re.search(r'[дdДD][аaАA][\s\-_–—]?61', line, re.IGNORECASE):
            continue
        if any_group_regex.match(line):
            break
        if any(day in line.lower() for day in ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота"]):
            continue

        m = re.match(r'^([1-6])(?:\s+(.*))?$', line)
        if m:
            num = int(m.group(1))
            rest = (m.group(2) or "").strip()
            # Пропускаем пустые строки вида "5" или "5 5 5"
            if re.match(r'^[1-6](\s+[1-6])*$', line):
                current_lesson = None
                continue
            current_lesson = num
            if rest:
                lesson_data[current_lesson] = lesson_data.get(current_lesson, "") + " " + rest
        else:
            if current_lesson is not None:
                lesson_data[current_lesson] = lesson_data.get(current_lesson, "") + " " + line

    records = []
    for num in sorted(lesson_data.keys()):
        full_str = clean_text(lesson_data[num])
        if not full_str or len(full_str) < 3:
            continue

        room_m = re.search(r'(?:каб\.?|ауд\.?)\s*([а-яА-Яa-zA-Z0-9\-]+)', full_str, re.IGNORECASE)
        default_room = "Энергетиков" if building_num == 3 else "Салова"
        room = room_m.group(1) if room_m else default_room

        subj = re.sub(r',?\s*(?:каб\.?|ауд\.?)\s*[а-яА-Яa-zA-Z0-9\-]*', '', full_str, flags=re.IGNORECASE).strip()

        if len(subj) > 2:
            records.append({
                "date": schedule_date,
                "building": building_num,
                "group_name": "ДА-61",
                "lesson_num": num,
                "subject": subj[:100],
                "room": room,
                "teacher": "По расписанию"
            })
    return records

def parse_pdf_for_group(pdf_bytes, building_num, schedule_date):
    records = []
    # 1. Пробуем геометрическую вырезку через pdfplumber (search находит даже разорванный текст)
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                matches = page.search(r'[ДдDd][АаAa][\s\-_–—]*61', regex=True)
                if not matches:
                    continue

                target_box = matches[0]
                W, H = page.width, page.height
                cx = (target_box['x0'] + target_box['x1']) / 2

                if cx < W * 0.36:
                    x0, x1 = 0, W * 0.35
                elif cx < W * 0.68:
                    x0, x1 = W * 0.34, W * 0.68
                else:
                    x0, x1 = W * 0.67, W

                y0 = max(0, target_box['top'] - 5)
                y1 = min(H, target_box['top'] + 250)

                cropped = page.crop((x0, y0, x1, y1))
                text = cropped.extract_text(x_tolerance=2, y_tolerance=3)
                if text:
                    lines = [clean_text(line) for line in text.split('\n') if clean_text(line)]
                    print(f"[pdfplumber стр.{page_idx+1}] Вырезанный текст:\n" + "\n".join(lines), flush=True)
                    records = parse_cropped_lines(lines, building_num, schedule_date)
                    if records:
                        return records
    except Exception as e:
        print(f"Ошибка pdfplumber: {e}", flush=True)

    # 2. Резервный метод через pypdf (если pdfplumber не сработал)
    print(f"[{building_num} корп.] Включаем резервный разбор pypdf...", flush=True)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    all_lines = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            for line in t.split("\n"):
                c = clean_text(line)
                if c:
                    all_lines.append(c)

    group_regex = re.compile(r'[дdДD][аaАA][\s\-_–—]?61', re.IGNORECASE)
    found_idx = -1
    for i, line in enumerate(all_lines):
        if group_regex.search(line):
            found_idx = i
            print(f"[pypdf] Найдена ДА-61 на строке {i}: {line}", flush=True)
            break

    if found_idx != -1:
        # Склеиваем разорванные переносы кабинетов перед разбором
        block = all_lines[found_idx + 1 : found_idx + 22]
        for idx, b_line in enumerate(block):
            print(f"  строка {idx}: {b_line}", flush=True)
            m_num = re.match(r'^([1-4])\s+(.*)', b_line)
            if m_num:
                num = int(m_num.group(1))
                content = m_num.group(2)
                # Отрезаем вторую и третью колонки (все что идет после следующего номера той же пары)
                first_col = re.split(rf'\s+{num}\s+', content)[0].strip()
                # Ищем кабинет в самой строке или на следующей строчке (куда pypdf переносит номер)
                room = "Салова" if building_num == 1 else "Энергетиков"
                room_m = re.search(r'(?:каб\.?|ауд\.?)\s*([0-9]{2,3}|ДТ\d|[0-9]+)', first_col, re.IGNORECASE)
                if room_m:
                    room = room_m.group(1)
                elif idx + 1 < len(block) and re.match(r'^([0-9]{2,3}|ДТ\d)', block[idx + 1]):
                    room = re.match(r'^([0-9]{2,3}|ДТ\d)', block[idx + 1]).group(1)

                subj = re.sub(r',?\s*(?:каб\.?|ауд\.?).*', '', first_col, flags=re.IGNORECASE).strip()
                if len(subj) > 2 and "пятница" not in subj.lower():
                    records.append({
                        "date": schedule_date,
                        "building": building_num,
                        "group_name": "ДА-61",
                        "lesson_num": num,
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

    # Московское время (UTC+3)
    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
    target_date = msk_now + timedelta(days=1) if msk_now.hour >= 15 else msk_now
    target_weekday = target_date.weekday()
    target_building = 3 if target_weekday in [0, 3] else 1
    print(f"Время МСК: {msk_now.strftime('%H:%M')}, День недели: {target_weekday}, Целевой корпус: {target_building}", flush=True)

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

    if all_records:
        try:
            supabase.table("schedule").delete().eq("group_name", "ДА-61").execute()
        except Exception as e:
            print(f"Ошибка очистки: {e}", flush=True)

        supabase.table("schedule").insert(all_records).execute()
        print(f"Готово! В Supabase сохранено {len(all_records)} пар.", flush=True)
    else:
        print("Внимание: пар для ДА-61 не найдено в PDF.", flush=True)

if __name__ == "__main__":
    get_schedule()
    
