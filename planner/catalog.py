"""Справочники в рабочем месте администратора (раздел 2 концепции).

Каждый справочник описан одной записью в CATALOG: модель, форма, колонки
списка и, если нужно, вложенная таблица (окна аудитории, классы школы).
"""

from dataclasses import dataclass, field

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import (
    Building,
    Event,
    MasterClass,
    Room,
    RoomWindow,
    School,
    SchoolClass,
    Teacher,
)
from .permissions import staff_required
from .staff_forms import DateInput, TimeInput


class BuildingForm(forms.ModelForm):
    class Meta:
        model = Building
        fields = ["code", "address"]


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["building", "number", "capacity", "pc_count", "board_chalk", "board_marker", "board_interactive"]
        help_texts = {"pc_count": "0 — без ПК."}


class TeacherForm(forms.ModelForm):
    class Meta:
        model = Teacher
        fields = ["full_name", "contact"]


class MasterClassForm(forms.ModelForm):
    class Meta:
        model = MasterClass
        fields = ["title", "duration_min", "teacher", "needs_pc", "board_required"]
        help_texts = {"teacher": "Можно не указывать — назначить позже прямо в занятии."}


class EventForm(forms.ModelForm):
    master_classes = forms.ModelMultipleChoiceField(
        label="Мастер-классы",
        queryset=MasterClass.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Event
        fields = ["title", "date", "time_from", "time_to"]
        widgets = {"date": DateInput(), "time_from": TimeInput(), "time_to": TimeInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["master_classes"].initial = list(self.instance.master_classes.all())

    def save(self, commit=True):
        obj = super().save(commit)
        if commit:
            obj.master_classes.set(self.cleaned_data["master_classes"])
        return obj


class SchoolForm(forms.ModelForm):
    class Meta:
        model = School
        fields = ["name", "contact_person", "phone"]


WindowFormSet = forms.inlineformset_factory(
    Room,
    RoomWindow,
    fields=["date", "time_from", "time_to"],
    widgets={"date": DateInput(), "time_from": TimeInput(), "time_to": TimeInput()},
    extra=2,
    can_delete=True,
)

SchoolClassFormSet = forms.inlineformset_factory(
    School, SchoolClass, fields=["name"], extra=2, can_delete=True
)


def _boards(room):
    names = [
        label
        for flag, label in [
            (room.board_chalk, "меловая"),
            (room.board_marker, "маркерная"),
            (room.board_interactive, "интерактивная"),
        ]
        if flag
    ]
    return ", ".join(names) or "—"


@dataclass
class Entry:
    model: type
    form: type
    title: str
    columns: list  # [(заголовок, функция от объекта)]
    search: list = field(default_factory=list)
    inline: type | None = None
    inline_title: str = ""
    select_related: list = field(default_factory=list)
    prefetch_related: list = field(default_factory=list)


CATALOG = {
    "building": Entry(
        Building, BuildingForm, "Корпуса",
        [("Код", lambda o: o.code), ("Адрес", lambda o: o.address), ("Аудиторий", lambda o: o.rooms.count())],
        search=["code", "address"],
    ),
    "room": Entry(
        Room, RoomForm, "Аудитории",
        [
            ("Аудитория", lambda o: o.label),
            ("Площадка", lambda o: o.site),
            ("Мест", lambda o: o.capacity),
            ("ПК", lambda o: o.pc_count or "—"),
            ("Доски", _boards),
        ],
        search=["number", "building__code"],
        inline=WindowFormSet, inline_title="Окна аудитории",
        select_related=["building"],
    ),
    "teacher": Entry(
        Teacher, TeacherForm, "Преподаватели",
        [("ФИО", lambda o: o.full_name), ("Контакты", lambda o: o.contact or "—")],
        search=["full_name"],
    ),
    "master_class": Entry(
        MasterClass, MasterClassForm, "Мастер-классы",
        [
            ("Название", lambda o: o.title),
            ("Мин", lambda o: o.duration_min),
            ("Преподаватель", lambda o: o.teacher or "не назначен"),
            ("ПК", lambda o: "нужны" if o.needs_pc else "—"),
            ("Доска", lambda o: o.get_board_required_display()),
        ],
        search=["title"],
        select_related=["teacher"],
    ),
    "event": Entry(
        Event, EventForm, "Мероприятия",
        [
            ("Название", lambda o: o.title),
            ("Дата", lambda o: o.date.strftime("%d.%m.%Y")),
            ("Время", lambda o: f"{o.time_from:%H:%M}–{o.time_to:%H:%M}"),
            ("Мастер-классы", lambda o: ", ".join(m.title for m in o.master_classes.all()) or "—"),
        ],
        search=["title"],
        prefetch_related=["master_classes"],
    ),
    "school": Entry(
        School, SchoolForm, "Школы",
        [
            ("Название", lambda o: o.name),
            ("Классы", lambda o: ", ".join(c.name for c in o.classes.all()) or "—"),
            ("Контактное лицо", lambda o: o.contact_person or "—"),
            ("Телефон", lambda o: o.phone or "—"),
        ],
        search=["name"],
        inline=SchoolClassFormSet, inline_title="Классы",
        prefetch_related=["classes"],
    ),
}


def _entry(kind):
    if kind not in CATALOG:
        raise Http404
    return CATALOG[kind]


@staff_required
def catalog_index(request):
    sections = [(kind, e.title, e.model.objects.count()) for kind, e in CATALOG.items()]
    return render(request, "planner/staff/catalog_index.html", {"sections": sections})


@staff_required
def catalog_list(request, kind):
    entry = _entry(kind)
    qs = entry.model.objects.select_related(*entry.select_related).prefetch_related(*entry.prefetch_related)
    q = request.GET.get("q", "").strip()
    if q and entry.search:
        cond = Q()
        for f in entry.search:
            cond |= Q(**{f"{f}__icontains": q})
        qs = qs.filter(cond)
    rows = [(obj, [fn(obj) for _, fn in entry.columns]) for obj in qs]
    return render(
        request,
        "planner/staff/catalog_list.html",
        {"kind": kind, "entry": entry, "rows": rows, "headers": [h for h, _ in entry.columns], "q": q},
    )


@staff_required
def catalog_edit(request, kind, pk=None):
    entry = _entry(kind)
    obj = get_object_or_404(entry.model, pk=pk) if pk else None
    form = entry.form(request.POST or None, instance=obj)
    inline = None
    if entry.inline and obj is not None:
        inline = entry.inline(request.POST or None, instance=obj, prefix="inline")
    if request.method == "POST":
        if form.is_valid() and (inline is None or inline.is_valid()):
            try:
                with transaction.atomic():
                    obj = form.save()
                    if inline is not None:
                        inline.save()
            except ProtectedError:
                messages.error(request, "Нельзя удалить строку: на неё ссылаются заявки.")
                return redirect("planner:catalog_edit", kind=kind, pk=pk)
            messages.success(request, f"Сохранено: {obj}.")
            if entry.inline and pk is None:
                # Окна и классы добавляются после создания записи.
                return redirect("planner:catalog_edit", kind=kind, pk=obj.pk)
            return redirect("planner:catalog_list", kind=kind)
    return render(
        request,
        "planner/staff/catalog_edit.html",
        {"kind": kind, "entry": entry, "obj": obj, "form": form, "inline": inline},
    )


@staff_required
def catalog_delete(request, kind, pk):
    entry = _entry(kind)
    obj = get_object_or_404(entry.model, pk=pk)
    if request.method == "POST":
        try:
            obj.delete()
            messages.success(request, f"Удалено: {obj}.")
        except ProtectedError:
            messages.error(request, f"Нельзя удалить «{obj}»: на запись ссылаются заявки или занятия.")
            return redirect("planner:catalog_edit", kind=kind, pk=pk)
    return redirect("planner:catalog_list", kind=kind)
