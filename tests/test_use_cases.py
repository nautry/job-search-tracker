import json
import unittest
from pathlib import Path
from src.puller import assess, use_case_fit, experience


class UseCasePreferences(unittest.TestCase):
    def setUp(self):
        self.prefs = json.loads((Path(__file__).parents[1] / 'config/preferences.json').read_text())
        self.job = dict(company='RTX', title='Mechanical Test Engineer I', location='Tucson, Arizona',
                        description='Mechanical engineering CAD prototypes and test fixtures.',
                        use_case_sector='defense_review', id='test:rtx:1', url='https://example.com/job')

    def test_missile_role_is_retained_but_deprioritized(self):
        base = assess(self.job, self.prefs)
        weapon = assess({**self.job, 'description': self.job['description'] + ' Develop missile test fixtures.'}, self.prefs)
        self.assertIsNotNone(weapon)
        self.assertLess(weapon['priority'], base['priority'])
        self.assertIn('Direct weapons context', weapon['flags'])

    def test_military_aircraft_is_not_treated_as_missile_work(self):
        aircraft = use_case_fit({**self.job, 'description': 'Fighter aircraft mechanical integration'}, self.prefs)
        missile = use_case_fit({**self.job, 'description': 'Missile mechanical integration'}, self.prefs)
        self.assertGreater(aircraft[1], missile[1])

    def test_citizenship_or_itar_alone_is_not_a_weapon_signal(self):
        label, _, _ = use_case_fit({**self.job, 'use_case_sector': 'civilian_hardware', 'description': 'ITAR and US citizenship required for space hardware'}, self.prefs)
        self.assertNotIn('Direct weapons', label)

    def test_medical_application_preferred_for_same_technical_fit(self):
        medical = assess({**self.job, 'company': 'Intuitive', 'use_case_sector': 'medical'}, self.prefs)
        defense = assess(self.job, self.prefs)
        self.assertEqual(medical['role_score'], defense['role_score'])
        self.assertGreater(medical['priority'], defense['priority'])

    def test_undergraduate_requirement_is_not_replaced_by_graduate_alternative(self):
        self.assertEqual(experience('Minimum 4 years of hardware product design experience with undergraduate degree, or minimum 2 years with graduate degree.'), 4)
        self.assertIsNone(assess({**self.job, 'description': 'Minimum 4 years of hardware product design experience with undergraduate degree, or minimum 2 years with graduate degree.'}, self.prefs))

    def test_largest_separate_required_minimum_is_preserved(self):
        self.assertEqual(experience('Requires 4 years of mechanical design experience. Requires 1 year of CAD experience.'), 4)

    def test_earlier_graduation_cohort_is_lower_priority(self):
        original = assess(self.job, self.prefs)
        earlier = assess({**self.job, 'title': 'Mechanical Engineer I - 2026 Graduate'}, self.prefs)
        self.assertLess(earlier['priority'], original['priority'])
        self.assertIn('Start eligibility conflict', earlier['flags'])

    def test_policy_is_optional_and_configurable(self):
        self.assertEqual(use_case_fit(self.job, {})[1], 0)
        self.prefs['use_case_preferences']['direct_weapons_adjustment'] = -40
        self.assertEqual(use_case_fit({**self.job, 'description': 'missile design'}, self.prefs)[1], -40)


if __name__ == '__main__':
    unittest.main()
