from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import RoomWindow
from .services import release_lessons_outside_windows


@receiver(pre_save, sender=RoomWindow)
def remember_old_window(sender, instance, **kwargs):
    instance._old = None
    if instance.pk:
        instance._old = RoomWindow.objects.filter(pk=instance.pk).values("room_id", "date").first()


@receiver(post_save, sender=RoomWindow)
def window_saved(sender, instance, **kwargs):
    release_lessons_outside_windows(instance.room_id, instance.date)
    old = getattr(instance, "_old", None)
    if old and (old["room_id"], old["date"]) != (instance.room_id, instance.date):
        release_lessons_outside_windows(old["room_id"], old["date"])


@receiver(post_delete, sender=RoomWindow)
def window_deleted(sender, instance, **kwargs):
    release_lessons_outside_windows(instance.room_id, instance.date)
