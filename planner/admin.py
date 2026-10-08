from django.contrib import admin, messages

from . import models
from .scheduler import run_distribution
from .services import accept_request, reject_request, sync_request_lessons

admin.site.site_header = "Планирование мастер-классов"
admin.site.site_title = "Мастер-классы"
admin.site.index_title = "Администрирование"


@admin.register(models.Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ["code", "address"]


class RoomWindowInline(admin.TabularInline):
    model = models.RoomWindow
    extra = 1


@admin.register(models.Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = [
        "label",
        "building",
        "capacity",
        "pc_count",
        "board_chalk",
        "board_marker",
        "board_interactive",
    ]
    list_filter = ["building"]
    search_fields = ["number"]
    inlines = [RoomWindowInline]

    @admin.display(description="аудитория", ordering="number")
    def label(self, obj):
        return obj.label


@admin.register(models.RoomWindow)
class RoomWindowAdmin(admin.ModelAdmin):
    list_display = ["room", "date", "time_from", "time_to"]
    list_filter = ["date", "room__building"]
    date_hierarchy = "date"


@admin.register(models.Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ["full_name", "contact"]
    search_fields = ["full_name"]


@admin.register(models.MasterClass)
class MasterClassAdmin(admin.ModelAdmin):
    list_display = ["title", "duration_min", "teacher", "needs_pc", "board_required"]
    list_filter = ["needs_pc", "board_required"]
    search_fields = ["title"]


class EventMasterClassInline(admin.TabularInline):
    model = models.EventMasterClass
    extra = 1


@admin.register(models.Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "date", "time_from", "time_to"]
    date_hierarchy = "date"
    inlines = [EventMasterClassInline]


class SchoolClassInline(admin.TabularInline):
    model = models.SchoolClass
    extra = 1


@admin.register(models.School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_person", "phone"]
    search_fields = ["name"]
    inlines = [SchoolClassInline]


@admin.register(models.SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ["name", "school"]
    list_filter = ["school"]
    search_fields = ["name", "school__name"]


class RequestClassInline(admin.TabularInline):
    model = models.RequestClass
    extra = 1
    autocomplete_fields = ["school_class"]


class RequestDayInline(admin.TabularInline):
    model = models.RequestDay
    extra = 1


class LessonInline(admin.TabularInline):
    model = models.Lesson
    extra = 0
    fields = [
        "master_class",
        "teacher",
        "room",
        "start_at",
        "end_at",
        "status",
        "conflict_reason",
        "is_manual",
        "allow_repeat",
    ]
    readonly_fields = ["room", "start_at", "end_at", "status", "conflict_reason", "is_manual"]


@admin.register(models.Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "school_display",
        "classes_display",
        "event",
        "participants",
        "site",
        "status",
        "source",
        "created_at",
    ]
    list_filter = ["status", "source", "event"]
    search_fields = ["school__name", "school_name", "contact_name"]
    inlines = [RequestClassInline, RequestDayInline, LessonInline]
    actions = ["accept", "reject", "distribute"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.source = models.Request.Source.ADMIN
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sync_request_lessons(form.instance)

    @admin.action(description="Принять (школа и классы попадут в справочник)")
    def accept(self, request, queryset):
        for obj in queryset.exclude(status=models.Request.Status.ACCEPTED):
            if obj.school_id is None and not obj.school_name.strip():
                self.message_user(request, f"{obj}: не указана школа.", messages.ERROR)
                continue
            accept_request(obj)
        self.message_user(request, "Заявки приняты.")

    @admin.action(description="Отклонить")
    def reject(self, request, queryset):
        for obj in queryset:
            reject_request(obj)
        self.message_user(request, "Заявки отклонены.")

    @admin.action(description="Распределить выбранные принятые заявки")
    def distribute(self, request, queryset):
        report = run_distribution(queryset.filter(status=models.Request.Status.ACCEPTED))
        self.message_user(
            request,
            f"Назначено: {report.assigned}, конфликтов: {report.conflicts}, "
            f"повторов: {report.repeats}.",
        )

    @admin.display(description="школа")
    def school_display(self, obj):
        return obj.school_display

    @admin.display(description="классы")
    def classes_display(self, obj):
        return obj.classes_display


@admin.register(models.Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = [
        "master_class",
        "request",
        "room",
        "teacher",
        "start_at",
        "end_at",
        "status",
        "is_manual",
    ]
    list_filter = ["status", "is_manual"]
