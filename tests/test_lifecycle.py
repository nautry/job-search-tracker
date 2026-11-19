import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from src.lifecycle import normalize_url, identity_evidence, deduplicate, mark_related, availability
from src.puller import verify_posting, reconcile

def job(id='greenhouse:test:1', **kw):
    return dict(id=id, company='Employer', source='test', title='Mechanical Engineer', location='Austin, TX', url='https://job-boards.greenhouse.io/test/jobs/'+id.split(':')[-1], priority=80, **kw)

class Lifecycle(unittest.TestCase):
    def test_tracking_removed_identity_preserved(self):
        self.assertEqual(normalize_url('https://job-boards.greenhouse.io/test/jobs/123?utm_source=x&gh_jid=123&gh_src=y#apply'), 'https://job-boards.greenhouse.io/test/jobs/123')
        self.assertIn('jobId=5',normalize_url('https://example.com/careers?jobId=5&utm_campaign=x'))
    def test_exact_endpoint_and_multilocation(self):
        a=job();b={**a,'id':'greenhouse:alias:1','location':'Seattle, WA'}
        rows=deduplicate([a],[a,b,a]);self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['id'],a['id']);self.assertIn('Seattle',rows[0]['location'])
        self.assertEqual(rows[0]['exact_duplicates_collapsed'],2)
    def test_separate_requisitions_preserved(self):
        a=job();b={**a,'id':'greenhouse:test:2'}
        self.assertEqual(len(deduplicate([],[a,b])),2)
        self.assertFalse(any(j['related_ids'] for j in mark_related([a,b])))
    def test_repost_text_flags_never_merges(self):
        desc=' '.join('hardware CAD mechanism prototype validation structural engineering design sensor '+str(i) for i in range(30))
        a={**job(),**identity_evidence({'description':desc})};b={**a,'id':'greenhouse:test:2'}
        b['title']='Mechanical Engineer - New Graduate 2027'
        rows=mark_related([a,b]);self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['related_ids'],[b['id']]);self.assertIn('Possible repost',rows[0]['duplicate_state'])
        b['location']='Boston, MA';self.assertFalse(mark_related([a,b])[0]['related_ids'])
    def test_partial_failed_scoped_never_close(self):
        old={**job(),'availability_state':'Verified active','last_confirmed_active':'2026-11-18T10:00:00Z'}
        for source in [{'status':'failed','full_board':True},{'status':'partial','full_board':True},{'status':'ok','full_board':False}]:
            self.assertEqual(availability(old,{},'2026-11-18T12:00:00Z',False,source)['availability_state'],'Verified active')
        self.assertEqual(availability(old,{},'2026-11-20T12:00:00Z',False,{'status':'failed'})['availability_state'],'Stale')
    def test_missing_complete_board_uncertain_not_closed(self):
        source={'status':'ok','full_board':True}
        row=availability(job(),{},'2026-11-18T12:00:00Z',False,source)
        self.assertEqual(row['availability_state'],'Unverified');self.assertEqual(row['missing_full_runs'],1)
        self.assertEqual(availability(row,{},'2026-11-18T13:00:00Z',False,source)['missing_full_runs'],1)
    def test_closed_reopening_requires_positive_check(self):
        old={**job(),'availability_state':'Confirmed closed'}
        self.assertEqual(availability(old,job(),'2026-11-18T12:00:00Z',True,{})['availability_state'],'Confirmed closed')
        self.assertEqual(availability(old,{**job(),'verification_result':'active'},'2026-11-18T12:00:00Z',True,{})['availability_state'],'Verified active')
    def test_inaccessible_and_removed_links(self):
        for code,expected in [(404,'closed'),(410,'closed'),(403,'unverified'),(429,'unverified')]:
            with patch('src.puller.get_json',side_effect=HTTPError('https://example.com',code,'error',{},None)):
                self.assertEqual(verify_posting(job())['verification_result'],expected)
        with patch('src.puller.get_json',side_effect=URLError('offline')):
            self.assertEqual(verify_posting(job())['verification_result'],'unverified')
    def test_explicit_closed_content(self):
        class Response:
            url='https://job-boards.greenhouse.io/test/jobs/1'
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'<p>This job is no longer accepting applications.</p>'
        with patch('src.puller.get_json',return_value={'id':1,'content':'CAD'}),patch('src.puller.urllib.request.urlopen',return_value=Response()):
            self.assertEqual(verify_posting(job(observed_this_run=True))['verification_result'],'closed')
    def test_history_retained(self):
        old={**job(),'first_seen':'2025-01-01','last_seen':'2025-01-02','availability_state':'Confirmed closed'}
        row=reconcile([old],[],[{'source':'test','status':'failed'}],'2026-11-18T12:00:00Z')[0]
        self.assertEqual(row['first_seen'],'2025-01-01');self.assertEqual(row['last_seen'],'2025-01-02')
        self.assertEqual(row['availability_state'],'Confirmed closed')
