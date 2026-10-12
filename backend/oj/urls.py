from django.urls import include, re_path as url

urlpatterns = [
    url(r"^api/agent/v1/", include("agent_service.urls")),
    url(r"^api/", include("learning.urls")),
    url(r"^api/", include("problem_import.urls")),
    url(r"^api/", include("knowledge.urls")),
    url(r"^api/plugin/", include("plugin.urls")),
    url(r"^api/", include("account.urls.oj")),
    url(r"^api/admin/", include("account.urls.admin")),
    url(r"^api/", include("announcement.urls.oj")),
    url(r"^api/admin/", include("announcement.urls.admin")),
    url(r"^api/", include("conf.urls.oj")),
    url(r"^api/admin/", include("conf.urls.admin")),
    url(r"^api/", include("problem.urls.oj")),
    url(r"^api/admin/", include("problem.urls.admin")),
    url(r"^api/", include("contest.urls.oj")),
    url(r"^api/admin/", include("contest.urls.admin")),
    url(r"^api/", include("submission.urls.oj")),
    url(r"^api/admin/", include("submission.urls.admin")),
    url(r"^api/admin/", include("utils.urls")),
]
