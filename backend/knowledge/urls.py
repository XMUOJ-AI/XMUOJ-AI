from django.urls import path

from . import views


urlpatterns = [
    path("knowledge-points", views.PublicKnowledgeList.as_view()),
    path("knowledge-points/<str:knowledge_code>", views.PublicKnowledgeDetail.as_view()),
    path("knowledge-points/<str:knowledge_code>/dependencies", views.PublicDependencySummaries.as_view()),
    path("knowledge-points/<str:knowledge_code>/related-problems", views.PublicProblemSummaries.as_view()),
    path("knowledge-graph", views.PublicKnowledgeGraph.as_view()),
    path("admin/knowledge-points", views.AdminKnowledgeList.as_view()),
    path("admin/knowledge-points/<str:knowledge_code>", views.AdminKnowledgeDetail.as_view()),
    path("admin/knowledge-points/<str:knowledge_code>/delete", views.AdminKnowledgeDelete.as_view()),
    path("admin/knowledge-points/<str:knowledge_code>/dependencies", views.AdminDependencySummaries.as_view()),
    path("admin/knowledge-points/<str:knowledge_code>/related-problems", views.AdminProblemSummaries.as_view()),
    path("admin/knowledge-graph", views.AdminKnowledgeGraph.as_view()),
    path("admin/knowledge-dependencies/<int:dependency_id>", views.AdminDependencyDetail.as_view()),
    path("admin/knowledge-dependency-change-requests", views.DependencyChangeCreate.as_view()),
    path("admin/problems/<int:problem_id>/knowledge-mappings", views.ProblemMappings.as_view()),
    path("admin/knowledge-reviews", views.ReviewList.as_view()),
    path("admin/knowledge-reviews/<str:object_type>/<str:object_key>", views.ReviewDetail.as_view()),
    path("admin/knowledge-reviews/<str:object_type>/<str:object_key>/approve", views.ReviewApprove.as_view()),
    path("admin/knowledge-reviews/<str:object_type>/<str:object_key>/reject", views.ReviewReject.as_view()),
]
