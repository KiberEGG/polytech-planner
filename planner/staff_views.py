"""Рабочее место администратора: сетка расписания на день и ручная правка."""

import datetime
import json

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .models import Lesson, Request, Room, RoomWindow, Teacher
from .rules import check_placement
from .scheduler import run_distribution
from .services import place_lesson, unplace_lesson


def parse_date(value, default=None):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def lesson_json(lesson):
    request = lesson.request
    return {
        "id": lesson.pk,
        "title": lesson.master_class.title,
        "duration": lesson.master_class.duration_min,
        "school": request.school_display,
        "classes": request.classes_display,
        "participants": request.participants,
        "request_id": request.pk,
        "teacher_id": lesson.teacher_id,
        "teacher": lesson.teacher.full_name if lesson.teacher_id else "",
        "room_id": lesson.room_id,
        "start": lesson.start_at.strftime("%H:%M") if lesson.start_at else None,
        "end": lesson.end_at.strftime("%H:%M") if lesson.end_at else None,
        "date": lesson.start_at.date().isoformat() if lesson.start_at else None,
        "status": lesson.status,
        "status_display": lesson.get_status_display(),
        "reason": lesson.conflict_reason,
        "is_manual": lesson.is_manual,
        "needs_pc": lesson.master_class.needs_pc,
        "days": [str(d) for d in request.days.all()],
    }


LESSON_RELATED = ("master_class", "teacher", "request__school", "room__building")


@staff_member_required
def schedule_grid(request):
    date = parse_date(request.GET.get("date"))
    if date is None:
        first = (
            RoomWindow.objects.filter(date__gte=datetime.date.today()).order_by("date").first()
        )
        date = first.date if first else datetime.date.today()

    rooms = list(Room.objects.select_related("building"))
    windows = {}
    for w in RoomWindow.objects.filter(date=date):
        windows.setdefault(w.room_id, []).append(
            {"id": w.pk, "from": f"{w.time_from:%H:%M}", "to": f"{w.time_to:%H:%M}"}
        )
    placed = (
        Lesson.objects.filter(start_at__date=date, room__isnull=False)
        .select_related(*LESSON_RELATED)
        .prefetch_related("request__classes", "request__days")
    )
    unplaced = (
        Lesson.objects.filter(room__isnull=True, request__status=Request.Status.ACCEPTED)
        .select_related(*LESSON_RELATED)
        .prefetch_related("request__classes", "request__days")
        .order_by("request__created_at", "id")
    )
    data = {
        "date": date.isoformat(),
        "rooms": [
            {
                "id": r.pk,
                "label": r.label,
                "site": r.site,
                "capacity": r.capacity,
                "pc": r.pc_count,
                "windows": windows.get(r.pk, []),
            }
            for r in rooms
        ],
        "lessons": [lesson_json(l) for l in placed],
        "unplaced": [lesson_json(l) for l in unplaced],
        "teachers": [{"id": t.pk, "name": t.full_name} for t in Teacher.objects.all()],
    }
    window_dates = (
        RoomWindow.objects.filter(date__gte=date - datetime.timedelta(days=60))
        .values_list("date", flat=True)
        .distinct()
        .order_by("date")[:60]
    )
    return render(
        request,
        "planner/staff/grid.html",
        {
            "date": date,
            "prev": date - datetime.timedelta(days=1),
            "next": date + datetime.timedelta(days=1),
            "window_dates": window_dates,
            "data": data,
        },
    )


