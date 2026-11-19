import unittest
from datetime import datetime, timezone

from src.eligibility import assess_eligibility, posting_age, recency_points
from src.puller import experience


class EligibilityTest(unittest.TestCase):
    def classify(self, title="Mechanical Engineer I", details="", years=None):
        return assess_eligibility(
            {"title": title, "description": "Mechanical Engineering bachelor's degree. CAD and prototypes.\n" + details},
            {"graduation": "2027-05"}, years, "Austin metro",
        )

    def test_cohort_and_start(self):
        self.assertEqual(self.classify(years=0)["category"], "Review")
        self.assertEqual(self.classify("2027 New Grad Mechanical Engineer", "Start June 2027.")["category"], "Apply")
        self.assertEqual(self.classify("2026 Graduate Mechanical Engineer", "Start April 2027.")["category"], "Review")

    def test_equivalence_and_professional_experience(self):
        details = "June 2027 start.\nRequires 2 years of experience; academic projects count."
        self.assertEqual(experience(details), 2)
        self.assertEqual(self.classify(details=details, years=2)["category"], "Apply")
        self.assertEqual(self.classify(details="June 2027 start.", years=2)["category"], "Stretch")
        self.assertEqual(self.classify(details="June 2027 start.", years=3)["category"], "Review")

    def test_nonfulltime_and_manufacturing(self):
        self.assertEqual(self.classify("Mechanical Engineer Intern", "June 2027", 0)["category"], "Review")
        self.assertEqual(self.classify("Manufacturing Engineer", "June 2027", 0)["category"], "Review")

    def test_recency_uses_employer_date(self):
        now = datetime(2026, 11, 16, tzinfo=timezone.utc)
        self.assertIsNone(posting_age("", now))
        self.assertIsNone(posting_age("2026-11-17", now))
        self.assertEqual(recency_points(posting_age("2026-11-15", now)), 10)
        self.assertEqual(recency_points(posting_age("2026-09-01", now)), 0)

    def test_queue_omits_factory_and_temporary_roles(self):
        for title in ['Manufacturing Engineering, Propulsion', 'Mechanical Engineer, Welding', 'Construction Mechanical Engineer II', 'Sourcing Specialist, Electro Mechanical']:
            self.assertFalse(self.classify(title, 'June 2027 start', 1)['queue_eligible'])
        self.assertFalse(self.classify('Mechanical Associate Engineer', 'June 2027. Temporary position for 12 weeks.', 0)['queue_eligible'])
