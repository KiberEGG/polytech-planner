from django.contrib.auth.decorators import user_passes_test

# Рабочее место администратора открыто только сотрудникам (is_staff).
staff_required = user_passes_test(lambda u: u.is_active and u.is_staff, login_url="planner:login")
