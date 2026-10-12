from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import F, JSONField, Q, Value
from django.db.models.fields.json import KeyTransform
from django.db.models.functions import Coalesce, JSONObject
from account.models import User
from learning.models import LearningSubmissionEvent
from learning.ratings import TERMINAL, capture_submission, dispatch_event, process_event, replay_user
from submission.models import Submission

# The actor retries up to 3 times with at most 60s backoff; wait past that before redelivering.
REDELIVER_AFTER = timedelta(minutes=5)


class Command(BaseCommand):
    help = "Redeliver durable learning events, or deterministically replay one student's ratings."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int)
        parser.add_argument("--sync", action="store_true")
        parser.add_argument("--limit", type=int, default=1000)
        parser.add_argument("--backfill", action="store_true")

    def handle(self, *args, **options):
        if options["backfill"]:
            # Compare the source in SQL before applying limit; old processed
            # rows cannot starve later missing or unsuccessfully captured verdicts.
            submissions = Submission.objects.filter(contest__isnull=True, problem__contest__isnull=True,
                                                    user_id__in=User.objects.values("pk")).annotate(
                learning_source=JSONObject(result=F("result"),
                                           score=Coalesce(KeyTransform("score", "statistic_info"), Value(0, output_field=JSONField())),
                                           rule_type=F("problem__rule_type"), total_score=F("problem__total_score"))).filter(
                Q(learningsubmissionevent__isnull=True, result__in=TERMINAL) |
                (Q(learningsubmissionevent__isnull=False) &
                 (Q(learningsubmissionevent__payload__source__isnull=True) |
                  ~Q(learningsubmissionevent__payload__source=F("learning_source")))))
            if options["user_id"]:
                submissions = submissions.filter(user_id=options["user_id"])
            submissions = submissions.select_related("problem").order_by("create_time", "pk")[:max(1, min(options["limit"], 10000))]
            for submission in submissions:
                capture_submission(submission)
        if options["user_id"]:
            count = replay_user(options["user_id"])
            self.stdout.write(f"Replayed {count} rating changes")
            return
        events = LearningSubmissionEvent.objects.exclude(status="processed")
        if not options["sync"]:
            # Redeliver only events idle for REDELIVER_AFTER, and stamp them on send, so a
            # 30-second supervisor loop cannot flood the queue while a worker is slow or down.
            events = events.filter(updated_time__lt=timezone.now() - REDELIVER_AFTER)
        ids = list(events.order_by("pk").values_list("pk", flat=True)[:max(1, min(options["limit"], 10000))])
        for pk in ids:
            if options["sync"]:
                process_event(pk)
            else:
                LearningSubmissionEvent.objects.filter(pk=pk).update(updated_time=timezone.now())
                dispatch_event(pk)
        self.stdout.write(f"Recovered {len(ids)} learning events")
