import unittest
from unittest.mock import patch
from src.eligibility import assess_eligibility
from src.puller import verify_posting, finalize_decisions, experience

class PracticalScreening(unittest.TestCase):
    def screen(self,extra='',years=0,title='Mechanical Engineer I',base="Bachelor's degree in Mechanical Engineering. CAD design and prototypes.\n"):
        return assess_eligibility({'title':title,'description':base+extra},{'graduation':'2027-05'},years,'Seattle metro')
    def test_unspecified_timing_is_caveat_not_rejection(self):
        j=self.screen(years=1)
        self.assertEqual(j['category'],'Recommended');self.assertIn('timing unconfirmed',j['start_eligibility'])
    def test_actual_incompatible_start_and_cohort(self):
        for text in ['Must start in January 2027.','Required to join within 30 days.','Start immediately.']:
            self.assertEqual(self.screen(text)['category'],'Ineligible')
        self.assertEqual(self.screen(title='2026 New Graduate Mechanical Engineer')['category'],'Ineligible')
    def test_unrelated_calendar_date_is_not_start_requirement(self):
        self.assertEqual(self.screen('Benefits renew January 2027.')['category'],'Recommended')
    def test_explicit_cohort_is_separate_from_generic_title(self):
        explicit=self.screen('Graduating May 2027.',title='2027 New Graduate Mechanical Engineer')
        generic=self.screen()
        self.assertIn('cohort',explicit['start_eligibility']);self.assertIn('unconfirmed',generic['start_eligibility'])
    def test_experience_gap_and_equivalence(self):
        self.assertEqual(self.screen(years=2)['category'],'Stretch')
        self.assertEqual(self.screen('Requires 2 years of experience; academic projects count.',years=2)['category'],'Recommended')
        self.assertEqual(self.screen(years=3)['category'],'Ineligible')
    def test_missing_degree_is_noncritical_when_entry_duties_clear(self):
        self.assertEqual(self.screen(base='CAD prototypes and mechanical design.\n')['category'],'Recommended')
    def test_incompatible_degree_is_not_hidden_by_title(self):
        self.assertEqual(self.screen(base='Required bachelor degree in Electrical Engineering. CAD prototypes.\n')['category'],'Ineligible')
        self.assertEqual(self.screen(base='Masters degree required. CAD prototypes.\n')['category'],'Ineligible')
    def test_unknown_experience_generic_role_is_material_hold(self):
        self.assertEqual(self.screen(years=None,title='Mechanical Engineer')['category'],'Hold')
        self.assertEqual(self.screen(years=None,title='Mechanical Engineer I')['category'],'Recommended')
    def test_manufacturing_scope_suffix_is_consistent_with_views(self):
        self.assertEqual(self.screen(title='Mechanical Engineer, Optical Manufacturing')['category'],'Ineligible')
        self.assertEqual(self.screen(title='Mechanical Design Engineer, Production')['category'],'Ineligible')
    def test_specialist_role_and_clearance(self):
        self.assertEqual(self.screen(title='RF Test Engineer I')['category'],'Ineligible')
        self.assertEqual(self.screen('Active Secret clearance required.')['category'],'Hold')
        self.assertEqual(self.screen('Must be able to obtain a clearance.')['category'],'Recommended')
    def test_final_decisions_require_acceptance_evidence(self):
        base=dict(qualification_category='Recommended',availability_state='Unverified',queue_eligible=True)
        self.assertEqual(finalize_decisions([base.copy()],'2026-11-19')[0]['category'],'Hold')
        active={**base,'availability_state':'Verified active','accepting_applications':True}
        self.assertEqual(finalize_decisions([active],'2026-11-19')[0]['category'],'Recommended')
        self.assertEqual(finalize_decisions([{**active,'related_ids':['older']}],'2026-11-19')[0]['category'],'Hold')

class Response:
    url='https://job-boards.greenhouse.io/test/jobs/1'
    def __init__(self,body=b'<html>Job details only</html>'):self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):return self.body

class AcceptingEvidence(unittest.TestCase):
    job=dict(id='greenhouse:test:1',url=Response.url,observed_this_run=True)
    def check(self,detail,body=b'<html>Job details only</html>'):
        with patch('src.puller.get_json',return_value=detail),patch('src.puller.urllib.request.urlopen',return_value=Response(body)):
            return verify_posting(self.job)
    def test_http_success_alone_is_inconclusive(self):
        self.assertEqual(self.check({'id':1,'content':'CAD'})['verification_result'],'unverified')
    def test_job_specific_application_fields_are_positive_evidence(self):
        j=self.check({'id':1,'content':'CAD','questions':[{'fields':[{'name':'email'}]}]})
        self.assertEqual(j['verification_result'],'active');self.assertIn('application fields',j['application_evidence'])
    def test_custom_employer_domain_from_official_api_is_supported(self):
        with patch('src.puller.get_json',return_value={'id':1,'content':'CAD','absolute_url':'https://careers.formlabs.com/job/1','questions':[{'fields':[{'name':'email'}]}]}),patch('src.puller.urllib.request.urlopen',return_value=Response()):
            self.assertEqual(verify_posting(self.job)['verification_result'],'active')
    def test_workday_explicit_state(self):
        j={'id':'workday:test:R1','url':'https://test.wd5.myworkdayjobs.com/en-US/Jobs/job/1','detail_api':'https://test.wd5.myworkdayjobs.com/wday/cxs/test/Jobs/job/1','observed_this_run':True}
        with patch('src.puller.get_json',return_value={'jobPostingInfo':{'canApply':False}}):
            self.assertEqual(verify_posting(j)['verification_result'],'closed')

class RequirementParsing(unittest.TestCase):
    def test_preference_does_not_hide_explicit_requirement(self):
        self.assertEqual(experience('Requires 2 years of professional experience. Python preferred.'),2)
        self.assertEqual(experience('Requires 2 years of professional experience; Python preferred.'),2)
        self.assertEqual(experience('Requires 2 years of experience, Python preferred.'),2)

    def test_written_years_and_zero_to_two_ranges(self):
        self.assertEqual(experience('Requires two years of professional experience.'),2)
        self.assertEqual(experience('Requires three years of engineering experience.'),3)
        self.assertEqual(experience('Requires zero to two years of relevant experience.'),0)