def _body(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _result(result, lesson=None, applied=False):
    payload = {"ok": applied, "errors": result.errors, "warnings": result.warnings}
    if lesson is not None:
        lesson.refresh_from_db()
        payload["lesson"] = lesson_json(lesson)
    return JsonResponse(payload)


def _teacher_arg(body):
    if "teacher_id" not in body:
        return ...
    return int(body["teacher_id"]) if body["teacher_id"] else None


@staff_member_required
@require_POST
def api_place(request, pk):
    """Перенести/поставить занятие: {date, room_id, start: "HH:MM", force}."""
    lesson = get_object_or_404(Lesson.objects.select_related("master_class", "request"), pk=pk)
    body = _body(request)
    date = parse_date(body.get("date"))
    room = get_object_or_404(Room.objects.select_related("building"), pk=body.get("room_id"))
    try:
        start_time = datetime.time.fromisoformat(body.get("start", ""))
    except ValueError:
        return JsonResponse({"ok": False, "errors": ["Неверное время."], "warnings": []}, status=400)
    if date is None:
        return JsonResponse({"ok": False, "errors": ["Неверная дата."], "warnings": []}, status=400)
    start = datetime.datetime.combine(date, start_time)
    result = place_lesson(lesson, room, start, _teacher_arg(body), force=bool(body.get("force")))
    applied = not result.errors and (not result.warnings or bool(body.get("force")))
    return _result(result, lesson, applied)


@staff_member_required
@require_POST
def api_teacher(request, pk):
    """Сменить преподавателя: {teacher_id, force}."""
    lesson = get_object_or_404(Lesson.objects.select_related("master_class", "request"), pk=pk)
    body = _body(request)
    teacher_id = _teacher_arg(body)
    if teacher_id is ...:
        return JsonResponse({"ok": False, "errors": ["Не указан преподаватель."], "warnings": []}, status=400)
    if not lesson.is_placed:
        lesson.teacher_id = teacher_id
        lesson.save()
        lesson.refresh_from_db()
        return JsonResponse({"ok": True, "errors": [], "warnings": [], "lesson": lesson_json(lesson)})
    result = check_placement(lesson, lesson.room, lesson.start_at, teacher_id)
    # Смена преподавателя проверяет только его занятость; прочие предупреждения
    # относятся к уже принятому размещению.
    if not result.errors:
        lesson.teacher_id = teacher_id
        lesson.is_manual = True
        lesson.save()
    result.warnings = []
    return _result(result, lesson, applied=not result.errors)


@staff_member_required
@require_POST
def api_unplace(request, pk):
    """Снять занятие с расписания (оно вернётся в список «ждёт»)."""
    lesson = get_object_or_404(Lesson, pk=pk)
    unplace_lesson(lesson)
    lesson.is_manual = False
    lesson.save()
    return JsonResponse({"ok": True, "lesson": lesson_json(lesson)})


@staff_member_required
@require_POST
def api_delete(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk)
    lesson.delete()
    return JsonResponse({"ok": True})


@staff_member_required
@require_POST
def api_distribute(request):
    report = run_distribution()
    return JsonResponse(
        {
            "ok": True,
            "assigned": report.assigned,
            "conflicts": report.conflicts,
            "repeats": report.repeats,
        }
    )


@staff_member_required
@require_POST
def api_window(request):
    """Создать, сдвинуть или удалить окно аудитории.

    {id?, room_id, date, from: "HH:MM", to: "HH:MM", delete?}. Занятия, которые
    перестали помещаться, снимаются со статусом «конфликт» (см. signals.py).
    """
    body = _body(request)
    window = None
    if body.get("id"):
        window = get_object_or_404(RoomWindow, pk=body["id"])
    if body.get("delete"):
        if window is None:
            return JsonResponse({"ok": False, "errors": ["Окно не найдено."]}, status=400)
        before = set(Lesson.objects.filter(status=Lesson.Status.CONFLICT).values_list("pk", flat=True))
        window.delete()
    else:
        try:
            time_from = datetime.time.fromisoformat(body.get("from", ""))
            time_to = datetime.time.fromisoformat(body.get("to", ""))
        except ValueError:
            return JsonResponse({"ok": False, "errors": ["Неверное время."]}, status=400)
        if time_from >= time_to:
            return JsonResponse(
                {"ok": False, "errors": ["Время «с» должно быть раньше времени «по»."]}, status=400
            )
        if window is None:
            window = RoomWindow(
                room=get_object_or_404(Room, pk=body.get("room_id")),
                date=parse_date(body.get("date")),
            )
            if window.date is None:
                return JsonResponse({"ok": False, "errors": ["Неверная дата."]}, status=400)
        window.time_from, window.time_to = time_from, time_to
        before = set(Lesson.objects.filter(status=Lesson.Status.CONFLICT).values_list("pk", flat=True))
        window.save()
    released = Lesson.objects.filter(status=Lesson.Status.CONFLICT).exclude(pk__in=before).count()
    return JsonResponse({"ok": True, "released": released})
