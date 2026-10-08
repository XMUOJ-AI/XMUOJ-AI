from django.conf.urls import url

from knowledge.public import PublicGraph, PublicPointDetail, PublicPointList


urlpatterns = [
    url(r"^knowledge-points/?$", PublicPointList.as_view()),
    url(r"^knowledge-points/(?P<knowledge_code>[a-z][a-z0-9_]{0,63})/?$", PublicPointDetail.as_view()),
    url(r"^knowledge-graph/?$", PublicGraph.as_view()),
]
