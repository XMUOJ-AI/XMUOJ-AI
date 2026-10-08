from django.conf.urls import url

from knowledge.admin import (AdminDependencyRequest, AdminGraph, AdminMapping,
                             AdminPointDelete, AdminPointDetail, AdminPointList,
                             AdminReviewAction, AdminReviewDetail, AdminReviewList)


urlpatterns = [
    url(r"^knowledge-points/?$", AdminPointList.as_view()),
    url(r"^knowledge-points/(?P<knowledge_code>[a-z][a-z0-9_]{0,63})/delete/?$", AdminPointDelete.as_view()),
    url(r"^knowledge-points/(?P<knowledge_code>[a-z][a-z0-9_]{0,63})/?$", AdminPointDetail.as_view()),
    url(r"^knowledge-graph/?$", AdminGraph.as_view()),
    url(r"^knowledge-dependency-change-requests/?$", AdminDependencyRequest.as_view()),
    url(r"^problems/(?P<problem_id>[0-9]+)/knowledge-mappings/?$", AdminMapping.as_view()),
    url(r"^knowledge-reviews/?$", AdminReviewList.as_view()),
    url(r"^knowledge-reviews/(?P<object_type>dependency_change|problem_mapping)/(?P<object_key>[0-9a-fA-F-]{36})/?$", AdminReviewDetail.as_view()),
    url(r"^knowledge-reviews/(?P<object_type>dependency_change|problem_mapping)/(?P<object_key>[0-9a-fA-F-]{36})/(?P<action>approve|reject)/?$", AdminReviewAction.as_view()),
]
