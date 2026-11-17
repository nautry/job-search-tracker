"""Conservative application screening using employer text."""
from datetime import datetime, timezone
import re

EXCLUDED_DUTIES = re.compile(
    r"\b(?:manufacturing|production|process|industrial|tooling|factory automation|"
    r"supplier development|equipment|quality)\s+(?:\w+\s+)?engineer\b|\btooling\b", re.I
)
HARDWARE_DUTIES = re.compile(
    r"\b(?:CAD|SolidWorks|Creo|CATIA|autodesk|mechanisms?|mechanical design|"
    r"machine design|mechanical testing|hardware test|test fixtures?|electromechanical|"
    r"mechatronics?|engineering drawings|prototypes?|structural analysis|GD&T)\b", re.I
)
DEGREE = re.compile(r"mechanical engineering|aerospace engineering|mechatronics|engineering or related|engineering discipline", re.I)
ENTRY_TITLE = re.compile(r"\b(?:new.grad(?:uate)?|entry.level|early.career|university.grad|recent graduate)\b", re.I)
PROJECT_EQUIVALENCE = re.compile(
    r"(?:internships?|co.ops?|(?:academic|course|student|design|relevant) projects?|coursework)"
    r".{0,110}(?:count|qualif|acceptable|consider|equival|included)|"
    r"(?:accept|include|count|qualif|equival).{0,90}(?:internships?|co.ops?|academic projects?|coursework)",
    re.I,
)


def posting_age(published, now=None):
    try:
        value = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    age = ((now or datetime.now(timezone.utc)) - value).days
    return age if age >= 0 else None


def recency_points(age):
    if age is None:
        return 0
    return next((points for cutoff, points in [(3, 10), (7, 7), (14, 4), (30, 2)] if age <= cutoff), 0)


def assess_eligibility(job, prefs, years, location_fit):
    title, desc = job["title"], job.get("description", "")
    combined = title + "\n" + desc
    target = prefs.get("graduation", "2027-05")
    year = target[:4]
    past_cohort = re.search(r"\b(20\d{2})\s+(?:early.career|new.grad|grad(?:uate)?)\b", title, re.I)
    earlier_label = re.search(r"\b(?:grad(?:uate)?|early.career).{0,15}\b(20\d{2})\b|\b(20\d{2})\s+(?:new )?grad", title, re.I)
    earlier_year = next((int(x) for x in earlier_label.groups() if x), int(year)) if earlier_label else int(year)
    too_early = (
        earlier_year < int(year) and year not in title
        or
        past_cohort and int(past_cohort[1]) < int(year) and year not in title
        or re.search(rf"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|Winter)\s+{year}\b", combined, re.I)
        or re.search(r"\b(?:immediate start|start immediately)\b", combined, re.I)
    )
    exact_start = re.search(rf"\b(?:May|June|Jun)\s+{year}\b", combined, re.I)
    seasonal_start = re.search(rf"\b(?:summer|fall|autumn|July|August|September)\s+{year}\b", combined, re.I)
    graduate_cohort = re.search(rf"{year}\s+(?:early.career|new.grad|grad)|graduat\w*.{{0,55}}{year}", combined, re.I)
    if too_early:
        start = "Start eligibility conflict"
    elif exact_start:
        start = f"May/June {year} mentioned; confirm start"
    elif seasonal_start:
        start = f"Summer/fall {year} mentioned; confirm start"
    elif graduate_cohort:
        start = f"{year} cohort; exact start to confirm"
    else:
        start = "Start timing unverified"

    employment = job.get("employment_type", "")
    nonfull = re.search(r"\b(?:intern(?:ship)?|co.op|contract(?:or)?|part.time|temporary|fixed.term)\b", title + " " + employment, re.I)
    nonfull = nonfull or re.search(r"\b(?:temporary|fixed.term) (?:role|position|program)\b", desc, re.I)
    nonfull = nonfull or ("associate" in title.lower() and re.search(r"\b(?:12|twelve)[ -]weeks?\b", desc, re.I))
    active_clearance = re.search(r"\b(?:active|current|existing)\s+(?:u\.?s\.?\s+)?(?:secret |top secret |ts/sci |security )?clearance\s+(?:is\s+)?required\b|\b(?:must possess|must hold|requires? an?)\b.{0,30}\b(?:active|current|existing)\b.{0,30}\bclearance\b", desc, re.I)
    work_auth = re.search(r"\b(?:citizen(?:ship)?|u\.?s\.? person|itar|export.controll?ed|work authori[sz]ation|sponsorship|clearance)\b", desc, re.I)
    graduate_degree = re.search(r"\b(?:master.s|ph\.?d\.?)\b.{0,45}\brequired\b", desc, re.I)
    # Equivalence must be linked to the required experience clause.
    equivalent = any(PROJECT_EQUIVALENCE.search(line) for line in desc.splitlines()
                     if re.search(r"\byears?\b.*\bexperience\b", line, re.I))
    matches = HARDWARE_DUTIES.findall(desc)
    reason = "Hardware evidence: " + ", ".join(dict.fromkeys(m.lower() for m in matches[:12])) if matches else "Mechanical duties need review"
    reason = reason[:140]
    flags = []
    category = "Apply"
    if too_early or nonfull or graduate_degree or active_clearance:
        category = "Review"
        flags.append(start if too_early else "Employment type, required degree or active clearance needs review")
    elif EXCLUDED_DUTIES.search(title) or not matches or not DEGREE.search(desc):
        category = "Review"
        flags.append("Role duties or eligible degree need review")
    elif location_fit.startswith(("Deprioritized", "Location review")):
        category = "Review"
    elif years is not None and (years >= 3 or years > prefs.get("max_required_years", 3)):
        category = "Review"
        flags.append(f"Requires {years}+ years; outside main queue")
    elif years == 2 and not equivalent:
        category = "Stretch"
        flags.append("Two years required; project equivalence unconfirmed")
    elif not (exact_start or seasonal_start or graduate_cohort):
        category = "Review"
        flags.append("May 2027 start compatibility unverified")
    elif years is None and not (ENTRY_TITLE.search(title) or graduate_cohort):
        category = "Review"
        flags.append("Required experience unverified")
    if equivalent:
        flags.append("Posting explicitly accepts project/internship experience")
    if work_auth:
        start += " | Verify export/clearance terms"
        flags.append("Check work authorization, export and clearance eligibility before submitting")
    return {
        "category": category, "start_eligibility": start, "fit_reason": reason,
        "defense": job.get("use_case_sector") == "defense_review" or bool(re.search(r"\bStarshield\b", title, re.I)),
        "eligibility_flags": flags,
    }
