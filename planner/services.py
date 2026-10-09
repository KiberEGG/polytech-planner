"""Операции над заявками и занятиями, которые используют админка и сетка."""

import re

from django.db import transaction

from .models import Lesson, Request, School, SchoolClass
from .rules import check_placement, lessons_outside_windows

WINDOW_SHIFT_REASON = "После изменения окна аудитории занятие в него не помещается."


def split_classes(text):
    """«9а, 9б», «9а и 9б» -> ["9а", "9б"]."""
    parts = re.split(r",|;|\sи\s", text or "")
    return [p.strip() for p in parts if p.strip()]


@transaction.atomic
def accept_request(request, school=None):
    """Принимает заявку: при необходимости заводит школу и классы в справочник.

    school — школа из справочника, которую выбрал администратор; если не задана,
    ищется по названию из заявки, а если такой нет — создаётся.
    """
    if school is not None:
        request.school = school
    if request.school_id is None:
        name = request.school_name.strip()
        school = School.objects.filter(name__iexact=name).first()
        if school is None:
            school = School.objects.create(
                name=name, contact_person=request.contact_name, phone=request.phone
            )
        request.school = school
    if not request.classes.exists():
        for name in split_classes(request.classes_text):
            school_class, _ = SchoolClass.objects.get_or_create(
                school=request.school, name=name
            )
            request.classes.add(school_class)
    request.status = Request.Status.ACCEPTED
    request.save()


def reject_request(request):
    request.status = Request.Status.REJECTED
    request.save()
    # Отклонённая заявка не должна занимать аудитории.
    request.lessons.exclude(status=Lesson.Status.PENDING).update(
        room=None, start_at=None, end_at=None, status=Lesson.Status.PENDING,
        conflict_reason="", is_manual=False,
    )


@transaction.atomic
def place_lesson(lesson, room, start, teacher_id=..., force=False):
    """Ручная постановка или перенос занятия.

    Жёсткие правила нарушить нельзя; по мягким — нужен force после предупреждения.
    Возвращает CheckResult; занятие сохраняется, только если ошибок нет и
    предупреждений нет или они подтверждены.
    """
    result = check_placement(lesson, room, start, teacher_id)
    if result.errors or (result.warnings and not force):
        return result
    if teacher_id is not ...:
        lesson.teacher_id = teacher_id
    lesson.room = room
    lesson.start_at = start
    lesson.end_at = start + lesson.master_class_duration
    lesson.status = Lesson.Status.ASSIGNED
    lesson.conflict_reason = ""
    lesson.is_manual = True
    lesson.save()
    return result


def unplace_lesson(lesson, status=Lesson.Status.PENDING, reason=""):
    lesson.unplace()
    lesson.status = status
    lesson.conflict_reason = reason
    lesson.save()


def release_lessons_outside_windows(room_id, date):
    """Занятия, которые после сдвига окна перестали помещаться, получают «конфликт»."""
    released = lessons_outside_windows(room_id, date)
    for lesson in released:
        unplace_lesson(lesson, Lesson.Status.CONFLICT, WINDOW_SHIFT_REASON)
    return released


def sync_request_lessons(request, master_classes=None):
    """Для заявки на мероприятие — день из мероприятия; занятия — по мастер-классам.

    Если master_classes не переданы и у заявки на мероприятие ещё нет занятий,
    берутся все мастер-классы мероприятия.
    """
    from .models import RequestDay

    if request.event_id:
        event = request.event
        request.days.exclude(
            date=event.date, time_from=event.time_from, time_to=event.time_to
        ).delete()
        RequestDay.objects.get_or_create(
            request=request, date=event.date, time_from=event.time_from, time_to=event.time_to
        )
        if master_classes is None and not request.lessons.exists():
            master_classes = event.master_classes.all()
    for mc in master_classes or ():
        Lesson.objects.get_or_create(request=request, master_class=mc)
