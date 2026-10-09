"""Заявки в рабочем месте администратора: список, карточка, создание."""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from .forms import RequestDayFormSet as PublicDayFormSet
from .forms import create_request_from_form, days_from_formset
from .models import Lesson, Request, School
from .permissions import staff_required
from .scheduler import run_distribution
from .services import accept_request, reject_request, unplace_lesson
from .views import form_context
from .staff_forms import AcceptForm, AddLessonForm, RequestDayFormSet, RequestEditForm, StaffRequestForm

STATUS_TABS = [
    ("new", "Новые"),
    ("accepted", "Принятые"),
    ("rejected", "Отклонённые"),
    ("all", "Все"),
]


@staff_required
def request_list(request):
    status = request.GET.get("status", "new")
    q = request.GET.get("q", "").strip()
    qs = (
        Request.objects.select_related("school", "event")
        .prefetch_related("classes", "days")
        .annotate(
            lessons_total=Count("lessons", distinct=True),
            lessons_assigned=Count(
                "lessons", filter=Q(lessons__status=Lesson.Status.ASSIGNED), distinct=True
            ),
            lessons_problem=Count(
                "lessons",
                filter=Q(lessons__status__in=[Lesson.Status.CONFLICT, Lesson.Status.REPEAT]),
                distinct=True,
            ),
        )
        .order_by("-created_at", "-id")
    )
    if status != "all":
        qs = qs.filter(status=status)
    if q:
        filters = Q(school__name__icontains=q) | Q(school_name__icontains=q) | Q(contact_name__icontains=q)
        if q.lstrip("№").isdigit():
            filters |= Q(pk=int(q.lstrip("№")))
        qs = qs.filter(filters)
    counts = dict(Request.objects.values_list("status").annotate(n=Count("id")))
    tabs = [
        (key, label, counts.get(key, 0) if key != "all" else sum(counts.values()))
        for key, label in STATUS_TABS
    ]
    return render(
        request,
        "planner/staff/request_list.html",
        {"requests": qs, "status": status, "q": q, "tabs": tabs},
    )


@staff_required
def request_detail(request, pk):
    obj = get_object_or_404(
        Request.objects.select_related("school", "event"), pk=pk
    )
    action = request.POST.get("action") if request.method == "POST" else None
    edit_form = RequestEditForm(instance=obj)
    days = RequestDayFormSet(instance=obj, prefix="days")
    accept_form = AcceptForm(request_obj=obj)
    add_form = AddLessonForm(request_obj=obj)

    if action == "save":
        edit_form = RequestEditForm(request.POST, instance=obj)
        days = RequestDayFormSet(request.POST, instance=obj, prefix="days")
        days_ok = obj.event_id is not None or days.is_valid()
        if edit_form.is_valid() and days_ok:
            edit_form.save()
            if obj.event_id is None:
                days.save()
            messages.success(request, "Заявка сохранена.")
            return redirect("planner:request_detail", pk=obj.pk)
    elif action == "accept":
        accept_form = AcceptForm(request.POST, request_obj=obj)
        if accept_form.is_valid():
            school = accept_form.cleaned_data["school"]
            if school is None and not obj.school_name.strip():
                messages.error(request, "В заявке не указана школа.")
            else:
                is_new_school = (
                    school is None
                    and obj.school_id is None
                    and not School.objects.filter(name__iexact=obj.school_name.strip()).exists()
                )
                accept_request(obj, school)
                note = " Школа добавлена в справочник." if is_new_school else ""
                messages.success(request, "Заявка принята." + note)
                return redirect("planner:request_detail", pk=obj.pk)
    elif action == "reject":
        reject_request(obj)
        messages.success(request, "Заявка отклонена.")
        return redirect("planner:request_detail", pk=obj.pk)
    elif action == "distribute":
        if obj.status != Request.Status.ACCEPTED:
            messages.error(request, "Распределяются только принятые заявки.")
        else:
            report = run_distribution(Request.objects.filter(pk=obj.pk))
            messages.success(
                request,
                f"Назначено: {report.assigned}, конфликтов: {report.conflicts}, повторов: {report.repeats}.",
            )
        return redirect("planner:request_detail", pk=obj.pk)
    elif action == "add_lesson":
        add_form = AddLessonForm(request.POST, request_obj=obj)
        if add_form.is_valid():
            Lesson.objects.create(request=obj, master_class=add_form.cleaned_data["master_class"])
            messages.success(request, "Мастер-класс добавлен.")
            return redirect("planner:request_detail", pk=obj.pk)
    elif action in ("delete_lesson", "unplace_lesson", "toggle_repeat"):
        lesson = get_object_or_404(Lesson, pk=request.POST.get("lesson"), request=obj)
        if action == "delete_lesson":
            lesson.delete()
            messages.success(request, "Занятие удалено.")
        elif action == "unplace_lesson":
            unplace_lesson(lesson)
            lesson.is_manual = False
            lesson.save()
            messages.success(request, "Занятие снято с расписания.")
        else:
            lesson.allow_repeat = not lesson.allow_repeat
            if lesson.allow_repeat and lesson.status == Lesson.Status.REPEAT:
                lesson.status = Lesson.Status.PENDING
                lesson.conflict_reason = ""
            lesson.save()
        return redirect("planner:request_detail", pk=obj.pk)

    lessons = obj.lessons.select_related("master_class", "teacher", "room__building").order_by(
        "start_at", "id"
    )
    return render(
        request,
        "planner/staff/request_detail.html",
        {
            "req": obj,
            "lessons": lessons,
            "edit_form": edit_form,
            "days": days,
            "accept_form": accept_form,
            "add_form": add_form,
        },
    )


@staff_required
def request_create(request):
    if request.method == "POST":
        form = StaffRequestForm(request.POST)
        days = PublicDayFormSet(request.POST, prefix="days")
        form.is_valid()
        if request.POST.get("kind") == StaffRequestForm.KIND_MASTER_CLASSES:
            if not days.is_valid():
                form.add_error(None, "Проверьте доступные дни.")
            elif not days_from_formset(days):
                form.add_error(None, "Укажите хотя бы один доступный день.")
        if not form.errors:
            obj = create_request_from_form(form, days, source=Request.Source.ADMIN)
            if form.cleaned_data.get("accept_now"):
                accept_request(obj, form.cleaned_data.get("school"))
            messages.success(request, f"Заявка №{obj.pk} создана.")
            return redirect("planner:request_detail", pk=obj.pk)
    else:
        form = StaffRequestForm()
        days = PublicDayFormSet(prefix="days")
    return render(
        request,
        "planner/staff/request_create.html",
        {"form": form, "days": days, **form_context(form)},
    )


@staff_required
def distribute_all(request):
    if request.method == "POST":
        report = run_distribution()
        messages.success(
            request,
            f"Распределение: назначено {report.assigned}, конфликтов {report.conflicts}, "
            f"повторов {report.repeats}.",
        )
    return redirect("planner:request_list")
