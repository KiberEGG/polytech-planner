from django.contrib.auth import views as auth_views
from django.urls import path

from . import catalog, staff_requests, staff_views, views

app_name = "planner"

urlpatterns = [
    # Форма заявки для школ.
    path("", views.request_form, name="request_form"),
    path("request/<int:pk>/", views.request_done, name="request_done"),
    # Вход администратора.
    path(
        "staff/login/",
        auth_views.LoginView.as_view(
            template_name="planner/staff/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("staff/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Заявки.
    path("staff/requests/", staff_requests.request_list, name="request_list"),
    path("staff/requests/new/", staff_requests.request_create, name="request_create"),
    path("staff/requests/<int:pk>/", staff_requests.request_detail, name="request_detail"),
    path("staff/distribute/", staff_requests.distribute_all, name="distribute_all"),
    # Справочники.
    path("staff/catalog/", catalog.catalog_index, name="catalog_index"),
    path("staff/catalog/<str:kind>/", catalog.catalog_list, name="catalog_list"),
    path("staff/catalog/<str:kind>/new/", catalog.catalog_edit, name="catalog_create"),
    path("staff/catalog/<str:kind>/<int:pk>/", catalog.catalog_edit, name="catalog_edit"),
    path("staff/catalog/<str:kind>/<int:pk>/delete/", catalog.catalog_delete, name="catalog_delete"),
    # Расписание.
    path("staff/", staff_views.schedule_grid, name="grid"),
    path("staff/report/<str:kind>/", staff_views.report, name="report"),
    path("staff/api/lessons/<int:pk>/place", staff_views.api_place, name="api_place"),
    path("staff/api/lessons/<int:pk>/teacher", staff_views.api_teacher, name="api_teacher"),
    path("staff/api/lessons/<int:pk>/unplace", staff_views.api_unplace, name="api_unplace"),
    path("staff/api/lessons/<int:pk>/delete", staff_views.api_delete, name="api_delete"),
    path("staff/api/windows", staff_views.api_window, name="api_window"),
    path("staff/api/distribute", staff_views.api_distribute, name="api_distribute"),
]
