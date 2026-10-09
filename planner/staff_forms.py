"""Формы рабочего места администратора."""

from django import forms

from .forms import RequestForm, site_choices
from .models import MasterClass, Request, RequestDay, School, SchoolClass


class ClassChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class RequestEditForm(forms.ModelForm):
    site = forms.ChoiceField(label="Площадка", required=False)
    classes = ClassChoiceField(
        label="Классы",
        queryset=SchoolClass.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Request
        fields = [
            "school_name",
            "classes_text",
            "participants",
            "site",
            "contact_name",
            "contact_position",
            "phone",
            "email",
            "allow_repeat",
            "comment",
        ]
        widgets = {"comment": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "allow_repeat": "Например, когда приезжает вторая половина класса.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].choices = site_choices()
        if self.instance.school_id:
            # После принятия школа и классы берутся из справочника.
            del self.fields["school_name"]
            del self.fields["classes_text"]
            self.fields["classes"].queryset = self.instance.school.classes.all()
            self.fields["classes"].initial = list(self.instance.classes.all())
        else:
            del self.fields["classes"]

    def save(self, commit=True):
        obj = super().save(commit)
        if commit and "classes" in self.cleaned_data:
            obj.classes.set(self.cleaned_data["classes"])
        return obj


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%Y-%m-%d")


class TimeInput(forms.TimeInput):
    input_type = "time"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%H:%M")


RequestDayFormSet = forms.inlineformset_factory(
    Request,
    RequestDay,
    fields=["date", "time_from", "time_to"],
    widgets={"date": DateInput(), "time_from": TimeInput(), "time_to": TimeInput()},
    extra=1,
    can_delete=True,
)


class AcceptForm(forms.Form):
    school = forms.ModelChoiceField(
        label="Школа в справочнике",
        queryset=School.objects.all(),
        required=False,
        empty_label="— добавить как новую —",
    )

    def __init__(self, *args, request_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        if request_obj is not None and not self.is_bound:
            self.fields["school"].initial = School.objects.filter(
                name__iexact=request_obj.school_name.strip()
            ).first()


class AddLessonForm(forms.Form):
    master_class = forms.ModelChoiceField(
        label="Добавить мастер-класс",
        queryset=MasterClass.objects.all(),
        empty_label="— добавить мастер-класс —",
    )

    def __init__(self, *args, request_obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        if request_obj is not None:
            taken = request_obj.lessons.values_list("master_class_id", flat=True)
            self.fields["master_class"].queryset = MasterClass.objects.exclude(pk__in=taken)


class StaffRequestForm(RequestForm):
    """Заявка, которую заводит администратор: без согласия, можно сразу принять."""

    accept_now = forms.BooleanField(label="Сразу принять", required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["consent"]
