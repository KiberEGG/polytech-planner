"""Модели системы планирования мастер-классов.

Тринадцать таблиц из концепции (раздел 9). Центральная — Lesson (занятие):
она связывает заявку, мастер-класс, аудиторию и преподавателя.
"""

import datetime

from django.core.exceptions import ValidationError
from django.db import models

# Корпуса на Б. Семёновской записываются через дефис: «В-509»,
# на остальных площадках — через пробел: «АВ 1109».
HYPHEN_BUILDING_CODES = {"А", "Б", "В", "Н", "Нд"}


class Building(models.Model):
    code = models.CharField("код", max_length=10, unique=True)
    address = models.CharField("адрес", max_length=255)

    class Meta:
        db_table = "building"
        verbose_name = "корпус"
        verbose_name_plural = "корпуса"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.address}"


class Room(models.Model):
    building = models.ForeignKey(
        Building, models.PROTECT, related_name="rooms", verbose_name="корпус"
    )
    number = models.CharField("номер", max_length=20)
    capacity = models.PositiveIntegerField("вместимость")
    pc_count = models.PositiveIntegerField("количество ПК", default=0)
    board_chalk = models.BooleanField("меловая доска", default=False)
    board_marker = models.BooleanField("маркерная доска", default=False)
    board_interactive = models.BooleanField("интерактивная доска", default=False)

    class Meta:
        db_table = "room"
        verbose_name = "аудитория"
        verbose_name_plural = "аудитории"
        ordering = ["building__code", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["building", "number"], name="room_building_number_uniq"
            )
        ]

    def __str__(self):
        return self.label

    @property
    def label(self):
        sep = "-" if self.building.code in HYPHEN_BUILDING_CODES else " "
        return f"{self.building.code}{sep}{self.number}"

    @property
    def site(self):
        return self.building.address

    def has_board(self, board):
        """Есть ли в аудитории доска нужного типа (board_required мастер-класса)."""
        if board == MasterClass.Board.NONE:
            return True
        if board == MasterClass.Board.ANY:
            return self.board_chalk or self.board_marker or self.board_interactive
        return getattr(self, f"board_{board}")


class RoomWindow(models.Model):
    """Время, на которое аудиторию дают под мастер-классы."""

    room = models.ForeignKey(
        Room, models.CASCADE, related_name="windows", verbose_name="аудитория"
    )
    date = models.DateField("дата")
    time_from = models.TimeField("с")
    time_to = models.TimeField("по")

    class Meta:
        db_table = "room_window"
        verbose_name = "окно аудитории"
        verbose_name_plural = "окна аудиторий"
        ordering = ["date", "room", "time_from"]

    def __str__(self):
        return f"{self.room} {self.date:%d.%m.%Y} {self.time_from:%H:%M}–{self.time_to:%H:%M}"

    def clean(self):
        if self.time_from and self.time_to and self.time_from >= self.time_to:
            raise ValidationError("Время «с» должно быть раньше времени «по».")

    @property
    def start(self):
        return datetime.datetime.combine(self.date, self.time_from)

    @property
    def end(self):
        return datetime.datetime.combine(self.date, self.time_to)


class Teacher(models.Model):
    full_name = models.CharField("ФИО", max_length=255)
    contact = models.CharField("контакты", max_length=255, blank=True)

    class Meta:
        db_table = "teacher"
        verbose_name = "преподаватель"
        verbose_name_plural = "преподаватели"
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class MasterClass(models.Model):
    class Board(models.TextChoices):
        NONE = "none", "не нужна"
        ANY = "any", "любая"
        CHALK = "chalk", "меловая"
        MARKER = "marker", "маркерная"
        INTERACTIVE = "interactive", "интерактивная"

    title = models.CharField("название", max_length=255)
    duration_min = models.PositiveIntegerField("продолжительность, мин")
    teacher = models.ForeignKey(
        Teacher,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="master_classes",
        verbose_name="преподаватель",
    )
    needs_pc = models.BooleanField("нужны ПК", default=False)
    board_required = models.CharField(
        "доска", max_length=12, choices=Board.choices, default=Board.NONE
    )

    class Meta:
        db_table = "master_class"
        verbose_name = "мастер-класс"
        verbose_name_plural = "мастер-классы"
        ordering = ["title"]

    def __str__(self):
        return f"{self.title} ({self.duration_min} мин)"


