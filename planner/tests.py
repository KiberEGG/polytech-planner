import datetime

from django.test import TestCase

from .models import (
    Building,
    Lesson,
    MasterClass,
    Request,
    RequestDay,
    Room,
    RoomWindow,
    School,
    SchoolClass,
    Teacher,
)
from .scheduler import REASON_CAPACITY, REASON_PC, REASON_TEACHER, run_distribution
from .services import accept_request, place_lesson, split_classes

D = datetime.date(2026, 10, 15)


def t(hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.time(h, m)


def dt(hhmm, date=D):
    return datetime.datetime.combine(date, t(hhmm))


class Fixtures:
    def setUp(self):
        self.av = Building.objects.get(code="АВ")
        self.v = Building.objects.get(code="В")
        self.school = School.objects.create(name="Школа 1")
        self.c9a = SchoolClass.objects.create(school=self.school, name="9а")
        self.c9b = SchoolClass.objects.create(school=self.school, name="9б")

    def room(self, building, number, capacity=30, pcs=0, chalk=True, marker=False, windows=(("09:00", "17:00"),), date=D):
        room = Room.objects.create(
            building=building, number=number, capacity=capacity, pc_count=pcs,
            board_chalk=chalk, board_marker=marker,
        )
        for a, b in windows:
            RoomWindow.objects.create(room=room, date=date, time_from=t(a), time_to=t(b))
        return room

    def mc(self, title, minutes=60, teacher=None, needs_pc=False, board=MasterClass.Board.NONE):
        return MasterClass.objects.create(
            title=title, duration_min=minutes, teacher=teacher, needs_pc=needs_pc, board_required=board
        )

    def request(self, mcs, classes=None, participants=20, days=((D, "09:00", "17:00"),), site="", allow_repeat=False):
        req = Request.objects.create(
            school=self.school, participants=participants, site=site,
            contact_name="Иванова", contact_position="классный руководитель", phone="1",
            status=Request.Status.ACCEPTED, allow_repeat=allow_repeat,
        )
        req.classes.set(classes or [self.c9a])
        for date, a, b in days:
            RequestDay.objects.create(request=req, date=date, time_from=t(a), time_to=t(b))
        for m in mcs:
            Lesson.objects.create(request=req, master_class=m)
        return req


class RoomLabelTests(Fixtures, TestCase):
    def test_labels_follow_university_style(self):
        self.assertEqual(self.room(self.v, "509").label, "В-509")
        self.assertEqual(self.room(self.av, "1109").label, "АВ 1109")


class SchedulerTests(Fixtures, TestCase):
    def test_lessons_of_group_go_back_to_back_with_gap(self):
        self.room(self.av, "1109")
        a, b = self.mc("Роботы"), self.mc("Химия")
        req = self.request([a, b])
        report = run_distribution()
        self.assertEqual(report.assigned, 2)
        lessons = list(req.lessons.order_by("start_at"))
        self.assertEqual(lessons[0].start_at, dt("09:00"))
        self.assertEqual(lessons[1].start_at, dt("10:10"))
        self.assertTrue(req.is_distributed)

    def test_pc_lesson_gets_pc_room_and_smallest_room_preferred(self):
        big = self.room(self.av, "1000", capacity=100)
        small = self.room(self.av, "1001", capacity=25)
        pc = self.room(self.av, "1002", capacity=25, pcs=25)
        prog, talk = self.mc("Программирование", needs_pc=True), self.mc("Лекция")
        req = self.request([talk, prog])
        run_distribution()
        self.assertEqual(req.lessons.get(master_class=prog).room, pc)
        self.assertIn(req.lessons.get(master_class=talk).room, {small, pc})
        self.assertNotEqual(req.lessons.get(master_class=talk).room, big)

    def test_capacity_and_pc_conflicts(self):
        self.room(self.av, "1109", capacity=10, pcs=5)
        a = self.mc("Лекция")
        req = self.request([a], participants=20)
        run_distribution()
        lesson = req.lessons.get()
        self.assertEqual(lesson.status, Lesson.Status.CONFLICT)
        self.assertEqual(lesson.conflict_reason, REASON_CAPACITY)

        Room.objects.update(capacity=30)
        b = self.mc("ИТ", needs_pc=True)
        req2 = self.request([b], classes=[self.c9b], participants=20)
        run_distribution()
        self.assertEqual(req2.lessons.get().conflict_reason, REASON_PC)

    def test_room_gap_between_different_groups(self):
        self.room(self.av, "1109")
        a = self.mc("Роботы")
        self.request([a], classes=[self.c9a])
        req2 = self.request([self.mc("Химия")], classes=[self.c9b])
        run_distribution()
        self.assertEqual(req2.lessons.get().start_at, dt("10:10"))

    def test_teacher_busy(self):
        teacher = Teacher.objects.create(full_name="Петров")
        self.room(self.av, "1", windows=(("09:00", "10:00"),))
        self.room(self.av, "2", windows=(("09:00", "10:00"),))
        self.request([self.mc("Роботы", teacher=teacher)], classes=[self.c9a])
        req2 = self.request([self.mc("Химия", teacher=teacher)], classes=[self.c9b])
        run_distribution()
        lesson = req2.lessons.get()
        self.assertEqual(lesson.status, Lesson.Status.CONFLICT)
        self.assertEqual(lesson.conflict_reason, REASON_TEACHER)

    def test_all_lessons_on_one_site_and_requested_site(self):
        self.room(self.av, "1109", windows=(("09:00", "10:00"),))
        v_room = self.room(self.v, "509")
        a, b = self.mc("Роботы"), self.mc("Химия")
        req = self.request([a, b])
        run_distribution()
        # На Автозаводской помещается только одно — заявка уходит туда, где встают обе.
        self.assertEqual({l.room for l in req.lessons.all()}, {v_room})

    def test_picks_second_day_when_first_is_full(self):
        d2 = D + datetime.timedelta(days=2)
        room = self.room(self.av, "1109", windows=(("09:00", "10:00"),))
        RoomWindow.objects.create(room=room, date=d2, time_from=t("09:00"), time_to=t("13:00"))
        a, b = self.mc("Роботы"), self.mc("Химия")
        req = self.request([a, b], days=((D, "09:00", "14:00"), (d2, "10:00", "14:00")))
        run_distribution()
        starts = sorted(l.start_at for l in req.lessons.all())
        self.assertEqual(starts, [dt("10:00", d2), dt("11:10", d2)])

    def test_repeat_in_same_academic_year(self):
        d_prev = datetime.date(2026, 9, 20)
        self.room(self.av, "1109")
        RoomWindow.objects.create(room=Room.objects.get(), date=d_prev, time_from=t("09:00"), time_to=t("17:00"))
        a = self.mc("Роботы")
        self.request([a], days=((d_prev, "09:00", "17:00"),))
        run_distribution()
        req2 = self.request([a, self.mc("Химия")], classes=[self.c9a, self.c9b])
        run_distribution()
        repeat = req2.lessons.get(master_class=a)
        self.assertEqual(repeat.status, Lesson.Status.REPEAT)
        self.assertIn("20.09.2026", repeat.conflict_reason)

        req3 = self.request([a], classes=[self.c9a], allow_repeat=True)
        run_distribution()
        self.assertEqual(req3.lessons.get().status, Lesson.Status.ASSIGNED)

    def test_rerun_keeps_assigned_and_manual(self):
        self.room(self.av, "1109")
        req = self.request([self.mc("Роботы")])
        run_distribution()
        before = req.lessons.get().start_at
        report = run_distribution()
        self.assertEqual(report.requests, 0)
        self.assertEqual(req.lessons.get().start_at, before)

    def test_new_requests_are_not_distributed(self):
        self.room(self.av, "1109")
        req = self.request([self.mc("Роботы")])
        req.status = Request.Status.NEW
        req.save()
        run_distribution()
        self.assertEqual(req.lessons.get().status, Lesson.Status.PENDING)


class ManualEditTests(Fixtures, TestCase):
    def test_hard_rule_blocks_and_soft_rule_warns(self):
        room = self.room(self.av, "1109", capacity=10)
        req = self.request([self.mc("Роботы")], participants=20)
        lesson = req.lessons.get()
        result = place_lesson(lesson, room, dt("08:00"))
        self.assertTrue(result.errors)  # вне окна
        result = place_lesson(lesson, room, dt("09:00"))
        self.assertFalse(result.errors)
        self.assertTrue(result.warnings)  # не помещаются участники
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.PENDING)
        place_lesson(lesson, room, dt("09:00"), force=True)
        lesson.refresh_from_db()
        self.assertEqual(lesson.status, Lesson.Status.ASSIGNED)
        self.assertTrue(lesson.is_manual)

    def test_window_shift_releases_lessons(self):
        room = self.room(self.av, "1109")
        req = self.request([self.mc("Роботы")])
        run_distribution()
        window = RoomWindow.objects.get()
        window.time_from = t("12:00")
        window.save()
        lesson = req.lessons.get()
        self.assertEqual(lesson.status, Lesson.Status.CONFLICT)
        self.assertIsNone(lesson.room)
        self.assertIsNotNone(room)


