import datetime

from django import forms

from .models import Building, Event, MasterClass, Request, School


class MasterClassChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.title} — {obj.duration_min} мин"


def site_choices():
    addresses = sorted(set(Building.objects.values_list("address", flat=True)))
    return [("", "любая")] + [(a, a) for a in addresses]


class RequestForm(forms.Form):
    KIND_EVENT = "event"
    KIND_MASTER_CLASSES = "master_classes"

    kind = forms.ChoiceField(
        label="На что заявка",
        choices=[(KIND_EVENT, "мероприятие"), (KIND_MASTER_CLASSES, "отдельные мастер-классы")],
        widget=forms.RadioSelect,
        initial=KIND_EVENT,
    )
    event = forms.ModelChoiceField(
        label="Мероприятие",
        queryset=Event.objects.none(),
        required=False,
        empty_label="— выберите мероприятие —",
    )
    event_master_classes = MasterClassChoiceField(
        label="Мастер-классы мероприятия",
        queryset=MasterClass.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Лишние можно снять.",
    )
    master_classes = MasterClassChoiceField(
        label="Мастер-классы",
        queryset=MasterClass.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    school = forms.ModelChoiceField(
        label="Школа",
        queryset=School.objects.all(),
        required=False,
        empty_label="— нет в списке, введу вручную —",
    )
    school_name = forms.CharField(label="Название школы", max_length=255, required=False)
    classes_text = forms.CharField(
        label="Классы", max_length=255, help_text="Например: 9а, 9б"
    )
    participants = forms.IntegerField(
        label="Количество учеников", min_value=1, help_text="Может быть меньше класса."
    )
    site = forms.ChoiceField(label="Площадка", required=False)
    contact_name = forms.CharField(label="ФИО контактного лица", max_length=255)
    contact_position = forms.CharField(
        label="Должность",
        max_length=255,
        help_text="Например, классный руководитель или заместитель директора.",
    )
    phone = forms.CharField(label="Телефон", max_length=50)
    email = forms.EmailField(label="Email", required=False)
    comment = forms.CharField(label="Комментарий", widget=forms.Textarea(attrs={"rows": 3}), required=False)
    consent = forms.BooleanField(
        label="Согласен(на) на обработку персональных данных", required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = datetime.date.today()
        self.fields["event"].queryset = Event.objects.filter(date__gte=today).prefetch_related(
            "master_classes"
        )
        self.fields["site"].choices = site_choices()

    def clean(self):
        data = super().clean()
        if data.get("kind") == self.KIND_EVENT:
            if not data.get("event"):
                self.add_error("event", "Выберите мероприятие.")
            elif not data.get("event_master_classes"):
                self.add_error("event_master_classes", "Отметьте хотя бы один мастер-класс.")
            else:
                allowed = set(data["event"].master_classes.values_list("pk", flat=True))
                if any(mc.pk not in allowed for mc in data["event_master_classes"]):
                    self.add_error("event_master_classes", "Мастер-класс не входит в мероприятие.")
        elif not data.get("master_classes"):
            self.add_error("master_classes", "Выберите хотя бы один мастер-класс.")
        if not data.get("school") and not (data.get("school_name") or "").strip():
            self.add_error("school_name", "Выберите школу из списка или введите название.")
        return data

    @property
    def is_event(self):
        return self.cleaned_data.get("kind") == self.KIND_EVENT


class RequestDayForm(forms.Form):
    date = forms.DateField(label="Дата", widget=forms.DateInput(attrs={"type": "date"}))
    time_from = forms.TimeField(label="с", widget=forms.TimeInput(attrs={"type": "time"}))
    time_to = forms.TimeField(label="по", widget=forms.TimeInput(attrs={"type": "time"}))

    def clean(self):
        data = super().clean()
        if data.get("time_from") and data.get("time_to") and data["time_from"] >= data["time_to"]:
            raise forms.ValidationError("Время «с» должно быть раньше времени «по».")
        if data.get("date") and data["date"] < datetime.date.today():
            self.add_error("date", "Дата уже прошла.")
        return data


RequestDayFormSet = forms.formset_factory(RequestDayForm, extra=3, max_num=10)


def days_from_formset(formset):
    return [f.cleaned_data for f in formset if f.cleaned_data and not f.errors]


def create_request_from_form(form, day_formset):
    """Сохраняет заявку с формы школы. Школа и классы — текстом до принятия."""
    from .services import sync_request_lessons

    data = form.cleaned_data
    school = data.get("school")
    request = Request.objects.create(
        school_name=school.name if school else data["school_name"].strip(),
        classes_text=data["classes_text"].strip(),
        event=data["event"] if form.is_event else None,
        participants=data["participants"],
        site=data.get("site") or "",
        contact_name=data["contact_name"],
        contact_position=data["contact_position"],
        phone=data["phone"],
        email=data.get("email") or "",
        comment=data.get("comment") or "",
        source=Request.Source.FORM,
        status=Request.Status.NEW,
    )
    if form.is_event:
        sync_request_lessons(request, data["event_master_classes"])
    else:
        for day in days_from_formset(day_formset):
            request.days.create(
                date=day["date"], time_from=day["time_from"], time_to=day["time_to"]
            )
        sync_request_lessons(request, data["master_classes"])
    return request

