from django.urls import re_path

from .views import BatchAPI, BatchErrorsAPI, BatchProblemsAPI, CommitBatchAPI, UploadBatchAPI

BASE = r"^admin/problem-import/batches"
KEY = r"/(?P<batch_id>[A-Za-z0-9._-]{1,64})"
urlpatterns = [
    re_path(BASE + r"/?$", UploadBatchAPI.as_view()),
    re_path(BASE + KEY + r"/?$", BatchAPI.as_view()),
    re_path(BASE + KEY + r"/problems/?$", BatchProblemsAPI.as_view()),
    re_path(BASE + KEY + r"/errors/?$", BatchErrorsAPI.as_view()),
    re_path(BASE + KEY + r"/commit/?$", CommitBatchAPI.as_view()),
]