class Event(models.Model):
    title = models.CharField("название", max_length=255)
    date = models.DateField("дата")
    time_from = models.TimeField("с")
    time_to = models.TimeField("по")
    master_classes = models.ManyToManyField(
        MasterClass,
        through="EventMasterClass",
        related_name="events",
        verbose_name="мастер-классы",
    )

    class Meta:
        db_table = "event"
        verbose_name = "мероприятие"
        verbose_name_plural = "мероприятия"
        ordering = ["date", "time_from"]

    def __str__(self):
        return f"{self.title} ({self.date:%d.%m.%Y})"

    def clean(self):
        if self.time_from and self.time_to and self.time_from >= self.time_to:
            raise ValidationError("Время «с» должно быть раньше времени «по».")


class EventMasterClass(models.Model):
    event = models.ForeignKey(Event, models.CASCADE, verbose_name="мероприятие")
    master_class = models.ForeignKey(
        MasterClass, models.CASCADE, verbose_name="мастер-класс"
    )

    class Meta:
        db_table = "event_master_class"
        verbose_name = "мастер-класс мероприятия"
        verbose_name_plural = "мастер-классы мероприятия"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "master_class"], name="event_master_class_uniq"
            )
        ]

    def __str__(self):
        return str(self.master_class)


class School(models.Model):
    name = models.CharField("название", max_length=255, unique=True)
    contact_person = models.CharField("контактное лицо", max_length=255, blank=True)
    phone = models.CharField("телефон", max_length=50, blank=True)

    class Meta:
        db_table = "school"
        verbose_name = "школа"
        verbose_name_plural = "школы"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SchoolClass(models.Model):
    school = models.ForeignKey(
        School, models.CASCADE, related_name="classes", verbose_name="школа"
    )
    name = models.CharField("название", max_length=20)

    class Meta:
        db_table = "school_class"
        verbose_name = "класс школы"
        verbose_name_plural = "классы школ"
        ordering = ["school__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"], name="school_class_uniq"
            )
        ]

    def __str__(self):
        return f"{self.school.name}, {self.name}"


class Request(models.Model):
    """Заявка — одно посещение школы: один день и одна площадка."""

    class Source(models.TextChoices):
        FORM = "form", "форма"
        ADMIN = "admin", "админ-панель"

    class Status(models.TextChoices):
        NEW = "new", "новая"
        ACCEPTED = "accepted", "принята"
        REJECTED = "rejected", "отклонена"

    school = models.ForeignKey(
        School,
        models.PROTECT,
        null=True,
        blank=True,
        related_name="requests",
        verbose_name="школа",
    )
    # Пока заявка с формы не принята, школа и классы хранятся текстом.
    school_name = models.CharField("школа (текстом)", max_length=255, blank=True)
    classes_text = models.CharField("классы (текстом)", max_length=255, blank=True)
    classes = models.ManyToManyField(
        SchoolClass,
        through="RequestClass",
        related_name="requests",
        blank=True,
        verbose_name="классы",
    )
    event = models.ForeignKey(
        Event,
        models.PROTECT,
        null=True,
        blank=True,
        related_name="requests",
        verbose_name="мероприятие",
    )
    participants = models.PositiveIntegerField("количество участников")
    # Адрес площадки; пусто, если подходит любая.
    site = models.CharField("площадка", max_length=255, blank=True)
    contact_name = models.CharField("контактное лицо", max_length=255)
    contact_position = models.CharField("должность", max_length=255)
    phone = models.CharField("телефон", max_length=50)
    email = models.EmailField("email", blank=True)
    source = models.CharField(
        "источник", max_length=10, choices=Source.choices, default=Source.ADMIN
    )
    status = models.CharField(
        "статус", max_length=10, choices=Status.choices, default=Status.NEW
    )
    allow_repeat = models.BooleanField("не проверять повтор", default=False)
    comment = models.TextField("комментарий", blank=True)
    created_at = models.DateTimeField("подана", auto_now_add=True)

    class Meta:
        db_table = "request"
        verbose_name = "заявка"
        verbose_name_plural = "заявки"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Заявка №{self.pk} — {self.school_display}"

    @property
    def school_display(self):
        return self.school.name if self.school_id else self.school_name

    @property
    def classes_display(self):
        names = [c.name for c in self.classes.all()]
        return ", ".join(names) if names else self.classes_text

    @property
    def is_distributed(self):
        lessons = list(self.lessons.all())
        return bool(lessons) and all(
            l.status == Lesson.Status.ASSIGNED for l in lessons
        )


