"""Автоматическое распределение (раздел 6 концепции).

Распределение идёт по очереди — заявка за заявкой, занятие за занятием.
Что не встало, получает статус «конфликт» с причиной.
"""

import datetime
from dataclasses import dataclass, field

from django.db import transaction

from .models import Lesson, Request, Room
from .rules import GAP, DayState, LessonInfo, RepeatIndex, Slot, room_suits, slot_from_lesson

REASON_CAPACITY = "Группа не помещается ни в одну аудиторию площадки."
REASON_PC = "Нет аудитории с нужным числом ПК."
REASON_BOARD = "Нет аудитории с нужной доской."
REASON_NO_TIME = "Нет свободного времени в окнах аудиторий."
REASON_TEACHER = "Занят преподаватель."
REASON_NO_DAYS = "В заявке не указаны доступные дни."


@dataclass
class Placement:
    room: Room
    start: datetime.datetime
    end: datetime.datetime


@dataclass
class Variant:
    """Вариант размещения заявки: один день и одна площадка."""

    date: datetime.date
    site: str
    placements: dict = field(default_factory=dict)  # lesson_id -> Placement
    failures: dict = field(default_factory=dict)  # lesson_id -> причина


@dataclass
class RunReport:
    assigned: int = 0
    conflicts: int = 0
    repeats: int = 0
    requests: int = 0


