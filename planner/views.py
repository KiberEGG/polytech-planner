from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import RequestDayFormSet, RequestForm, create_request_from_form, days_from_formset
from .models import Request

SESSION_KEY = "submitted_requests"


def request_form(request):
    if request.method == "POST":
        form = RequestForm(request.POST)
        days = RequestDayFormSet(request.POST, prefix="days")
        form.is_valid()
        if request.POST.get("kind") == RequestForm.KIND_MASTER_CLASSES:
            if not days.is_valid():
                form.add_error(None, "Проверьте доступные дни.")
            elif not days_from_formset(days):
                form.add_error(None, "Укажите хотя бы один доступный день.")
        if not form.errors:
            obj = create_request_from_form(form, days)
            request.session[SESSION_KEY] = request.session.get(SESSION_KEY, []) + [obj.pk]
            return redirect("planner:request_done", pk=obj.pk)
    else:
        form = RequestForm()
        days = RequestDayFormSet(prefix="days")
    events = {
        str(e.pk): {
            "date": e.date.strftime("%d.%m.%Y"),
            "time": f"{e.time_from:%H:%M}–{e.time_to:%H:%M}",
            "master_classes": [mc.pk for mc in e.master_classes.all()],
        }
        for e in form.fields["event"].queryset
    }
    school_classes = {
        str(s.pk): [c.name for c in s.classes.all()]
        for s in form.fields["school"].queryset.prefetch_related("classes")
    }
    return render(
        request,
        "planner/request_form.html",
        {"form": form, "days": days, "events": events, "school_classes": school_classes},
    )


def request_done(request, pk):
    # Содержимое заявки видит только тот, кто её отправил (по сессии).
    if pk not in request.session.get(SESSION_KEY, []):
        raise Http404
    obj = get_object_or_404(
        Request.objects.select_related("event").prefetch_related("days", "lessons__master_class"),
        pk=pk,
    )
    return render(request, "planner/request_done.html", {"req": obj})
