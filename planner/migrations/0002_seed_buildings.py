from django.db import migrations

SEMENOVSKAYA = "ул. Б. Семёновская, 38"

BUILDINGS = [
    ("А", SEMENOVSKAYA),
    ("Б", SEMENOVSKAYA),
    ("В", SEMENOVSKAYA),
    ("Н", SEMENOVSKAYA),
    ("Нд", SEMENOVSKAYA),
    ("АВ", "ул. Автозаводская, 16"),
    ("ПК", "ул. Павла Корчагина, 22"),
    ("ПР", "ул. Прянишникова, 2А"),
    ("М", "ул. Михалковская, 7"),
]


def seed(apps, schema_editor):
    Building = apps.get_model("planner", "Building")
    for code, address in BUILDINGS:
        Building.objects.get_or_create(code=code, defaults={"address": address})


def unseed(apps, schema_editor):
    Building = apps.get_model("planner", "Building")
    Building.objects.filter(code__in=[c for c, _ in BUILDINGS], rooms__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("planner", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
