from django.urls import path

from . import staff_views, views

app_name = "planner"

urlpatterns = [
    # Форма заявки для школ.
    path("", views.request_form, name="request_form"),
    path("request/<int:pk>/", views.request_done, name="request_done"),
    # Рабочее место администратора.
    path("staff/", staff_views.schedule_grid, name="grid"),
    path("staff/api/lessons/<int:pk>/place", staff_views.api_place, name="api_place"),
    path("staff/api/lessons/<int:pk>/teacher", staff_views.api_teacher, name="api_teacher"),
    path("staff/api/lessons/<int:pk>/unplace", staff_views.api_unplace, name="api_unplace"),
    path("staff/api/lessons/<int:pk>/delete", staff_views.api_delete, name="api_delete"),
    path("staff/api/windows", staff_views.api_window, name="api_window"),
    path("staff/report/<str:kind>/", staff_views.report, name="report"),
    path("staff/api/distribute", staff_views.api_distribute, name="api_distribute"),
]
