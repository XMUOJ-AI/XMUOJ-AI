from django.urls import path
from .views import ClassStatsAPI, PathAPI, ProfileAPI, RefreshAPI, TeacherProfileAPI, WeaknessAPI

urlpatterns = [
    path("learning/profile", ProfileAPI.as_view()),
    path("learning/weakness", WeaknessAPI.as_view()),
    path("recommendation/path", PathAPI.as_view()),
    path("recommendation/refresh", RefreshAPI.as_view()),
    path("admin/learning/student/<int:student_id>/profile", TeacherProfileAPI.as_view()),
    path("admin/learning/class/knowledge-stats", ClassStatsAPI.as_view()),
]
