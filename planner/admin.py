from django.contrib import admin

from . import models

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
