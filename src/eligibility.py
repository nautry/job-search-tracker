"""Evidence-based screening. Missing timing is a caveat, never proof of incompatibility."""
from datetime import datetime, timezone
import re

EXCLUDED_DUTIES = re.compile(r'\b(?:manufacturing|production|process|industrial|tooling|factory automation|supplier development|equipment|quality)\s+(?:\w+\s+)?engineer(?:ing)?\b|\b(?:tooling|factory automation|production automation|sourcing|procurement|construction|welding|facilities|HVAC|technician|field service)\b|engineer,\s*automation\b', re.I)
HARDWARE_DUTIES = re.compile(r'\b(?:CAD|SolidWorks|Creo|CATIA|autodesk|mechanisms?|mechanical design|machine design|mechanical testing|hardware test|test fixtures?|electromechanical|mechatronics?|engineering drawings|prototypes?|structural analysis|GD&T|flight.test|data acquisition|environmental testing|electrical integration)\b', re.I)
DEGREE = re.compile(r'mechanical|aerospace|mechatronics|engineering (?:or related|discipline|field)|related engineering', re.I)
ENTRY_TITLE = re.compile(r'\b(?:new.grad(?:uate)?|entry.level|early.career|university.grad|recent graduate|engineer\s+i|associate\s+(?:mechanical\s+)?engineer)\b', re.I)
PROJECT_EQUIVALENCE = re.compile(r'(?:internships?|co.ops?|(?:academic|course|student|design|relevant) projects?|coursework).{0,110}(?:count|qualif|acceptable|consider|equival|included)|(?:accept|include|count|qualif|equival).{0,90}(?:internships?|co.ops?|academic projects?|coursework)',re.I)
BACHELOR = re.compile(r"bachelor|\bB\.?S\.?\b|\bBSc\b|undergraduate",re.I)


def posting_age(published, now=None):
    try:
        value=datetime.fromisoformat(str(published).replace('Z','+00:00'))
        if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):return None
    age=((now or datetime.now(timezone.utc))-value).days
    return age if age>=0 else None


def recency_points(age):
    return 0 if age is None else next((p for c,p in [(3,10),(7,7),(14,4),(30,2)] if age<=c),0)


