"""Правила расписания (раздел 5 концепции).

Жёсткие правила система не даёт нарушить даже вручную, мягкие соблюдает
автоматика, а администратор может обойти их после предупреждения.

Проверки работают над состоянием в памяти (DayState), чтобы одно и то же
использовалось и при автоматическом распределении, и при ручной правке.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field


from .models import Lesson, MasterClass, Room, RoomWindow, academic_year_bounds

GAP = datetime.timedelta(minutes=10)


@dataclass
class Slot:
    """Занятие, уже стоящее в расписании."""

    lesson_id: int
    request_id: int
    master_class_id: int
    room_id: int
    building_id: int
    site: str
    teacher_id: int | None
    start: datetime.datetime
    end: datetime.datetime
    class_ids: frozenset = field(default_factory=frozenset)


@dataclass
class LessonInfo:
    """Что нужно знать о занятии, чтобы проверить его размещение."""

    lesson_id: int | None
    request_id: int
    master_class: MasterClass
    teacher_id: int | None
    participants: int
    class_ids: frozenset
    allow_repeat: bool

    @property
    def duration(self):
        return datetime.timedelta(minutes=self.master_class.duration_min)

    @classmethod
    def from_lesson(cls, lesson, class_ids=None):
        request = lesson.request
        if class_ids is None:
            class_ids = frozenset(request.classes.values_list("id", flat=True))
        return cls(
            lesson_id=lesson.pk,
            request_id=request.pk,
            master_class=lesson.master_class,
            teacher_id=lesson.teacher_id,
            participants=request.participants,
            class_ids=class_ids,
            allow_repeat=request.allow_repeat or lesson.allow_repeat,
        )


def _overlaps(a_start, a_end, b_start, b_end, gap=datetime.timedelta(0)):
    return a_start < b_end + gap and b_start < a_end + gap


def same_group(info, slot):
    if info.request_id == slot.request_id:
        return True
    return bool(info.class_ids & slot.class_ids)


class DayState:
    """Занятия и окна аудиторий на один день."""

    def __init__(self, date, slots=(), windows=None):
        self.date = date
        self.slots = list(slots)
        # room_id -> [(start, end)]
        self.windows = windows if windows is not None else {}

    @classmethod
    def load(cls, date, exclude_lesson_ids=()):
        lessons = (
            Lesson.objects.filter(
                start_at__date=date, room__isnull=False, status=Lesson.Status.ASSIGNED
            )
            .exclude(pk__in=list(exclude_lesson_ids))
            .select_related("room__building")
        )
        class_map = request_class_map({l.request_id for l in lessons})
        slots = [slot_from_lesson(l, class_map.get(l.request_id, frozenset())) for l in lessons]
        windows = defaultdict(list)
        for w in RoomWindow.objects.filter(date=date):
            windows[w.room_id].append((w.start, w.end))
        return cls(date, slots, dict(windows))

    def add(self, slot):
        self.slots.append(slot)

    def fitting_window(self, room_id, start, end):
        for w_start, w_end in self.windows.get(room_id, ()):
            if w_start <= start and end <= w_end:
                return w_start, w_end
        return None

    def hard_violations(self, info, room, start, end):
        """Список нарушенных жёстких правил (пустой — можно ставить)."""
        errors = []
        if self.fitting_window(room.pk, start, end) is None:
            errors.append(f"Занятие не помещается в окно аудитории {room.label}.")
        for slot in self.slots:
            if slot.lesson_id == info.lesson_id:
                continue
            if slot.room_id == room.pk and _overlaps(start, end, slot.start, slot.end, GAP):
                errors.append(
                    f"Аудитория {room.label} занята {fmt_range(slot.start, slot.end)} "
                    "(между занятиями нужно не меньше 10 минут)."
                )
            if (
                info.teacher_id
                and slot.teacher_id == info.teacher_id
                and _overlaps(start, end, slot.start, slot.end)
            ):
                errors.append(f"Преподаватель занят {fmt_range(slot.start, slot.end)}.")
            if same_group(info, slot) and _overlaps(start, end, slot.start, slot.end, GAP):
                errors.append(
                    f"Группа занята {fmt_range(slot.start, slot.end)} "
                    "(на переход нужно не меньше 10 минут)."
                )
        return errors

    def group_slots(self, info):
        return [s for s in self.slots if s.lesson_id != info.lesson_id and same_group(info, s)]


def room_suits(info, room):
    """Мягкие правила, зависящие только от аудитории: вместимость, ПК, доска."""
    problems = []
    if info.participants > room.capacity:
        problems.append(
            f"В аудитории {room.label} {room.capacity} мест, а участников {info.participants}."
        )
    if info.master_class.needs_pc and room.pc_count < info.participants:
        problems.append(
            f"В аудитории {room.label} {room.pc_count} ПК, а участников {info.participants}."
        )
    if not room.has_board(info.master_class.board_required):
        problems.append(
            f"В аудитории {room.label} нет доски: "
            f"{info.master_class.get_board_required_display()}."
        )
    return problems


class RepeatIndex:
    """Какие мастер-классы уже стоят у классов в этом учебном году."""

    def __init__(self, entries=()):
        # (class_id, master_class_id) -> [(date, request_id)]
        self.entries = defaultdict(list)
        for class_id, mc_id, date, request_id in entries:
            self.entries[(class_id, mc_id)].append((date, request_id))

    @classmethod
    def load(cls, class_ids, master_class_ids, around_date, exclude_lesson_ids=()):
        if not class_ids or not master_class_ids:
            return cls()
        year_start, year_end = academic_year_bounds(around_date)
        lessons = (
            Lesson.objects.filter(
                status=Lesson.Status.ASSIGNED,
                master_class_id__in=master_class_ids,
                request__classes__id__in=class_ids,
                start_at__date__gte=year_start,
                start_at__date__lte=year_end,
            )
            .exclude(pk__in=list(exclude_lesson_ids))
            .values_list("request__classes__id", "master_class_id", "start_at", "request_id")
        )
        return cls(
            (cid, mc_id, start.date(), rid)
            for cid, mc_id, start, rid in lessons
            if cid in class_ids
        )

    def add(self, info, date):
        for cid in info.class_ids:
            self.entries[(cid, info.master_class.pk)].append((date, info.request_id))

    def repeat_date(self, info, date):
        """Дата занятия, из-за которого это — повтор, или None."""
        if info.allow_repeat:
            return None
        year = academic_year_bounds(date)
        for cid in info.class_ids:
            for other_date, request_id in self.entries.get((cid, info.master_class.pk), ()):
                if request_id == info.request_id or other_date == date:
                    continue
                if academic_year_bounds(other_date) == year:
                    return other_date
        return None


def fmt_range(start, end):
    return f"{start:%H:%M}–{end:%H:%M}"


def slot_from_lesson(lesson, class_ids):
    return Slot(
        lesson_id=lesson.pk,
        request_id=lesson.request_id,
        master_class_id=lesson.master_class_id,
        room_id=lesson.room_id,
        building_id=lesson.room.building_id,
        site=lesson.room.building.address,
        teacher_id=lesson.teacher_id,
        start=lesson.start_at,
        end=lesson.end_at,
        class_ids=class_ids,
    )


def request_class_map(request_ids):
    from .models import RequestClass

    result = defaultdict(set)
    for rid, cid in RequestClass.objects.filter(request_id__in=request_ids).values_list(
        "request_id", "school_class_id"
    ):
        result[rid].add(cid)
    return {rid: frozenset(cids) for rid, cids in result.items()}


@dataclass
class CheckResult:
    errors: list
    warnings: list

    @property
    def ok(self):
        return not self.errors


def check_placement(lesson, room, start, teacher_id=..., day_state=None):
    """Проверка ручной правки: жёсткие правила — ошибки, мягкие — предупреждения."""
    if not isinstance(room, Room):
        room = Room.objects.select_related("building").get(pk=room)
    info = LessonInfo.from_lesson(lesson)
    if teacher_id is not ...:
        info.teacher_id = teacher_id
    end = start + info.duration
    state = day_state or DayState.load(start.date(), exclude_lesson_ids=[lesson.pk])
    errors = state.hard_violations(info, room, start, end)
    warnings = room_suits(info, room)

    request = lesson.request
    days = list(request.days.all())
    if days and not any(d.start <= start and end <= d.end for d in days):
        warnings.append("Время не входит в доступные дни заявки.")
    if request.site and room.site != request.site:
        warnings.append(f"Площадка заявки — {request.site}, а аудитория на {room.site}.")
    siblings = (
        Lesson.objects.filter(request=request, status=Lesson.Status.ASSIGNED, room__isnull=False)
        .exclude(pk=lesson.pk)
        .select_related("room__building")
    )
    if any(s.start_at.date() != start.date() for s in siblings):
        warnings.append("Другие занятия заявки стоят в другой день.")
    if any(s.room.site != room.site for s in siblings):
        warnings.append("Другие занятия заявки стоят на другой площадке.")

    repeats = RepeatIndex.load(
        info.class_ids, [info.master_class.pk], start.date(), exclude_lesson_ids=[lesson.pk]
    )
    repeat_date = repeats.repeat_date(info, start.date())
    if repeat_date:
        warnings.append(
            f"Повтор: этот мастер-класс уже стоит у класса {repeat_date:%d.%m.%Y}."
        )
    return CheckResult(errors, warnings)


def lessons_outside_windows(room_id, date):
    """Назначенные занятия аудитории, которые больше не помещаются в её окна."""
    windows = [(w.start, w.end) for w in RoomWindow.objects.filter(room_id=room_id, date=date)]
    lessons = Lesson.objects.filter(
        room_id=room_id, start_at__date=date, status=Lesson.Status.ASSIGNED
    )
    return [
        l for l in lessons if not any(ws <= l.start_at and l.end_at <= we for ws, we in windows)
    ]
