from django.urls import include, path
urlpatterns = [path("api/agent/v1/", include("agent_service.urls"))]
