import json
from pathlib import Path
import unittest
from unittest.mock import patch
from src.puller import assess, location_fit, experience, reconcile, collect, plain

PREFS = json.loads((Path(__file__).parents[1] / 'config/preferences.json').read_text())

def job(**kw):
    return dict(id='greenhouse:test:1',source='test',company='Test',title='Mechanical Engineer I',location='Austin, Texas, United States',url='https://example.com/jobs/1',description='Mechanical engineering. Creo CAD and prototype design. Python sensors.',**kw)

class Core(unittest.TestCase):
    def test_preferences_can_change_without_code_edits(self):
        prefs={**PREFS,'excluded_companies':['Test']}
        self.assertIsNone(assess(job(),prefs))
        prefs={**PREFS,'role_patterns':['product development engineer']}
        j=job();j['title']='Product Development Engineer'
        self.assertIsNotNone(assess(j,prefs))
        prefs={**PREFS,'required_location_keywords':['Boston']}
        self.assertIsNone(assess(job(),prefs))
        prefs={**PREFS,'max_required_years':0}
        j=job();j['description']='Requires 2 years of experience.'
        self.assertIsNone(assess(j,prefs))
    def test_fit_and_location(self):
        j=assess(job(),PREFS)
        self.assertGreater(j['role_score'],60)
        self.assertIn('Austin',j['location_fit'])
        self.assertEqual(location_fit('Cedar Rapids, IA',PREFS)[1],-15)
        self.assertIn('Location review',location_fit('Unknown',PREFS)[0])
    def test_seniority(self):
        for title in ['Senior Mechanical Engineer','Staff Test Engineer','Mechanical Engineer III','Mechanical Engineering Intern']:
            j=job();j['title']=title
            self.assertIsNone(assess(j,PREFS))
        j=job();j['description']='Requires 5 years of professional experience.'
        self.assertIsNone(assess(j,PREFS))
    def test_preferred_experience_not_hard_exclusion(self):
        self.assertIsNone(experience('Preferred: 5 years of experience.'))
        self.assertEqual(experience('Requires 2-4 years of engineering experience.'),2)
    def test_html_qualifications_keep_boundaries(self):
        text=plain('<li>Requires 5 years of experience</li><li>Preferred: Python</li>')
        self.assertIn('\n',text)
        self.assertEqual(experience(text),5)
        j=job();j['title']='Mechanical Engineer, 2+ years of experience'
        self.assertLessEqual(assess(j,PREFS)['role_score'],75)
    def test_international(self):
        j=job();j['location']='Auckland, New Zealand'
        self.assertIsNone(assess(j,PREFS))
    def test_retention_failure_does_not_advance_last_seen(self):
        old={**assess(job(),PREFS),'first_seen':'2026-01-01','last_seen':'2026-01-02'}
        rows=reconcile([old],[],[{'source':'test','status':'failed'}],'2026-01-03')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['last_seen'],'2026-01-02')
        self.assertIn('retained',rows[0]['availability'])
    def test_stable_id_no_duplicates(self):
        j=assess(job(),PREFS)
        a=reconcile([],[j],[{'source':'test','status':'ok'}],'2026-01-01')
        b=reconcile(a,[j],[{'source':'test','status':'ok'}],'2026-01-02')
        self.assertEqual(len(b),1)
        self.assertEqual(b[0]['first_seen'],'2026-01-01')
        self.assertEqual(b[0]['last_seen'],'2026-01-02')
    def test_malformed_schema_is_failure(self):
        with patch('src.puller.get_json',return_value={'unexpected':[]}):
            with self.assertRaises(ValueError):
                collect({'provider':'greenhouse','slug':'test'})
    def test_missing_after_complete_search_is_not_declared_closed(self):
        j=assess(job(),PREFS)
        rows=reconcile([j],[],[{'source':'test','status':'ok'}],'2026-01-03')
        self.assertIn('Not seen',rows[0]['availability'])

if __name__=='__main__':unittest.main()
