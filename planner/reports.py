"""Просмотр расписания в трёх разрезах и выгрузка в Excel (раздел 8)."""

import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Lesson

ASSIGNED = Lesson.objects.filter(status=Lesson.Status.ASSIGNED, room__isnull=False).select_related(
    "master_class", "teacher", "room__building", "request__school"
).prefetch_related("request__classes")


def _time(l):
    return f"{l.start_at:%H:%M}–{l.end_at:%H:%M}"


def _mark(l):
    return "вручную" if l.is_manual else "авто"


def by_day(date):
    lessons = ASSIGNED.filter(start_at__date=date).order_by(
        "room__building__address", "room__building__code", "room__number", "start_at"
    )
    columns = ["Площадка", "Аудитория", "Время", "Мастер-класс", "Школа", "Классы", "Участников", "Преподаватель", "Пометка"]
    rows = [
        [l.room.site, l.room.label, _time(l), l.master_class.title, l.request.school_display,
         l.request.classes_display, l.request.participants, l.teacher or "—", _mark(l)]
        for l in lessons
    ]
    return columns, rows


def by_school(school, date_from=None, date_to=None):
    lessons = ASSIGNED.filter(request__school=school)
    if date_from:
        lessons = lessons.filter(start_at__date__gte=date_from)
    if date_to:
        lessons = lessons.filter(start_at__date__lte=date_to)
    columns = ["Дата", "Время", "Площадка", "Аудитория", "Мастер-класс", "Классы", "Участников", "Преподаватель", "Заявка"]
    rows = [
        [l.start_at.strftime("%d.%m.%Y"), _time(l), l.room.site, l.room.label, l.master_class.title,
         l.request.classes_display, l.request.participants, l.teacher or "—", f"№{l.request_id}"]
        for l in lessons.order_by("start_at")
    ]
    return columns, rows


def by_teacher(teacher, date_from=None, date_to=None):
    lessons = ASSIGNED.filter(teacher=teacher)
    if date_from:
        lessons = lessons.filter(start_at__date__gte=date_from)
    if date_to:
        lessons = lessons.filter(start_at__date__lte=date_to)
    columns = ["Дата", "Время", "Площадка", "Аудитория", "Мастер-класс", "Школа", "Классы", "Участников"]
    rows = [
        [l.start_at.strftime("%d.%m.%Y"), _time(l), l.room.site, l.room.label, l.master_class.title,
         l.request.school_display, l.request.classes_display, l.request.participants]
        for l in lessons.order_by("start_at")
    ]
    return columns, rows


def to_xlsx(title, columns, rows):
    wb = Workbook()
    ws = wb.active
    # В названии листа Excel нельзя использовать : \ / ? * [ ]
    ws.title = re.sub(r"[:\\/?*\[\]]", " ", title)[:31]
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(columns)
    header_fill = PatternFill("solid", fgColor="EDE3F4")
    for cell in ws[3]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for row in rows:
        ws.append([str(v) if not isinstance(v, (int, float)) else v for v in row])
    for i, col in enumerate(columns, start=1):
        width = max([len(str(col))] + [len(str(r[i - 1])) for r in rows]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 50)
    for row in ws.iter_rows(min_row=4):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