class AcceptRequestTests(Fixtures, TestCase):
    def test_split_classes(self):
        self.assertEqual(split_classes("9а, 9б"), ["9а", "9б"])
        self.assertEqual(split_classes("9а и 9б"), ["9а", "9б"])

    def test_accept_creates_school_and_classes(self):
        req = Request.objects.create(
            school_name="Лицей 2", classes_text="10а и 10б", participants=25,
            contact_name="Сидоров", contact_position="завуч", phone="2", source=Request.Source.FORM,
        )
        accept_request(req)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.ACCEPTED)
        self.assertEqual(req.school.name, "Лицей 2")
        self.assertEqual(sorted(c.name for c in req.classes.all()), ["10а", "10б"])


class PublicFormTests(Fixtures, TestCase):
    def base_post(self, **extra):
        data = {
            "school": "", "school_name": "Школа 57", "classes_text": "9а, 9б",
            "participants": "20", "site": "", "contact_name": "Иванова И. И.",
            "contact_position": "классный руководитель", "phone": "+7 900 000-00-00",
            "consent": "on",
            "days-TOTAL_FORMS": "3", "days-INITIAL_FORMS": "0",
            "days-MIN_NUM_FORMS": "0", "days-MAX_NUM_FORMS": "10",
        }
        data.update(extra)
        return data

    def test_master_class_request(self):
        mc = self.mc("Роботы")
        future = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        resp = self.client.post("/", self.base_post(
            kind="master_classes", master_classes=[mc.pk],
            **{"days-0-date": future, "days-0-time_from": "10:00", "days-0-time_to": "14:00"},
        ))
        req = Request.objects.get()
        self.assertRedirects(resp, f"/request/{req.pk}/")
        self.assertEqual(req.status, Request.Status.NEW)
        self.assertEqual(req.source, Request.Source.FORM)
        self.assertIsNone(req.school)
        self.assertEqual(req.days.count(), 1)
        self.assertEqual(req.lessons.get().master_class, mc)
        page = self.client.get(resp.url)
        self.assertContains(page, f"Заявка №{req.pk}")

    def test_event_request_uses_event_day_and_selected_classes(self):
        a, b = self.mc("Роботы"), self.mc("Химия")
        from .models import Event
        event = Event.objects.create(
            title="День открытых дверей", date=datetime.date.today() + datetime.timedelta(days=5),
            time_from=t("10:00"), time_to=t("15:00"),
        )
        event.master_classes.set([a, b])
        self.client.post("/", self.base_post(kind="event", event=event.pk, event_master_classes=[a.pk]))
        req = Request.objects.get()
        self.assertEqual(req.event, event)
        self.assertEqual([l.master_class for l in req.lessons.all()], [a])
        self.assertEqual(req.days.get().date, event.date)

    def test_consent_and_days_required(self):
        mc = self.mc("Роботы")
        data = self.base_post(kind="master_classes", master_classes=[mc.pk])
        del data["consent"]
        resp = self.client.post("/", data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Request.objects.exists())
        self.assertContains(resp, "Укажите хотя бы один доступный день")

    def test_other_people_cannot_see_request(self):
        req = self.request([self.mc("Роботы")])
        self.assertEqual(self.client.get(f"/request/{req.pk}/").status_code, 404)