class RequestClass(models.Model):
    request = models.ForeignKey(Request, models.CASCADE, verbose_name="заявка")
    school_class = models.ForeignKey(
        SchoolClass, models.PROTECT, verbose_name="класс"
    )

    class Meta:
        db_table = "request_class"
        verbose_name = "класс заявки"
        verbose_name_plural = "классы заявки"
        constraints = [
            models.UniqueConstraint(
                fields=["request", "school_class"], name="request_class_uniq"
            )
        ]

    def __str__(self):
        return str(self.school_class)


class RequestDay(models.Model):
    """Доступный день заявки; для мероприятия — его дата и время."""

    request = models.ForeignKey(
        Request, models.CASCADE, related_name="days", verbose_name="заявка"
    )
    date = models.DateField("дата")
    time_from = models.TimeField("с")
    time_to = models.TimeField("по")

    class Meta:
        db_table = "request_day"
        verbose_name = "доступный день"
        verbose_name_plural = "доступные дни"
        ordering = ["date", "time_from"]

    def __str__(self):
        return f"{self.date:%d.%m.%Y} {self.time_from:%H:%M}–{self.time_to:%H:%M}"

    def clean(self):
        if self.time_from and self.time_to and self.time_from >= self.time_to:
            raise ValidationError("Время «с» должно быть раньше времени «по».")

    @property
    def start(self):
        return datetime.datetime.combine(self.date, self.time_from)

    @property
    def end(self):
        return datetime.datetime.combine(self.date, self.time_to)


class Lesson(models.Model):
    """Занятие: один мастер-класс заявки, который нужно поставить в расписание."""

    class Status(models.TextChoices):
        PENDING = "pending", "ждёт"
        ASSIGNED = "assigned", "назначено"
        CONFLICT = "conflict", "конфликт"
        REPEAT = "repeat", "повтор"

    request = models.ForeignKey(
        Request, models.CASCADE, related_name="lessons", verbose_name="заявка"
    )
    master_class = models.ForeignKey(
        MasterClass, models.PROTECT, related_name="lessons", verbose_name="мастер-класс"
    )
    room = models.ForeignKey(
        Room,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="lessons",
        verbose_name="аудитория",
    )
    # Кто фактически ведёт; при создании копируется из мастер-класса.
    teacher = models.ForeignKey(
        Teacher,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="lessons",
        verbose_name="преподаватель",
    )
    start_at = models.DateTimeField("начало", null=True, blank=True)
    end_at = models.DateTimeField("конец", null=True, blank=True)
    status = models.CharField(
        "статус", max_length=10, choices=Status.choices, default=Status.PENDING
    )
    conflict_reason = models.TextField("причина", blank=True)
    is_manual = models.BooleanField("вручную", default=False)
    # Отмена проверки повтора для отдельного занятия (раздел 5, «Повтор»).
    allow_repeat = models.BooleanField("не проверять повтор", default=False)

    class Meta:
        db_table = "lesson"
        verbose_name = "занятие"
        verbose_name_plural = "занятия"
        ordering = ["start_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "master_class"], name="lesson_request_mc_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(start_at__isnull=True, end_at__isnull=True, room__isnull=True)
                | models.Q(start_at__lt=models.F("end_at"), room__isnull=False),
                name="lesson_placement_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.master_class.title} — {self.request.school_display}"

    def save(self, *args, **kwargs):
        if self._state.adding and self.teacher_id is None:
            self.teacher_id = self.master_class.teacher_id
        super().save(*args, **kwargs)

    @property
    def is_placed(self):
        return self.room_id is not None and self.start_at is not None

    def unplace(self):
        self.room = None
        self.start_at = None
        self.end_at = None


def academic_year_bounds(day):
    """Учебный год: с 1 сентября по 31 августа."""
    start_year = day.year if day.month >= 9 else day.year - 1
    return datetime.date(start_year, 9, 1), datetime.date(start_year + 1, 8, 31)