class Scheduler:
    def __init__(self):
        self.rooms = list(Room.objects.select_related("building"))
        self.sites = sorted({r.site for r in self.rooms})
        self._days = {}

    def day_state(self, date):
        if date not in self._days:
            self._days[date] = DayState.load(date)
        return self._days[date]

    def run(self, requests=None):
        report = RunReport()
        if requests is None:
            requests = Request.objects.filter(status=Request.Status.ACCEPTED)
        for request in requests.order_by("created_at", "id"):
            with transaction.atomic():
                self.schedule_request(request, report)
        return report

    def schedule_request(self, request, report):
        lessons = list(
            request.lessons.filter(is_manual=False)
            .exclude(status=Lesson.Status.ASSIGNED)
            .select_related("master_class")
        )
        if not lessons:
            return
        report.requests += 1
        class_ids = frozenset(request.classes.values_list("id", flat=True))
        infos = {l.pk: LessonInfo.from_lesson(l, class_ids) for l in lessons}
        days = list(request.days.all())
        if not days:
            for lesson in lessons:
                self._mark(lesson, Lesson.Status.CONFLICT, REASON_NO_DAYS, report)
            return

        # Уже стоящие занятия заявки закрепляют день и площадку.
        placed = list(
            request.lessons.filter(status=Lesson.Status.ASSIGNED, room__isnull=False)
            .select_related("room__building")
        )
        fixed_date = placed[0].start_at.date() if placed else None
        fixed_site = placed[0].room.site if placed else None

        repeats = RepeatIndex.load(
            class_ids,
            [i.master_class.pk for i in infos.values()],
            days[0].date,
        )
        # Повтор: мастер-класс уже стоит в другой день — во всех доступных днях.
        candidates = []
        for lesson in lessons:
            info = infos[lesson.pk]
            repeat_dates = [repeats.repeat_date(info, d.date) for d in days]
            if all(repeat_dates):
                self._mark(
                    lesson,
                    Lesson.Status.REPEAT,
                    f"Мастер-класс уже стоит у класса {repeat_dates[0]:%d.%m.%Y}.",
                    report,
                )
            else:
                candidates.append(lesson)
        if not candidates:
            return

        sites = [request.site] if request.site else self.sites
        if fixed_site:
            sites = [fixed_site]
        best = None
        for day in days:
            if fixed_date and day.date != fixed_date:
                continue
            for site in sites:
                variant = self.try_variant(day, site, candidates, infos, repeats)
                if len(variant.placements) == len(candidates):
                    best = variant
                    break
                if best is None or len(variant.placements) > len(best.placements):
                    best = variant
            if best and len(best.placements) == len(candidates):
                break

        if best is None:
            for lesson in candidates:
                self._mark(lesson, Lesson.Status.CONFLICT, REASON_NO_TIME, report)
            return
        state = self.day_state(best.date)
        for lesson in candidates:
            p = best.placements.get(lesson.pk)
            if p is None:
                reason = best.failures.get(lesson.pk, REASON_NO_TIME)
                self._mark(lesson, Lesson.Status.CONFLICT, reason, report)
                continue
            lesson.room = p.room
            lesson.start_at = p.start
            lesson.end_at = p.end
            lesson.status = Lesson.Status.ASSIGNED
            lesson.conflict_reason = ""
            lesson.is_manual = False
            lesson.save()
            state.add(slot_from_lesson(lesson, class_ids))
            repeats.add(infos[lesson.pk], best.date)
            report.assigned += 1

    def _mark(self, lesson, status, reason, report):
        lesson.unplace()
        lesson.status = status
        lesson.conflict_reason = reason
        lesson.save()
        if status == Lesson.Status.REPEAT:
            report.repeats += 1
        else:
            report.conflicts += 1

    def try_variant(self, day, site, lessons, infos, repeats):
        """Пробует поставить все занятия заявки в один день на одну площадку."""
        variant = Variant(day.date, site)
        base = self.day_state(day.date)
        state = DayState(day.date, list(base.slots), base.windows)
        site_rooms = [r for r in self.rooms if r.site == site]

        suitable = {}
        for lesson in lessons:
            info = infos[lesson.pk]
            suitable[lesson.pk] = [r for r in site_rooms if not room_suits(info, r)]
        # Первыми — те, кому подходит меньше всего аудиторий.
        order = sorted(lessons, key=lambda l: (len(suitable[l.pk]), l.pk))

        for lesson in order:
            info = infos[lesson.pk]
            if repeats.repeat_date(info, day.date):
                variant.failures[lesson.pk] = "Мастер-класс уже стоит у класса в другой день."
                continue
            rooms = suitable[lesson.pk]
            if not rooms:
                variant.failures[lesson.pk] = self._room_reason(info, site_rooms)
                continue
            placement = self.find_slot(state, info, rooms, day)
            if placement is None:
                no_teacher = LessonInfo(**{**info.__dict__, "teacher_id": None})
                if info.teacher_id and self.find_slot(state, no_teacher, rooms, day):
                    variant.failures[lesson.pk] = REASON_TEACHER
                else:
                    variant.failures[lesson.pk] = REASON_NO_TIME
                continue
            variant.placements[lesson.pk] = placement
            state.add(
                Slot(
                    lesson_id=lesson.pk,
                    request_id=info.request_id,
                    master_class_id=info.master_class.pk,
                    room_id=placement.room.pk,
                    building_id=placement.room.building_id,
                    site=site,
                    teacher_id=info.teacher_id,
                    start=placement.start,
                    end=placement.end,
                    class_ids=info.class_ids,
                )
            )
        return variant

    @staticmethod
    def _room_reason(info, site_rooms):
        fits = [r for r in site_rooms if r.capacity >= info.participants]
        if not fits:
            return REASON_CAPACITY
        if info.master_class.needs_pc:
            fits = [r for r in fits if r.pc_count >= info.participants]
            if not fits:
                return REASON_PC
        return REASON_BOARD

    def find_slot(self, state, info, rooms, day):
        """Лучшее место: раньше, в корпусе группы, в самой маленькой аудитории."""
        duration = info.duration
        group_slots = state.group_slots(info)
        group_buildings = {s.building_id for s in group_slots}
        best_key, best = None, None
        for room in rooms:
            for start in self._start_candidates(state, info, room, day):
                end = start + duration
                if end > day.end:
                    continue
                if state.hard_violations(info, room, start, end):
                    continue
                key = (start, room.building_id not in group_buildings, room.capacity, room.pk)
                if best_key is None or key < best_key:
                    best_key, best = key, Placement(room, start, end)
                break  # для аудитории подходит самое раннее время
        return best

    @staticmethod
    def _start_candidates(state, info, room, day):
        """Самое раннее допустимое начало — либо начало окна/дня, либо сразу после
        какого-то занятия (аудитории, группы или преподавателя)."""
        points = set()
        for w_start, w_end in state.windows.get(room.pk, ()):
            if w_end > day.start and w_start < day.end:
                points.add(max(w_start, day.start))
        if not points:
            return []
        for s in state.slots:
            if s.room_id == room.pk or s.request_id == info.request_id or (info.class_ids & s.class_ids):
                points.add(s.end + GAP)
            if info.teacher_id and s.teacher_id == info.teacher_id:
                points.add(s.end)
        return sorted(p for p in points if day.start <= p < day.end)


def run_distribution(requests=None):
    return Scheduler().run(requests)
