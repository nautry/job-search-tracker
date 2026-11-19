"""Employer-published job collector. Python 3.11+, standard library only."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
if __package__:
    from .eligibility import assess_eligibility, posting_age, recency_points
    from .lifecycle import normalize_url, identity_evidence, deduplicate, mark_related, availability, resume_variant, hours_since
else:
    from eligibility import assess_eligibility, posting_age, recency_points
    from lifecycle import normalize_url, identity_evidence, deduplicate, mark_related, availability, resume_variant, hours_since

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"User-Agent": "PublicJobTracker/1.0", "Accept": "application/json"}
SENIOR = re.compile(r"\b(senior|sr\.?|principal|staff|lead|manager|director|head|chief|iii|iv|v)\b", re.I)
ROLE = re.compile(r"mechanical|mechatronic|electro.?mechanical|manufacturing engineer|test engineer|hardware (design|test|integration)|product design engineer|equipment engineer|tooling engineer|reliability engineer", re.I)
NON_US = re.compile(r"\b(canada|toronto|vancouver|montreal|united kingdom|london|germany|berlin|munich|france|paris|india|bangalore|bengaluru|singapore|china|taiwan|australia|new zealand|auckland|hungary|budapest|poland|warsaw|mexico|brazil|netherlands|japan|israel|sweden|ireland)\b", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def plain(value):
    value = html.unescape(value or "")
    value = re.sub(r"(?i)</(?:p|li|div|h[1-6])>|<br\s*/?>", "\n", value)
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return '\n'.join(re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines() if line.strip())


def get_json(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={**HEADERS, **({"Content-Type": "application/json"} if data else {})})
    # No retries on 403/429, no proxies or access-control bypasses.
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.load(response)


def location_fit(location, prefs):
    loc = location.lower()
    if any(re.search(r"\b" + re.escape(x) + r"\b", loc) for x in prefs["deprioritized_locations"]):
        return "Deprioritized region", -15
    for metro, names in prefs["preferred_metros"].items():
        if any(re.search(r"\b" + re.escape(x) + r"\b", loc) for x in names):
            return metro + " metro (commute review)", 10
    # State abbreviations require comma separation; do not match ordinary words.
    if re.search(r",\s*(OH|IN|IL|MI|WI|MN|IA|MO|KS|NE|ND|SD|WV)\b", location):
        return "Deprioritized region", -15
    return "Location review", 0


def experience(text):
    """Extract requirements conservatively; preferred experience does not exclude."""
    words={"zero":"0","one":"1","two":"2","three":"3","four":"4","five":"5","six":"6","seven":"7","eight":"8","nine":"9","ten":"10"}
    text=re.sub(r"\b("+"|".join(words)+r")\b",lambda m:words[m.group(0).lower()],text,flags=re.I).replace("-to-"," to ")
    chunks = re.split(r"(?<=[.!?;])\s+|[\n\r]", text)
    minimums = []
    for chunk in chunks:
        if re.search(r"preferred|desirable|nice.to.have", chunk, re.I) and not re.search(r"require|minimum|must|at least",chunk,re.I):
            continue
        if re.search(r"master|ph\.?d|doctor|graduate degree", chunk, re.I):
            # Resolve degree alternatives within clauses, rather than letting a
            # graduate-degree alternative hide the applicant's BS requirement.
            clauses = re.split(r"\bor\b|[,;]", chunk, flags=re.I)
            degree_pattern = r"\b(?:bachelor|bachelors|undergraduate|bs|bsc)\b"
            bachelor_clauses = [c for c in clauses if re.search(degree_pattern, c, re.I)]
            candidates = bachelor_clauses or [c for c in clauses if not re.search(r"master|ph\.?d|doctor|graduate degree", c, re.I)]
            for candidate in candidates:
                requirement = re.search(r"\b(\d{1,2})(?:\s*(?:[-–]|to)\s*\d{1,2})?\s*\+?\s*years?\b", candidate, re.I)
                if requirement:
                    minimums.append(int(requirement.group(1)))
            continue
        for m in re.finditer(r"\b(\d{1,2})(?:\s*(?:[-–]|to)\s*\d{1,2})?\s*\+?\s*years?\s+(?:of\s+)?(?:(?:[A-Za-z/-]+)\s+){0,8}experience", chunk, re.I):
            if not re.match(r"\s*(?:\w+\s+){0,2}(?:preferred|desirable)\b",chunk[m.end():],re.I):
                minimums.append(int(m.group(1)))
    return max(minimums) if minimums else None


def use_case_fit(job, prefs):
    """Explain keyword evidence and preferences, not an ethical certification."""
    policy = prefs.get("use_case_preferences", {})
    if not policy:
        return "Not assessed", 0, ""
    text = job["title"] + "\n" + job.get("description", "")
    hits = [pattern for pattern in policy.get("direct_weapons_patterns", []) if re.search(pattern, text, re.I)]
    if hits:
        terms = sorted({m.group(0).lower() for pattern in hits for m in re.finditer(pattern, text, re.I)})
        return "Direct weapons context: review", 0, "Direct-weapons keyword evidence: " + ", ".join(terms[:5]) + "; verify whether role duties or company boilerplate"
    if any(re.search(pattern, text, re.I) for pattern in policy.get("military_aircraft_patterns", [])):
        return "Military aircraft / dual use: review", 0, "Military aircraft context; user review of actual mission and program required"
    if re.search(r"\b(commercial (aircraft|aviation)|civil aviation|passenger aircraft)\b", text, re.I):
        return "Civil aviation context: verify program", 0, "Explicit civil/commercial aviation wording; verify team and program"
    sector = job.get("use_case_sector", "unknown")
    labels = {"medical": ("Medical devices / rehabilitation", "medical_adjustment", 8), "sports": ("Sports / wellness hardware", "sports_adjustment", 8), "civilian_hardware": ("Civilian product / industrial hardware", "civilian_hardware_adjustment", 4), "defense_review": ("Defense or dual-use employer; role unspecified", "defense_unspecified_adjustment", -8)}
    if sector in labels:
        label, _, _ = labels[sector]
        return label, 0, "Employer-sector context; verify actual product and team"
    return "Use case not established: review", 0, "Employer name alone does not establish end use"


def assess(job, prefs):
    title, desc, loc = job["title"], job.get("description", ""), job["location"]
    role_pattern = re.compile('|'.join(prefs.get('role_patterns', [ROLE.pattern])), re.I)
    if job['company'].casefold() in {x.casefold() for x in prefs.get('excluded_companies', [])}:
        return None
    if any(x.casefold() in (title+' '+desc).casefold() for x in prefs.get('excluded_keywords', [])):
        return None
    if any(x.casefold() in loc.casefold() for x in prefs.get('excluded_location_keywords', [])):
        return None
    required_locations = prefs.get('required_location_keywords', [])
    if required_locations and not any(x.casefold() in loc.casefold() for x in required_locations):
        return None
    if not role_pattern.search(title) or SENIOR.search(title):
        return None
    if NON_US.search(loc) and not re.search(r"united states|\busa\b", loc, re.I):
        return None
    if re.search(r"quality engineer", title, re.I) and not (re.search(r"mechanical engineering", desc, re.I) and re.search(r"hardware|physical|manufactur|device", desc, re.I)):
        return None
    years = experience(title + '\n' + desc)
    score = 42
    evidence = []
    if re.search(r"mechanical|mechatronic|electro.?mechanical|product design", title, re.I):
        score += 18
        evidence.append("Design / electromechanical role")
    else:
        score += 8
        evidence.append("Test / manufacturing / equipment role")
    for label, words in prefs["skills"].items():
        hits = [w for w in words if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", desc, re.I)]
        if hits:
            score += 6
            evidence.append(label + ": " + ", ".join(hits[:3]))
    early = bool(re.search(r"entry.level|new.grad|university.grad|engineer i\b|associate|2027", title + " " + desc[:2500], re.I))
    score += 10 if early else 0
    score = min(score, 95 if early else 82)
    if years == 2:
        score = min(score, 75)
    if years is not None and years >= 3:
        score = min(score, 65)
    flags = []
    if years is None:
        flags.append("Experience minimum not parsed; review qualifications")
    elif years:
        flags.append(f"Requires {years}+ years; experience gap review")
    if re.search(r"clearance|u\.?s\.? citizen|us person|u\.?s\.? person|export control|itar", desc, re.I):
        flags.append("Citizenship / export / clearance: review")
    if re.search(r"electrical engineering|computer engineering|pcb|fpga|rf design", desc, re.I):
        flags.append("Check electrical-specialist requirements")
        if not re.search(r"mechanical engineering", desc, re.I):
            score = min(score, 50)
    geo, bonus = location_fit(loc, prefs)
    if geo == "Location review":
        flags.append("US location / city proximity needs review")
    salary = job.get("salary", "")
    if not salary:
        match = re.search(r"\$[\d,]+(?:\.\d+)?\s*(?:-|–|to)\s*\$?[\d,]+(?:\.\d+)?", desc)
        salary = match.group(0) if match else "Not disclosed / not parsed"
        if match:
            salary += " (verify period and base pay)"
    # Salary is intentionally review-only until a currency/period-aware floor is configured.
    if prefs.get("salary_floor") is not None:
        flags.append("Salary floor configured; manual salary review required")
    if score < prefs["minimum_role_score"]:
        return None
    assessment = assess_eligibility(job, prefs, years, geo)
    flags.extend(assessment.pop("eligibility_flags"))
    age = posting_age(job.get("posted_at"))
    freshness = recency_points(age)
    weights = prefs["ranking_weights"]
    priority = score * weights["fit"] + bonus * weights["location"] + freshness * weights["freshness"]
    priority += {"Recommended": 12, "Stretch": -10, "Hold": -15, "Ineligible": -35}[assessment["category"]]
    if assessment["start_eligibility"].startswith("Explicit start"):
        priority -= 25
    use_case, _, use_case_reason = use_case_fit(job, prefs)
    if use_case_reason:
        flags.append("Use case: " + use_case)
        evidence.append("Product context: " + use_case_reason)
    flags.extend(["Employer publication date unavailable"] if age is None else
                 ["Posting over 45 days old; verify availability"] if age > 45 else [])
    return {k: v for k, v in {
        **job, **assessment, **identity_evidence(job), "requisition_id": str(job.get("requisition_id") or job["id"].split(":", 2)[-1]), "resume_variant": resume_variant(job), "use_case": use_case, "use_case_adjustment": 0,
        "role_score": score, "priority": round(max(0, min(100, priority)), 1),
        "location_fit": geo, "experience": f"{years}+ years required (parsed)" if years is not None else "Early-career wording; numeric minimum not extracted" if assessment["screening_evidence"]["entry_signal"] else "Experience level unresolved by automatic screening",
        "salary": salary, "flags": "; ".join(flags), "evidence": "; ".join(evidence),
        "posting_age": age, "recency_points": freshness * weights["freshness"],
    }.items() if k != "description"}


def canonical(board, raw_id, title, location, url, description, **extra):
    if not re.match(r"https://", url or ""):
        raise ValueError("Missing HTTPS posting URL")
    return {"id": f"{board['provider']}:{board['slug']}:{raw_id}", "source": board["slug"], "provider_job_id": str(raw_id), "company": board["company"], "title": title, "location": location or "Location not supplied", "url": normalize_url(url), "description": plain(description), "use_case_sector": board.get("use_case_sector", "unknown"), **extra}


def collect(board):
    provider, slug = board["provider"], board["slug"]
    jobs, errors = [], []
    if provider == "greenhouse":
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if not isinstance(data.get("jobs"), list):
            raise ValueError("Unexpected Greenhouse schema")
        for j in data["jobs"]:
            jobs.append(canonical(board, j["id"], j["title"], j.get("location", {}).get("name", ""), j["absolute_url"], j.get("content", ""), posted_at=j.get("first_published", ""), employer_requisition_id=j.get("requisition_id"), employer_internal_job_id=j.get("internal_job_id")))
        return jobs, True, errors
    if provider == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
        if not isinstance(data.get("jobs"), list):
            raise ValueError("Unexpected Ashby schema")
        for j in data["jobs"]:
            if j.get("isListed", True):
                jobs.append(canonical(board, j["id"], j["title"], j.get("location", ""), j.get("jobUrl") or j.get("applyUrl"), j.get("descriptionPlain") or j.get("descriptionHtml", ""), employment_type=j.get("employmentType", ""), posted_at=j.get("publishedAt", ""), apply_url=j.get("applyUrl", "")))
        return jobs, True, errors
    if provider == "lever":
        data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if not isinstance(data, list):
            raise ValueError("Unexpected Lever schema")
        for j in data:
            desc = j.get("descriptionPlain", "") + "\n" + j.get("additionalPlain", "") + "\n" + "\n".join(x.get("text", "") + " " + plain(x.get("content", "")) for x in j.get("lists", []))
            jobs.append(canonical(board, j["id"], j["text"], j.get("categories", {}).get("location", ""), j["hostedUrl"], desc, employment_type=j.get("categories", {}).get("commitment", ""), apply_url=j.get("applyUrl", ""), posted_at=datetime.fromtimestamp(j["createdAt"]/1000, timezone.utc).isoformat() if j.get("createdAt") else ""))
        return jobs, True, errors
    if provider == "smartrecruiters":
        api = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        complete = True
        for page in range(board.get("max_pages", 20)):
            data = get_json(api + f"?limit=100&offset={page*100}")
            if not isinstance(data.get("content"), list) or "totalFound" not in data:
                raise ValueError("Unexpected SmartRecruiters schema")
            for j in data["content"]:
                if j.get("location", {}).get("country", "").lower() != "us":
                    continue
                if SENIOR.search(j["name"]) or not re.search(board.get("title_pattern", ROLE.pattern), j["name"], re.I):
                    continue
                detail = get_json(api + "/" + j["id"])
                sections = detail.get("jobAd", {}).get("sections", {})
                description = "\n".join(v.get("text", "") for v in sections.values() if isinstance(v, dict))
                jobs.append(canonical(board, j["id"], j["name"], j["location"].get("fullLocation", j["location"].get("city", "")), detail.get("applyUrl") or f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", description, posted_at=j.get("releasedDate", ""), employment_type=j.get("typeOfEmployment", {}).get("label", "")))
            if (page+1)*100 >= data["totalFound"]:
                break
            if page+1 == board.get("max_pages", 20):
                complete = False
                errors.append("SmartRecruiters page cap reached")
        return jobs, complete, errors
    if provider != "workday":
        raise ValueError("Unsupported source provider")
    api = f"https://{board['host']}/wday/cxs/{board['tenant']}/{board['site']}"
    listings = {}
    complete = True
    for term in board["search_terms"]:
        for page in range(board.get("max_pages", 8)):
            try:
                d = get_json(api + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": term})
                if not isinstance(d.get("jobPostings"), list) or "total" not in d:
                    raise ValueError("Unexpected Workday schema")
                for j in d["jobPostings"]:
                    if (re.search(board.get("title_pattern", ROLE.pattern), j["title"], re.I) or re.search(r"product development|design verification|mechanisms? engineer|integration engineer", j["title"], re.I)) and not SENIOR.search(j["title"]):
                        listings[j["externalPath"]] = j
                if (page + 1) * 20 >= d["total"]:
                    break
                if page + 1 == board.get("max_pages", 8):
                    complete = False
                    errors.append(f"Page cap reached for {term}")
                time.sleep(0.25)
            except (urllib.error.URLError, ValueError, KeyError) as e:
                errors.append(f"{term}: {e}")
                complete = False
                # Stop this employer on access or rate limits.
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 429):
                    return jobs, False, errors
                break
    for i, (path, j) in enumerate(listings.items()):
        if i >= board.get("max_details", 100):
            complete = False
            errors.append("Detail cap reached")
            break
        try:
            d = get_json(api + path)["jobPostingInfo"]
            jobs.append(canonical(board, d.get("jobReqId") or path.rsplit("_", 1)[-1], d.get("title", j["title"]), d.get("location", j.get("locationsText", "")), f"https://{board['host']}/en-US/{board['site']}{path}", d.get("jobDescription", ""), employment_type=d.get("timeType", ""), posted_at=d.get("datePosted", ""), employer_updated_at=d.get("postedOn", ""), detail_api=api + path, verification_result="closed" if d.get("canApply") is False else "", employer_requisition_id=d.get("jobReqId"), verification_detail="Official Workday detail retrieved; application link check pending"))
            time.sleep(0.2)
        except (urllib.error.URLError, ValueError, KeyError) as e:
            complete = False
            errors.append(f"Detail: {e}")
            if isinstance(e, urllib.error.HTTPError) and e.code in (403, 429):
                break
    return jobs, complete, errors


def verify_posting(job):
    """Read-only public ATS/form checks. HTTP 200 alone never establishes acceptance."""
    provider,slug,raw_id=job['id'].split(':',2)
    raw_id=str(job.get('provider_job_id') or raw_id)
    check_url=job['url'];signal='';detail={};declared_host=''
    def result(state,reason,**extra):
        return {**job,'verification_result':state,'verification_version':2,
                'verification_detail':reason,'verification_url':check_url,**extra}
    try:
        if provider=='greenhouse':
            detail=get_json(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{raw_id}?questions=true')
            if str(detail.get('id'))!=raw_id or not detail.get('content'):
                return result('unverified','Official ATS detail identity/content could not be confirmed')
            check_url=detail.get('absolute_url') or check_url
            fields=[f for q in detail.get('questions',[]) for f in q.get('fields',[])]
            if fields:signal='Greenhouse currently publishes job-specific application fields'
            deadline=detail.get('application_deadline')
            if deadline and posting_age(deadline) is not None:
                return result('closed','Employer application deadline has passed')
        elif provider=='lever':
            detail=get_json(f'https://api.lever.co/v0/postings/{slug}/{raw_id}')
            if str(detail.get('id'))!=raw_id:return result('unverified','Official ATS posting identity unconfirmed')
            check_url=detail.get('applyUrl') or check_url
        elif provider=='workday' and job.get('detail_api'):
            detail=get_json(job['detail_api']).get('jobPostingInfo',{})
            if detail.get('canApply') is False:return result('closed','Workday explicitly disables applications')
            if detail.get('canApply') is True:signal='Workday canApply=true for this requisition'
            if not detail:return result('unverified','Workday detail unavailable')
        elif provider=='smartrecruiters':
            detail=get_json(f'https://api.smartrecruiters.com/v1/companies/{slug}/postings/{raw_id}')
            check_url=detail.get('applyUrl') or check_url
        elif provider!='ashby':return result('unverified','Unsupported ATS provider')
        parsed=urlsplit(check_url)
        known=('greenhouse.io','lever.co','ashbyhq.com','myworkdayjobs.com','smartrecruiters.com')
        # A custom domain must be supplied by the official detail response, not arbitrary input.
        declared_host=urlsplit(detail.get('absolute_url') or detail.get('applyUrl') or '').hostname
        def safe_host(host):return bool(host and (any(host==h or host.endswith('.'+h) for h in known) or host==declared_host))
        if parsed.scheme!='https' or not safe_host(parsed.hostname):return result('unverified','Employer URL authenticity cannot be established automatically')
        req=urllib.request.Request(check_url,headers={**HEADERS,'Accept':'text/html'})
        try:
            with urllib.request.urlopen(req,timeout=25) as response:
                body=response.read(1500000).decode('utf-8',errors='replace')
                final_url=getattr(response,'url',check_url)
                if not safe_host(urlsplit(final_url).hostname):return result('unverified','Application URL redirects outside official ATS/employer host')
        except urllib.error.HTTPError as e:
            # Conflicting positive ATS metadata and a dead page is uncertainty, not proof of closure.
            return result('unverified',f'Application URL HTTP {e.code}; ATS/public-page evidence conflicts or access is unavailable')
        text=plain(body)
        closed=re.search(r'this (?:job|position|posting|role) (?:is |has been )?(?:no longer available|no longer accepting applications|closed|removed|filled|expired)|job (?:has been |is )closed|job you.{0,20}looking for.{0,30}(?:no longer|not available)',text,re.I)
        if closed:return result('closed','Employer page explicitly states closure: '+closed.group(0))
        form=bool(re.search(r'<form\b',body,re.I) and re.search(r'<(?:input|textarea)\b',body,re.I) and re.search(r'resume|candidate|email|curriculum',body,re.I) and re.search(r'type=[\"\x27]submit|submit.{0,30}application|apply.{0,30}(?:job|position)',body,re.I))
        if form:signal=(signal+'; ' if signal else '')+'Public application form and applicant fields are available'
        if not signal:return result('unverified','Official listing/page is accessible, but application-enabled state or form could not be confirmed')
        if not job.get('observed_this_run') and provider not in ('greenhouse','lever','workday','smartrecruiters'):
            return result('unverified','Listing absent from collection; application state inconclusive')
        return result('active',signal+'. Application submission was not attempted; interview activity is unknown.',
                      accepting_applications=True,application_evidence=signal,application_url=check_url)
    except urllib.error.HTTPError as e:
        return result('closed' if e.code in (404,410) else 'unverified',f'Official ATS detail HTTP {e.code}')
    except (urllib.error.URLError,ValueError,OSError) as e:
        return result('unverified','Automatic employer verification unavailable: '+str(e)[:160])


def finalize_decisions(jobs,timestamp):
    """One authoritative category vocabulary for feed, Sheet and views."""
    for j in jobs:
        q=j.get('qualification_category','Hold')
        if j.get('availability_state')=='Confirmed closed':category='Closed';reason='Employer confirms closure'
        elif j.get('duplicate_state','').startswith('Exact requisition alias'):category='Duplicate';reason='Same employer requisition; retain linked application history'
        elif q=='Ineligible':category=q;reason=j.get('assessment_reason','Explicit qualification or scope incompatibility')
        elif j.get('related_ids'):category='Hold';reason='Likely repost/duplicate relationship needs a targeted history check'
        elif q=='Recommended' and j.get('accepting_applications') and j.get('availability_state')=='Verified active':category=q;reason=j.get('assessment_reason','Practical entry-level fit')
        elif q=='Stretch':category=q;reason=j.get('assessment_reason','Experience disadvantage')
        else:category='Hold';reason=j.get('assessment_reason','Full qualifications not reassessed in this collection') if q!='Recommended' else 'Application-enabled state is awaiting automatic verification'
        j['category']=category;j['decision_reason']=reason
        if category in ('Closed','Duplicate','Ineligible'):j['queue_eligible']=False
        j['decision_version']=2
    return jobs

def reconcile(previous, observed, health, timestamp):
    old = {j['id']: j for j in previous}
    merged = dict(old)
    sources = {s['source']: s for s in health}
    seen = set()
    for j in deduplicate(previous, observed):
        seen.add(j['id'])
        historical = old.get(j['id'], {})
        if not j.get('verification_result'):
            j.pop('verification_result',None);j.pop('verification_detail',None)
        prior_date = historical.get('posted_at')
        if prior_date and posting_age(prior_date) is not None and (not j.get('posted_at') or str(prior_date) < str(j['posted_at'])):
            j['employer_latest_publication'] = j.get('posted_at', '')
            j['posted_at'] = prior_date
        row = {**j, 'first_seen': historical.get('first_seen', timestamp), 'last_seen': timestamp,
               'availability': 'Seen in latest search'}
        merged[j['id']] = availability(historical, row, timestamp, True, sources.get(j['source'], {}))
    for key, j in list(merged.items()):
        if key not in seen:
            source = sources.get(j['source'], {})
            row = availability(j, {}, timestamp, False, source)
            row['availability'] = 'Not seen in latest complete search' if source.get('status') == 'ok' else 'Source incomplete / unavailable; retained'
            merged[key] = row
    return sorted(mark_related(list(merged.values())), key=lambda j: (-j['priority'], j['company'], j['id']))


def run(root=ROOT):
    prefs = json.loads((root / "config/preferences.json").read_text())
    boards = [b for b in json.loads((root / "config/boards.json").read_text()) if b.get("enabled", True)]
    output = root / "data/jobs.json"
    previous = json.loads(output.read_text()).get("jobs", []) if output.exists() else []
    timestamp = now()
    observed, health = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(collect, b): b for b in boards}
        for f in as_completed(futures):
            b = futures[f]
            try:
                raw, complete, errors = f.result()
                matching = [x for j in raw if (x := assess(j, prefs)) is not None]
                observed.extend({**j, "observed_this_run": True} for j in matching)
                state = "ok" if complete else ("partial" if raw else "failed")
                detail = "; ".join(errors)[:1500]
            except Exception as e:
                raw, matching, state, detail = [], [], "failed", f"{type(e).__name__}: {e}"
            health.append({"source": b["slug"], "full_board": b["provider"] in ("greenhouse", "ashby", "lever") and state == "ok", "company": b["company"], "status": state, "scope": "Keyword search with page/detail caps" if b["provider"] == "workday" else "Paginated board; US hardware-title prefilter" if b["provider"] == "smartrecruiters" else "Full public board", "collected": len(raw), "matched": len(matching), "checked_at": timestamp, "error": detail, "careers_url": b["careers_url"], "context": b["context"]})
            print(f"{b['company']}: {state}; {len(raw)} collected; {len(matching)} matches", flush=True)
    # Private application statuses remain in Sheets. There, the same sync performs
    # a small read-only check of the strongest unapplied records. This public pass
    # rotates checks instead of repeatedly spending the budget on fresh positives.
    observed_ids={j['id'] for j in observed}
    missing=sorted((j for j in previous if j.get('qualification_category') in ('Recommended','Stretch') and j['id'] not in observed_ids),key=lambda j:-j['priority'])[:4]
    old_by_id={j['id']:j for j in previous}
    def check_priority(j):
        old=old_by_id.get(j['id'],{})
        fresh=old.get('verification_version')==2 and old.get('accepting_applications') and hours_since(old.get('last_confirmed_active'),timestamp)<24
        return (1 if fresh else 0, {'Recommended':0,'Hold':1,'Stretch':2}.get(j['category'],3),-j['priority'],j['id'])
    candidates=sorted((j for j in observed if j.get('queue_eligible')),key=check_priority)[:max(0,prefs.get('verification_budget',40)-len(missing))]
    checks = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for checked in pool.map(verify_posting, candidates):
            checks[checked['id']] = checked
    observed = [checks.get(j['id'], j) for j in observed]
    jobs = reconcile(previous, observed, health, timestamp)
    for j in missing:
        checked = verify_posting({**j, 'observed_this_run': False})
        for i, row in enumerate(jobs):
            if row['id'] == j['id']:
                jobs[i] = availability(row, {k: checked[k] for k in ['verification_result', 'verification_detail']}, timestamp, False, {})
                break
    for j in jobs:
        j.pop('observed_this_run', None)
        j['posting_age'] = posting_age(j.get('posted_at'))
    jobs=finalize_decisions(jobs,timestamp)
    counts = {state: sum(j.get('availability_state') == state for j in jobs) for state in ['Verified active', 'Unverified', 'Stale', 'Confirmed closed']}
    counts['suspected_duplicate_records'] = sum(bool(j.get('related_ids')) for j in jobs)
    counts['exact_observations_collapsed'] = sum(j.get('exact_duplicates_collapsed', 0) for j in jobs)
    feed = {"schema_version": 1, "decision_version": 2, "generated_at": timestamp, "source_status": sorted(health, key=lambda x: x["company"]), "jobs": jobs, "availability_summary": counts, "preferences": {k: prefs[k] for k in ['shortlist_limit','shortlist_per_company','stale_after_hours','defense_target','daily_target','priority_queue_limit','verification_budget','daily_capacity','verification_max_hours','sheet_verification_budget','decision_version'] if k in prefs}, "config_hash": hashlib.sha256(json.dumps({'preferences':prefs,'boards':boards},sort_keys=True).encode()).hexdigest()}
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(output)
    with output.with_suffix(".csv").open("w", newline="") as f:
        fields = ["id", "company", "title", "location", "role_score", "location_fit", "priority", "experience", "salary", "flags", "evidence", "url", "source", "first_seen", "last_seen", "availability", "posted_at", "posting_age", "recency_points", "category", "start_eligibility", "fit_reason", "defense", "availability_state", "last_confirmed_active", "availability_checked_at", "verification_detail", "duplicate_state", "related_ids", "resume_variant", "queue_eligible", "qualification_category", "decision_reason", "application_state", "accepting_applications", "application_url", "application_evidence"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for j in jobs:
            w.writerow({k: ("'" + str(v) if isinstance(v, str) and v[:1] in "=+-@" else v) for k, v in j.items()})
    return feed


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()

