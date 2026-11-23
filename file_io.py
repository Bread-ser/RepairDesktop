from __future__ import annotations
import csv
from datetime import date
from html import escape
from pathlib import Path
import openpyxl
from config import STATUS_LABELS

EXPORT_HEADERS = [
    "№",
    "Дата",
    "Тип техники",
    "Модель",
    "Проблема",
    "Статус",
    "Дата завершения",
    "Запчасти",
    "Клиент",
    "Телефон",
    "Мастер",
]


def _request_to_row(r: dict) -> list:
    return [
        r.get("request_id", ""),
        r.get("start_date", ""),
        r.get("tech_type", ""),
        r.get("tech_model", ""),
        r.get("problem", ""),
        STATUS_LABELS.get(r.get("status", ""), r.get("status", "")),
        r.get("completion_date") or "",
        r.get("repair_parts") or "",
        r.get("client_fio") or "",
        r.get("client_phone") or "",
        r.get("master_fio") or "",
        ]


def export_requests_csv(filepath: str, items: list[dict]) -> None:
    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(EXPORT_HEADERS)
        for r in items:
            writer.writerow(_request_to_row(r))


def export_requests_xlsx(filepath: str, items: list[dict]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Заявки"
    ws.append(EXPORT_HEADERS)
    for r in items:
        ws.append(_request_to_row(r))
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 45)
    wb.save(filepath)


def import_requests_file(filepath: str, default_client_id: int) -> list[dict]:
    """
    Читает CSV (разделитель ';' или ',') или XLSX.
    Ожидаемые колонки (по порядку или по заголовку):
    tech_type, tech_model, problem, [start_date], [client_id]
    """
    path = Path(filepath)
    rows: list[list[str]] = []

    if path.suffix.lower() == ".xlsx":
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            if any(v is not None and str(v).strip() for v in row):
                rows.append([str(v).strip() if v is not None else "" for v in row])
    else:
        with open(filepath, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                if any(cell.strip() for cell in row):
                    rows.append([cell.strip() for cell in row])

    if not rows:
        return []

    # Пропускаем строку заголовка, если она похожа на шапку
    first_lower = " ".join(rows[0]).lower()
    if any(k in first_lower for k in ("тип", "type", "модель", "model", "проблема", "problem")):
        rows = rows[1:]

    result = []
    today = date.today().isoformat()
    for row in rows:
        if len(row) < 3:
            continue
        tech_type, tech_model, problem = row[0], row[1], row[2]
        if not tech_type or not tech_model or not problem:
            continue
        start_date = row[3] if len(row) > 3 and len(row[3]) == 10 else today
        client_id = default_client_id
        if len(row) > 4 and row[4].isdigit():
            client_id = int(row[4])
        result.append(
            {
                "tech_type": tech_type,
                "tech_model": tech_model,
                "problem": problem,
                "start_date": start_date,
                "client_id": client_id,
            }
        )
    return result


def build_request_print_html(req: dict) -> str:
    status = STATUS_LABELS.get(req.get("status", ""), req.get("status", ""))
    return f"""
    <html>
    <head><meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; font-size: 12pt; color: #111; }}
        h1 {{ font-size: 16pt; margin-bottom: 4px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ border: 1px solid #888; padding: 6px 8px; text-align: left; }}
        th {{ background: #f0f0f0; width: 32%; }}
        .sign {{ margin-top: 36px; display: flex; justify-content: space-between; }}
    </style></head>
    <body>
        <h1>Квитанция по заявке №{escape(str(req.get("request_id", "")))}</h1>
        <p>Дата создания: {escape(str(req.get("start_date", "")))} | Статус: <b>{escape(status)}</b></p>
        <table>
            <tr><th>Тип техники</th><td>{escape(str(req.get("tech_type", "")))}</td></tr>
            <tr><th>Модель</th><td>{escape(str(req.get("tech_model", "")))}</td></tr>
            <tr><th>Заказчик</th><td>{escape(str(req.get("client_fio", "")))} ({escape(str(req.get("client_phone", "")))})</td></tr>
            <tr><th>Мастер</th><td>{escape(str(req.get("master_fio") or "Не назначен"))}</td></tr>
            <tr><th>Описание проблемы</th><td>{escape(str(req.get("problem", "")))}</td></tr>
            <tr><th>Запчасти</th><td>{escape(str(req.get("repair_parts") or "—"))}</td></tr>
            <tr><th>Дата завершения</th><td>{escape(str(req.get("completion_date") or "—"))}</td></tr>
        </table>
        <p style="margin-top: 32px;">Подпись заказчика: ___________________ &nbsp;&nbsp;&nbsp; Подпись мастера: ___________________</p>
    </body>
    </html>
    """


def build_report_print_html(stats: dict, date_from: str = "", date_to: str = "") -> str:
    period = f"с {date_from or 'начала'} по {date_to or 'сегодня'}"
    type_rows = "".join(
        f"<tr><td>{escape(str(r.get('tech_type', '')))}</td>"
        f"<td>{r.get('total', 0)}</td>"
        f"<td>{r.get('done', 0)}</td>"
        f"<td>{r.get('avg_days') if r.get('avg_days') is not None else '—'}</td></tr>"
        for r in stats.get("by_type", [])
    )
    master_rows = "".join(
        f"<tr><td>{escape(str(r.get('master', '')))}</td>"
        f"<td>{r.get('total', 0)}</td>"
        f"<td>{r.get('done', 0)}</td></tr>"
        for r in stats.get("by_master", [])
    )
    return f"""
    <html>
    <head><meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; font-size: 11pt; color: #111; }}
        h1 {{ font-size: 16pt; }}
        h2 {{ font-size: 13pt; margin-top: 18px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
        th, td {{ border: 1px solid #888; padding: 6px 8px; text-align: left; }}
        th {{ background: #f0f0f0; }}
    </style></head>
    <body>
        <h1>Отчёт по заявкам на ремонт</h1>
        <p>Период: {escape(period)} | Всего заявок: <b>{stats.get("total", 0)}</b> | Средний срок ремонта: <b>{stats.get("avg_days") or "—"} дн.</b></p>
        <h2>По типам техники</h2>
        <table>
            <tr><th>Тип техники</th><th>Всего</th><th>Готово</th><th>Ср. дней</th></tr>
            {type_rows}
        </table>
        <h2>По мастерам</h2>
        <table>
            <tr><th>Мастер</th><th>Заявок</th><th>Готово</th></tr>
            {master_rows}
        </table>
    </body>
    </html>
    """