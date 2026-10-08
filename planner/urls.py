from django.urls import path

from . import views

app_name = "planner"

urlpatterns = [
    path("", views.request_form, name="request_form"),
    path("request/<int:pk>/", views.request_done, name="request_done"),
]
