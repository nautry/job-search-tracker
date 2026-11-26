import unittest
from src.lifecycle import mark_related
from src.puller import apply_recency_policy, finalize_decisions

def job(id, **kw):
    return {'id':'greenhouse:test:'+id,'company':'Employer','title':'Mechanical Engineer I','location':'Boston, MA','first_seen':'2026-10-01','availability':'Seen in latest search','employer_internal_job_id':77,'qualification_category':'Recommended','queue_eligible':True,'availability_state':'Verified active','accepting_applications':True,**kw}

class RecencyCleanup(unittest.TestCase):
    def test_exact_group_keeps_one_representative_and_history(self):
        rows=mark_related([job('1'),job('2')])
        self.assertEqual(len(rows),2)
        self.assertEqual(sum(j['duplicate_kind']=='canonical' for j in rows),1)
        decisions=finalize_decisions(rows,'2026-11-25T18:00:00Z')
        self.assertEqual(sorted(j['category'] for j in decisions),['Duplicate','Recommended'])
        canonical=next(j for j in rows if j['duplicate_kind']=='canonical')
        self.assertIn(next(j['id'] for j in rows if j['id']!=canonical['id']),canonical['related_ids'])

    def test_uncorroborated_legacy_alias_is_only_suspected(self):
        a=job('1',aliases=['greenhouse:test:2'],identity_version=3)
        b=job('2',employer_internal_job_id=None,title='Mechanical Engineer, Different Program')
        rows=mark_related([a,b])
        self.assertTrue(all(j['duplicate_kind']=='possible' for j in rows))

    def test_shared_requisition_text_does_not_merge_distinct_positions(self):
        rows=mark_related([job('1',employer_requisition_id='OPEN'),job('2',employer_internal_job_id=88,employer_requisition_id='OPEN')])
        self.assertTrue(all(j['canonical_id']==j['id'] for j in rows))

    def test_original_alias_date_cannot_be_laundered_by_repost(self):
        rows=mark_related([job('1',posted_at='2026-09-01'),job('2',posted_at='2026-11-25')])
        canonical=next(j for j in rows if j['duplicate_kind']=='canonical')
        self.assertEqual(canonical['posted_at'],'2026-09-01')

    def test_rolling_calendar_boundary_and_unknown_date(self):
        rows=[job('1',posted_at='2026-10-11'),job('2',posted_at='2026-10-10'),job('3',first_seen='2026-11-25'),job('4',posted_at='2026-11-26')]
        out=apply_recency_policy(rows,{'max_posting_age_days':45},'2026-11-25T18:00:00Z')
        self.assertEqual([j['queue_eligible'] for j in out],[True,False,False,False])
        self.assertEqual(out[2]['recency_state'],'Unknown employer posting date')

    def test_tracker_midnight_is_used_not_utc_midnight(self):
        a=apply_recency_policy([job('1',posted_at='2026-10-11')],{},'2026-11-26T04:59:59Z')[0]
        b=apply_recency_policy([job('1',posted_at='2026-10-11')],{},'2026-11-26T05:00:00Z')[0]
        self.assertTrue(a['queue_eligible']);self.assertFalse(b['queue_eligible'])
