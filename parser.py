import os
import io
import re
from urllib.parse import urljoin
from datetime import datetime, timedelta, timezone
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
    records = []
    any_group_regex = re.compile(r'^[А-ЯA-Z]{2,4}[\s\-_–—]?\d{2}$')

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            matches = page.search(r'[ДдDd][АаAa][\s\-_–—]*61', regex=True)
            if not matches:
                continue

            target_box = matches[0]
            W, H = page.width, page.height
            cx = (target_box['x0'] + target_box['x1']) / 2

            # Определяем границы колонки ДА-61 (левая, средняя или правая треть листа)
            if cx < W * 0.36:
                col_x0, col_x1 = 0, W * 0.34
            elif cx < W * 0.68:
                col_x0, col_x1 = W * 0.34, W * 0.67
            else:
                col_x0, col_x1 = W * 0.67, W

            col_w = col_x1 - col_x0
            # Граница между столбцом "Предмет" и столбцом "Препод + Кабинет" (примерно 46% ширины колонки)
            split_x = col_x0 + col_w * 0.46

            # Находим, где заканчивается таблица ДА-61 (до следующей группы снизу)
            y_top = target_box['bottom'] + 2
            y_bottom = min(H, y_top + 230)

            full_col = page.crop((col_x0, y_top, col_x1, y_bottom))
            words = full_col.extract_words()

            # Ограничиваем высоту до следующей шапки группы (например ДР-33)
            for w in words:
                if any_group_regex.match(w['text']) and w['top'] > y_top + 30:
                    y_bottom = w['top'] - 2
                    break

            # Ищем координаты Y для цифр 1, 2, 3, 4, 5, 6 в самом левом краю колонки
            num_strip = page.crop((col_x0, y_top, col_x0 + col_w * 0.12, y_bottom))
            num_words = num_strip.extract_words()

            lesson_anchors = []
            for nw in num_words:
                if re.match(r'^[1-6]$', nw['text']):
                    num_val = int(nw['text'])
                    if not any(a[0] == num_val for a in lesson_anchors):
                        lesson_anchors.append((num_val, nw['top'], nw['bottom']))

            lesson_anchors.sort(key=lambda x: x[1])

            # Для каждой пары вырезаем строгую горизонтальную полосу (от середины между цифрами)
            for i, (num_val, n_top, n_bot) in enumerate(lesson_anchors):
                n_mid = (n_top + n_bot) / 2
                if i == 0:
                    row_y0 = max(y_top, n_top - 12)
                else:
                    prev_mid = (lesson_anchors[i-1][1] + lesson_anchors[i-1][2]) / 2
                    row_y0 = (prev_mid + n_mid) / 2

                if i < len(lesson_anchors) - 1:
                    next_mid = (lesson_anchors[i+1][1] + lesson_anchors[i+1][2]) / 2
                    row_y1 = (n_mid + next_mid) / 2
                else:
                    row_y1 = min(y_bottom, n_bot + 15)

                # Вырезаем отдельно ЛЕВУЮ ячейку (предмет) и ПРАВУЮ ячейку (препод + кабинет)
                left_box = page.crop((col_x0 + col_w * 0.08, row_y0, split_x, row_y1))
                right_box = page.crop((split_x, row_y0, col_x1, row_y1))

                subj_raw = clean_text(left_box.extract_text() or "")
                right_raw = clean_text(right_box.extract_text() or "")

                # Убираем случайную цифру номера пары или дату из начала предмета
                subj_raw = re.sub(r'^[1-6]\s*', '', subj_raw).strip()
                if "пятница" in right_raw.lower() or "четверг" in right_raw.lower():
                    right_raw = re.sub(r'(?:Понедельник|Вторник|Среда|Четверг|Пятница|Суббота)\s*\d{2}\.\d{2}\.\d{2}', '', right_raw, flags=re.IGNORECASE).strip()

                if not subj_raw and not right_raw:
                    continue

                # Вытаскиваем кабинет из правой ячейки (включая переносы типа "каб 412" или "каб ДТ3")
                default_room = "Энергетиков" if building_num == 3 else "Салова"
                room_m = re.search(r'(?:каб\.?|ауд\.?)\s*([а-яА-Яa-zA-Z0-9\-]+)', right_raw, re.IGNORECASE)
                room = room_m.group(1) if room_m else default_room

                # Вытаскиваем ФИО преподавателя (всё что в правой ячейке до слова "каб")
                teacher_str = re.sub(r',?\s*(?:каб\.?|ауд\.?)\s*[а-яА-Яa-zA-Z0-9\-]*', '', right_raw, flags=re.IGNORECASE).strip()

                full_subject = f"{subj_raw} ({teacher_str})" if teacher_str else subj_raw

                if len(subj_raw) >= 2:
                    print(f"  Пара {num_val}: {full_subject} | Каб: {room}", flush=True)
                    records.append({
                        "date": schedule_date,
                        "building": building_num,
                        "group_name": "ДА-61",
                        "lesson_num": num_val,
                        "subject": full_subject[:100],
                        "room": room,
                        "teacher": teacher_str or "По расписанию"
                    })
            if records:
                return records
    return records

def get_schedule():
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(SCHEDULE_PAGE, headers=headers)
    res.encoding = "utf-8"

    soup = BeautifulSoup(res.text, "html.parser")
    date_m = re.search(r'на\s+(\d{1,2}\s+[а-яА-Я]+\s+\d{4})', res.text)
    schedule_date = date_m.group(1) if date_m else "23 октября"

    msk_now = datetime.now(timezone.utc) + timedelta(hours=3)
    target_date = msk_now + timedelta(days=1) if msk_now.hour >= 15 else msk_now
    target_weekday = target_date.weekday()
    target_building = 3 if target_weekday in [0, 3] else 1
    print(f"Время МСК: {msk_now.strftime('%H:%M')}, Целевой корпус: {target_building}", flush=True)

    pdf_targets = []
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True).lower()
        href = urljoin(BASE_URL, a['href'])
        href_low = href.lower()
        if ".pdf" in href_low and ("grup" in href_low or "групп" in txt or "расписание" in txt):
            # Определяем корпус СТРОГО по ссылке или точному совпадению "3 корп" (чтобы "23 октября" не путалось с 3 корпусом!)
            if "3-korp" in href_low or "3_korp" in href_low or re.search(r'\b3\s*корп', txt) or "энергетиков" in txt:
                pdf_targets.append((href, 3))
            elif "1-2" in href_low or re.search(r'1[\s,\-]*2\s*корп', txt) or "салова" in txt:
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
    
