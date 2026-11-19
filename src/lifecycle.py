"""Conservative identity and availability evidence; never merges semantic guesses."""
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def normalize_url(url):
    p = urlsplit(url)
    tracking = {'gh_src', 'source', 'lever-source', 'lever-origin', 'ref', 'referrer', 'sourceid', 'trackingid'}
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in tracking
             and not (k == 'gh_jid' and re.search(r'/jobs/' + re.escape(v) + r'/?$', p.path))]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))


def identity_evidence(job):
    desc = re.sub(r'\s+', ' ', job.get('description', '')).strip().casefold()
    words = re.findall(r'[a-z0-9]+', desc)
    # Bounded shingles allow cautious near-text comparisons without publishing descriptions.
    shingles = sorted({hashlib.sha256(' '.join(words[i:i+5]).encode()).hexdigest()[:12]
                       for i in range(max(0, len(words)-4))})
    return {'description_hash': hashlib.sha256(desc.encode()).hexdigest() if desc else '',
            'description_signature': shingles[:128], 'description_words': len(words)}


def company_key(job):
    return re.sub(r'\W+', '', job['company'].casefold())


def requisition(job):
    return str(job.get('requisition_id') or job['id'].split(':', 2)[-1]).casefold()


def deduplicate(previous, observed):
    """Collapse only proven identity in new observations; keep every historical record."""
    def key_for(j):
        provider=j['id'].split(':',1)[0]
        return (company_key(j),provider,str(j.get('employer_requisition_id') or j.get('requisition_id') or j['id'].split(':',2)[-1]).casefold())
    old_keys = {}
    for j in previous:old_keys.setdefault(key_for(j), j['id'])
    known_ids = {j['id'] for j in previous}
    result, positions = [], {}
    for raw in observed:
        j = {**raw, 'url': normalize_url(raw['url'])}
        key = key_for(j)
        # Preserve the original stable ID even if source aliases/endpoint names change.
        stable = j['id'] if j['id'] in known_ids else old_keys.get(key, j['id'])
        aliases = list(dict.fromkeys(j.get('aliases', []) + ([j['id']] if stable != j['id'] else [])))
        j = {**j, 'id': stable, 'aliases': aliases}
        if key in positions:
            current = result[positions[key]]
            locations = list(dict.fromkeys([current['location'], j['location']]))
            current['location'] = '; '.join(locations)
            current['aliases'] = list(dict.fromkeys(current.get('aliases', []) + aliases))
            current['exact_duplicates_collapsed'] = current.get('exact_duplicates_collapsed', 0) + 1
        else:
            positions[key] = len(result)
            result.append(j)
    return result


def mark_related(jobs):
    groups = {}
    for j in jobs:
        j['related_ids'] = []
        j['duplicate_state'] = 'Distinct / no duplicate evidence'
        title = re.sub(r'[^a-z0-9]+', ' ', j['title'].casefold()).strip()
        j['_identity_title'] = re.sub(r'\b(?:new graduate|new grad|20\d{2})\b', '', title).strip()
        groups.setdefault(company_key(j), []).append(j)
    for group in groups.values():
        for i, a in enumerate(group):
            for b in group[i+1:]:
                same_req = requisition(a) == requisition(b)
                ta, tb = set(a['_identity_title'].split()), set(b['_identity_title'].split())
                title_close = bool(ta | tb) and len(ta & tb)/len(ta | tb) >= .85
                if not same_req and not title_close:
                    continue
                sa, sb = set(a.get('description_signature', [])), set(b.get('description_signature', []))
                near = min(a.get('description_words', 0), b.get('description_words', 0)) >= 80 and bool(sa | sb) and len(sa & sb) / len(sa | sb) >= .90
                # Same title alone is never enough. Different IDs stay separate even for identical text.
                if same_req or (near and a['location'].casefold() == b['location'].casefold()):
                    for one, other in [(a, b), (b, a)]:
                        one['related_ids'].append(other['id'])
                        one['duplicate_state'] = 'Exact requisition alias; review history' if same_req else 'Possible repost / duplicate; distinct requisitions retained'
    for j in jobs:
        j.pop('_identity_title', None)
    return jobs


def hours_since(value, timestamp):
    try:
        a = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        b = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return (b.replace(tzinfo=b.tzinfo or timezone.utc) - a.replace(tzinfo=a.tzinfo or timezone.utc)).total_seconds()/3600
    except (ValueError, TypeError):
        return float('inf')


def availability(previous, job, timestamp, seen, source):
    """Only explicit employer evidence closes a role. Missing feeds alone never close it."""
    out = {**previous, **job}
    out['verification_version'] = 2
    if job.get('verification_result') == 'closed':
        out.update(availability_state='Confirmed closed', application_state='Confirmed closed', accepting_applications=False, availability_checked_at=timestamp,
                   verification_detail=job.get('verification_detail', 'Employer explicitly closed posting'))
    elif job.get('verification_result') == 'active':
        out.update(availability_state='Verified active', application_state='Verified accepting applications', accepting_applications=True, last_confirmed_active=timestamp,
                   availability_checked_at=timestamp, missing_full_runs=0)
    else:
        full = source.get('status') == 'ok' and source.get('full_board') is True
        misses = previous.get('missing_full_runs', 0)
        if not seen and full and (not previous.get('missing_checked_at') or hours_since(previous['missing_checked_at'], timestamp) >= 24):
            misses += 1
            out['missing_checked_at'] = timestamp
        out['missing_full_runs'] = misses
        if previous.get('availability_state') == 'Confirmed closed':
            out['availability_state'] = 'Confirmed closed'  # Reopening needs positive verification.
        elif job.get('verification_result') == 'unverified' or (not seen and full):
            out['availability_state'] = 'Unverified'
        elif not out.get('accepting_applications') or previous.get('verification_version') != 2 or hours_since(out.get('last_confirmed_active'), timestamp) > 72:
            out['availability_state'] = 'Stale' if out.get('last_confirmed_active') else 'Unverified'
        else:
            out['availability_state'] = 'Verified active'
        if out['availability_state'] != 'Verified active':
            out['accepting_applications'] = False
            out['application_state'] = 'Confirmed closed' if out['availability_state']=='Confirmed closed' else 'Verification unavailable or inconclusive'
        if job.get('verification_result'):
            out['availability_checked_at'] = timestamp
    return out


def resume_variant(job):
    title = job['title'].casefold()
    if re.search(r'mechatronic|electromechanical|electro.mechanical|robotic|integration', title):
        return 'Mechatronics'
    if re.search(r'test|validation|verification|r&d|research|performance|reliability', title):
        return 'Test/R&D'
    return 'Design'
