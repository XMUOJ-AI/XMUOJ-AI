from copy import deepcopy

from utils.api.tests import APITestCase

from .models import ACMContestRank, Contest
from .tests import DEFAULT_CONTEST_DATA


class ACMHelperPermissionTest(APITestCase):
    def setUp(self):
        self.owner = self.create_admin("owner", "owner-password", login=False)
        self.other = self.create_admin("other", "other-password")
        data = dict(deepcopy(DEFAULT_CONTEST_DATA), password="")
        self.contest = Contest.objects.create(created_by=self.owner, **data)
        self.other_contest = Contest.objects.create(created_by=self.other, **data)
        self.student = self.create_user("student", "student-password", login=False)
        self.rank = ACMContestRank.objects.create(user=self.student, contest=self.contest,
                                                  accepted_number=1,
                                                  submission_info={"123": {"is_ac": True, "ac_time": 10}})
        self.url = "/api/admin/contest/acm_helper"

    def test_non_owner_cannot_read_helper(self):
        self.assertFailed(self.client.get(self.url, {"contest_id": self.contest.id}))

    def test_rank_must_belong_to_authorized_contest(self):
        response = self.client.put(self.url, {"contest_id": self.other_contest.id,
                                              "rank_id": self.rank.id, "problem_id": "123", "checked": True})
        self.assertFailed(response)
        self.rank.refresh_from_db()
        self.assertNotIn("checked", self.rank.submission_info["123"])

    def test_owner_can_read_and_update_own_rank(self):
        self.client.force_login(self.owner)
        self.assertSuccess(self.client.get(self.url, {"contest_id": self.contest.id}))
        self.assertSuccess(self.client.put(self.url, {"contest_id": self.contest.id,
                                                      "rank_id": self.rank.id, "problem_id": "123", "checked": True}))
        self.rank.refresh_from_db()
        self.assertTrue(self.rank.submission_info["123"]["checked"])