def assess_eligibility(job,prefs,years,location_fit):
    title,desc=job['title'],job.get('description','')
    text=re.sub(r'\s+',' ',title+' '+desc)
    year=prefs.get('graduation','2027-05')[:4]
    flags=[];caveats=[];blockers=[]
    cohort=re.search(r'\b(20\d{2})\s+(?:new.grad|grad(?:uate)?|early.career)|(?:new.grad|grad(?:uate)?|early.career).{0,15}\b(20\d{2})\b',title,re.I)
    old_cohort=cohort and int(next(v for v in cohort.groups() if v))<int(year) and year not in title
    early_date=re.search(rf'(?:start|begin|join|available|commence|graduat\w*|complete).{{0,65}}\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|Winter)\s+{year}\b',text,re.I)
    immediate=re.search(r'(?:must|expected|required|able|available).{0,45}(?:start|join|begin).{0,35}(?:immediately|within\s+(?:30|60|90|one|two|three).{0,12}(?:days?|months?))|\bimmediate (?:start|openings)\b|\bstart immediately\b',text,re.I)
    old_degree=re.search(r'graduat\w*.{0,45}(?:by|before|in).{0,20}(?:202[0-6])\b',text,re.I)
    too_early=bool(old_cohort or early_date or immediate or (old_degree and year not in text))
    if too_early:
        start='Explicit start / graduation conflict'
        blockers.append('Posting explicitly conflicts with May 2027 graduation')
    elif re.search(rf'(?:start|begin|join).{{0,30}}(?:May|June|summer|fall|July|August|September)\s+{year}',text,re.I):
        start='2027 post-graduation start wording present; exact arrangement not guaranteed'
    elif re.search(rf'\b{year}\b',title) or re.search(rf'graduat\w*.{{0,65}}{year}',text,re.I):
        start='2027 graduation/cohort evidence; exact start not stated'
        caveats.append('Exact start date not stated')
    else:
        start='May 2027 timing unconfirmed; no explicit conflict found'
        caveats.append('May 2027 start timing unconfirmed')
    employment=title+' '+job.get('employment_type','')
    nonfull=bool(re.search(r'\b(?:intern(?:ship)?|co.op|contract(?:or)?|part.time|temporary|fixed.term)\b',employment,re.I) or re.search(r'\b(?:temporary|fixed.term) (?:role|position|program)\b',desc,re.I) or ('associate' in title.lower() and re.search(r'\b(?:12|twelve)[ -]weeks?\b',desc,re.I)))
    if nonfull:blockers.append('Internship / temporary / non-full-time position')
    matches=list(dict.fromkeys(m.lower() for m in HARDWARE_DUTIES.findall(desc)))
    scope=not EXCLUDED_DUTIES.search(title) and bool(matches)
    if not scope:blockers.append('Duties outside preferred mechanical design / development / hardware test scope')
    preferred_location=not location_fit.startswith(('Deprioritized','Location review'))
    if not preferred_location:blockers.append('Location outside the selected metro preferences or unresolved')
    # Interpret requirement wording across the full available description, not title alone.
    degree_lines=[line for line in desc.splitlines() if re.search(r'degree|bachelor|\bB\.?S\.?\b|master|PhD',line,re.I)]
    degree_text=' '.join(degree_lines)
    bachelor=bool(BACHELOR.search(degree_text))
    compatible=bool(DEGREE.search(degree_text))
    explicit_other=bool(bachelor and re.search(r'electrical engineering|computer (?:science|engineering)|software engineering',degree_text,re.I) and not compatible)
    grad_only=bool(not bachelor and re.search(r'(?:master.?s|Ph\.?D\.?).{0,45}(?:required|minimum)|(?:requires?|must have).{0,45}(?:master.?s|Ph\.?D\.?)',degree_text,re.I))
    if explicit_other or grad_only:blockers.append('Explicit required degree is outside the applicant BS mechanical background')
    degree_status='Compatible bachelor / engineering discipline stated' if bachelor and compatible else 'Degree wording incomplete; no incompatible requirement identified'
    if not (bachelor and compatible):caveats.append(degree_status)
    specialist=bool(re.search(r'\b(?:software|firmware|RF|PCB|FPGA)\b',title,re.I) and not re.search(r'mechanical|mechatronic|electromechanical',title,re.I))
    if specialist:blockers.append('Electrical / software specialist role rather than mechanical hardware')
    active_clearance=bool(re.search(r'\b(?:active|current|existing)\s+(?:u\.?s\.?\s+)?(?:secret |top secret |ts/sci |security )?clearance\s+(?:is\s+)?required\b|(?:must possess|must hold|requires? an?).{0,30}(?:active|current|existing).{0,30}clearance',desc,re.I))
    if active_clearance:flags.append('Current clearance required; applicant possession is unconfirmed')
    work_auth=bool(re.search(r'citizen|u\.?s\.? person|ITAR|export.control|work authori[sz]ation|sponsorship|clearance',desc,re.I))
    if work_auth:caveats.append('Personal export / citizenship / clearance eligibility not verified')
    equivalent=any(PROJECT_EQUIVALENCE.search(line) for line in desc.splitlines() if re.search(r'\byears?\b.*\bexperience\b',line,re.I))
    explicit_entry=bool(ENTRY_TITLE.search(title) or re.search(r'no (?:prior )?(?:professional )?experience required|0\s*[-–to]+\s*1\s*years?|recent graduate|entry.level',desc,re.I))
    if years is not None and (years>=3 or years>prefs.get('max_required_years',3)):blockers.append(f'{years}+ required years exceeds realistic entry-level scope')
    if blockers:category='Ineligible';reason=blockers[0]
    elif active_clearance:category='Hold';reason=flags[0]
    elif years==2 and not equivalent:category='Stretch';reason='Two required years; educational/project equivalence not established'
    elif years is None and not explicit_entry:category='Hold';reason='Experience level is materially ambiguous; automatic requirement check pending'
    else:category='Recommended';reason='Relevant mechanical duties with realistic early-career requirements; no explicit incompatibility found'
    if equivalent:flags.append('Employer explicitly includes project/internship experience')
    evidence='Hardware: '+', '.join(matches[:6]) if matches else 'Hardware duty evidence absent'
    flags.extend(blockers+caveats)
    return {'category':category,'qualification_category':category,'start_eligibility':start,
            'fit_reason':(evidence+'; '+reason)[:240], 'assessment_reason':reason,
            'caveats':caveats,'screening_evidence':{'required_years':years,'projects_accepted':equivalent,'degree':degree_status,'entry_signal':explicit_entry,'current_clearance_required':active_clearance,'full_time_conflict':nonfull,'timing_conflict':too_early,'hardware_terms':matches[:8]},
            'queue_eligible':category in ('Recommended','Stretch','Hold') and scope and preferred_location,
            'defense':job.get('use_case_sector')=='defense_review' or bool(re.search(r'\bStarshield\b',title,re.I)), 'eligibility_flags':flags}
