from django.urls import path
from .views import ConversationView, RunsView, RunView, FeedbackView

urlpatterns = [path("conversations", ConversationView.as_view()), path("runs", RunsView.as_view()),
               path("runs/<str:run_id>", RunView.as_view()), path("runs/<str:run_id>/feedback", FeedbackView.as_view())]