class StaffClient(Fixtures):
    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import User

        self.user = User.objects.create_user("staff", password="x", is_staff=True)
        self.client.force_login(self.user)

    def post(self, url, body):
        import json

        return self.client.post(url, json.dumps(body), content_type="application/json").json()


class StaffApiTests(StaffClient, TestCase):
    def test_grid_requires_staff(self):
        self.client.logout()
        self.assertEqual(self.client.get("/staff/").status_code, 302)

    def test_grid_renders(self):
        self.room(self.av, "1109")
        self.request([self.mc("Роботы")])
        run_distribution()
        resp = self.client.get(f"/staff/?date={D.isoformat()}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["data"]["rooms"][0]["label"], "АВ 1109")
        self.assertEqual(len(resp.context["data"]["lessons"]), 1)

    def test_place_warn_then_force(self):
        room = self.room(self.av, "1109", capacity=10)
        lesson = self.request([self.mc("Роботы")], participants=20).lessons.get()
        url = f"/staff/api/lessons/{lesson.pk}/place"
        body = {"date": D.isoformat(), "room_id": room.pk, "start": "09:00"}
        res = self.post(url, body)
        self.assertFalse(res["ok"])
        self.assertTrue(res["warnings"])
        res = self.post(url, {**body, "force": True})
        self.assertTrue(res["ok"])
        self.assertTrue(res["lesson"]["is_manual"])
        res = self.post(url, {**body, "start": "07:00", "force": True})
        self.assertFalse(res["ok"])
        self.assertTrue(res["errors"])

    def test_teacher_change_checks_busy(self):
        teacher = Teacher.objects.create(full_name="Петров")
        self.room(self.av, "1")
        self.room(self.av, "2")
        self.request([self.mc("Роботы", teacher=teacher)], classes=[self.c9a])
        other = self.request([self.mc("Химия")], classes=[self.c9b])
        run_distribution()
        lesson = other.lessons.get()
        res = self.post(f"/staff/api/lessons/{lesson.pk}/teacher", {"teacher_id": teacher.pk})
        self.assertFalse(res["ok"])
        self.assertIn("Преподаватель занят", res["errors"][0])

    def test_window_shrink_releases_lesson(self):
        self.room(self.av, "1109")
        req = self.request([self.mc("Роботы")])
        run_distribution()
        window = RoomWindow.objects.get()
        res = self.post("/staff/api/windows", {"id": window.pk, "from": "13:00", "to": "17:00"})
        self.assertEqual(res["released"], 1)
        self.assertEqual(req.lessons.get().status, Lesson.Status.CONFLICT)


class ReportTests(StaffClient, TestCase):
    def test_reports_and_excel(self):
        import io

        from openpyxl import load_workbook

        teacher = Teacher.objects.create(full_name="Петров")
        self.room(self.av, "1109")
        self.request([self.mc("Роботы", teacher=teacher)])
        run_distribution()
        resp = self.client.get(f"/staff/report/day/?date={D.isoformat()}")
        self.assertContains(resp, "Роботы")
        resp = self.client.get(f"/staff/report/school/?school={self.school.pk}")
        self.assertContains(resp, "АВ 1109")
        resp = self.client.get(f"/staff/report/teacher/?teacher={teacher.pk}&format=xlsx")
        ws = load_workbook(io.BytesIO(resp.content)).active
        self.assertEqual(ws["E4"].value, "Роботы")
        self.assertEqual(self.client.get("/staff/report/nope/").status_code, 404)
