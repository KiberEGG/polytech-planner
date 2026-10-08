"""Демо-данные: аудитории, окна, преподаватели, мастер-классы, школы и заявки."""

import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from planner.models import (
    Building,
    Event,
    MasterClass,
    Request,
    Room,
    RoomWindow,
    School,
    SchoolClass,
    Teacher,
)
from planner.services import accept_request, sync_request_lessons

ROOMS = [
    # код, номер, мест, ПК, мел, маркер, интерактив
    ("В", "509", 30, 0, True, False, False),
    ("В", "207", 24, 24, False, True, False),
    ("Б", "301", 60, 0, True, False, True),
    ("Н", "405", 20, 20, False, True, True),
    ("АВ", "1109", 28, 0, False, True, False),
    ("АВ", "1310", 30, 30, False, False, True),
    ("ПР", "1401", 40, 0, True, True, False),
    ("ПК", "114", 25, 12, True, False, False),
]

MASTER_CLASSES = [
    ("Программирование роботов", 90, "Смирнов А. В.", True, "any"),
    ("Химия без взрывов", 60, "Кузнецова Е. П.", False, "chalk"),
    ("3D-моделирование", 90, "Смирнов А. В.", True, "interactive"),
    ("Как устроен автомобиль", 60, "Попов Д. С.", False, "none"),
    ("Дизайн упаковки", 45, None, False, "marker"),
    ("Экскурсия по лабораториям", 40, "Попов Д. С.", False, "none"),
]


class Command(BaseCommand):
    help = "Заполняет базу демонстрационными данными."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="первый день (YYYY-MM-DD), по умолчанию — через неделю")

    @transaction.atomic
    def handle(self, *args, **opts):
        start = (
            datetime.date.fromisoformat(opts["date"])
            if opts.get("date")
            else datetime.date.today() + datetime.timedelta(days=7)
        )
        days = [start, start + datetime.timedelta(days=2)]

        rooms = []
        for code, number, cap, pcs, chalk, marker, inter in ROOMS:
            room, _ = Room.objects.get_or_create(
                building=Building.objects.get(code=code),
                number=number,
                defaults=dict(
                    capacity=cap, pc_count=pcs, board_chalk=chalk,
                    board_marker=marker, board_interactive=inter,
                ),
            )
            rooms.append(room)
            for d in days:
                RoomWindow.objects.get_or_create(
                    room=room, date=d,
                    defaults=dict(time_from=datetime.time(9, 0), time_to=datetime.time(16, 0)),
                )

        mcs = {}
        for title, minutes, teacher, pc, board in MASTER_CLASSES:
            t = Teacher.objects.get_or_create(full_name=teacher)[0] if teacher else None
            mcs[title], _ = MasterClass.objects.get_or_create(
                title=title,
                defaults=dict(duration_min=minutes, teacher=t, needs_pc=pc, board_required=board),
            )

        event, created = Event.objects.get_or_create(
            title="День инженера",
            date=days[0],
            defaults=dict(time_from=datetime.time(10, 0), time_to=datetime.time(15, 0)),
        )
        if created:
            event.master_classes.set(
                [mcs["Программирование роботов"], mcs["Химия без взрывов"], mcs["Экскурсия по лабораториям"]]
            )

        schools = []
        for name, classes in [("Школа № 1535", ["9а", "9б"]), ("Лицей № 1580", ["10а"]), ("Школа № 57", ["8в", "11а"])]:
            school, _ = School.objects.get_or_create(
                name=name, defaults=dict(contact_person="Иванова И. И.", phone="+7 495 000-00-00")
            )
            for c in classes:
                SchoolClass.objects.get_or_create(school=school, name=c)
            schools.append(school)

        if Request.objects.exists():
            self.stdout.write("Заявки уже есть — пропускаю.")
            return

        semenovskaya = Building.objects.get(code="В").address
        specs = [
            (schools[0], "9а", 25, event, [], None, semenovskaya),
            (schools[0], "9б", 22, None, ["3D-моделирование", "Дизайн упаковки"], days, ""),
            (schools[1], "10а", 28, None, ["Как устроен автомобиль", "Программирование роботов"], days[1:], ""),
            (schools[2], "8в и 11а", 35, None, ["Химия без взрывов", "Экскурсия по лабораториям"], days, ""),
        ]
        for school, classes, n, ev, titles, req_days, site in specs:
            req = Request.objects.create(
                school_name=school.name, classes_text=classes, participants=n, event=ev, site=site,
                contact_name="Петрова М. А.", contact_position="классный руководитель",
                phone="+7 900 000-00-00", source=Request.Source.FORM,
            )
            for d in req_days or []:
                req.days.create(date=d, time_from=datetime.time(9, 30), time_to=datetime.time(15, 0))
            sync_request_lessons(req, [mcs[t] for t in titles] or None)
            accept_request(req)
        # Одна заявка остаётся новой — чтобы было что принимать.
        req = Request.objects.create(
            school_name="Гимназия № 1514", classes_text="7б", participants=18,
            contact_name="Орлов П. Н.", contact_position="заместитель директора",
            phone="+7 900 111-11-11", source=Request.Source.FORM,
        )
        req.days.create(date=days[1], time_from=datetime.time(11, 0), time_to=datetime.time(14, 0))
        sync_request_lessons(req, [mcs["Химия без взрывов"]])
        self.stdout.write(self.style.SUCCESS(f"Готово. Дни с окнами: {', '.join(map(str, days))}."))
