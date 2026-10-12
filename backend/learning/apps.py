from django.apps import AppConfig


class LearningConfig(AppConfig):
    name = "learning"

    def ready(self):
        from . import signals  # noqa: F401
