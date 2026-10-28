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
    chunks = re.split(r"(?<=[.!?;])\s+|[\n\r]", text)
    minimums = []
    for chunk in chunks:
        if re.search(r"preferred|desirable|nice.to.have|master|ph\.?d|doctor", chunk, re.I):
            continue
        for m in re.finditer(r"\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*years?\s+(?:of\s+)?(?:relevant\s+|professional\s+|related\s+|engineering\s+|industry\s+|work\s+)?experience", chunk, re.I):
            minimums.append(int(m.group(1)))
    return min(minimums) if minimums else None


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
    if re.search(r"\b(intern|internship|co.op|contractor|technician)\b", title, re.I):
        return None
    if job.get("employment_type", "").lower() in {"intern", "internship", "contract", "parttime", "part-time"}:
        return None
    if NON_US.search(loc) and not re.search(r"united states|\busa\b", loc, re.I):
        return None
    if re.search(r"quality engineer", title, re.I) and not (re.search(r"mechanical engineering", desc, re.I) and re.search(r"hardware|physical|manufactur|device", desc, re.I)):
        return None
    years = experience(title + '\n' + desc)
    if years is not None and years > prefs.get("max_required_years", 3):
        return None
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
    if years == 3:
        score = min(score, 65)
    flags = []
    flags.append("May 2027 start / degree eligibility: review")
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
    # Fit dominates; employer publication date supplies a bounded freshness bonus.
    freshness = 0
    published = job.get("posted_at", "")
    if published:
        try:
            age = max(0, (datetime.now(timezone.utc)-datetime.fromisoformat(published.replace("Z", "+00:00"))).days)
            freshness = 10 if age <= 3 else 7 if age <= 7 else 4 if age <= 14 else 2 if age <= 30 else 0
            evidence.append(f"Employer posting age: {age} days; freshness +{freshness}")
        except (ValueError, TypeError):
            flags.append("Posting date unavailable; freshness not scored")
    else:
        flags.append("Posting date unavailable; first seen is not posting date")
    weights = prefs.get("ranking_weights", {"fit": 0.85, "location": 0.5, "freshness": 0.8})
    priority = round(score * weights["fit"] + bonus * weights["location"] + freshness * weights["freshness"], 1)
    return {k: v for k, v in {**job, "role_score": score, "priority": max(0, min(100, priority)), "location_fit": geo, "experience": f"{years}+ years (parsed)" if years is not None else "Review posting", "salary": salary, "flags": "; ".join(flags), "evidence": "; ".join(evidence)}.items() if k != "description"}


def canonical(board, raw_id, title, location, url, description, **extra):
    if not re.match(r"https://", url or ""):
        raise ValueError("Missing HTTPS posting URL")
    return {"id": f"{board['provider']}:{board['slug']}:{raw_id}", "source": board["slug"], "company": board["company"], "title": title, "location": location or "Location not supplied", "url": url, "description": plain(description), **extra}


def collect(board):
    provider, slug = board["provider"], board["slug"]
    jobs, errors = [], []
    if provider == "greenhouse":
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        if not isinstance(data.get("jobs"), list):
            raise ValueError("Unexpected Greenhouse schema")
        for j in data["jobs"]:
            jobs.append(canonical(board, j["id"], j["title"], j.get("location", {}).get("name", ""), j["absolute_url"], j.get("content", ""), posted_at=j.get("first_published", "")))
        return jobs, True, errors
    if provider == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
        if not isinstance(data.get("jobs"), list):
            raise ValueError("Unexpected Ashby schema")
        for j in data["jobs"]:
            if j.get("isListed", True):
                jobs.append(canonical(board, j["id"], j["title"], j.get("location", ""), j.get("jobUrl") or j.get("applyUrl"), j.get("descriptionPlain") or j.get("descriptionHtml", ""), employment_type=j.get("employmentType", ""), posted_at=j.get("publishedAt", "")))
        return jobs, True, errors
    if provider == "lever":
        data = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if not isinstance(data, list):
            raise ValueError("Unexpected Lever schema")
        for j in data:
            desc = j.get("descriptionPlain", "") + "\n" + "\n".join(x.get("text", "") + " " + plain(x.get("content", "")) for x in j.get("lists", []))
            jobs.append(canonical(board, j["id"], j["text"], j.get("categories", {}).get("location", ""), j["hostedUrl"], desc, employment_type=j.get("categories", {}).get("commitment", ""), posted_at=datetime.fromtimestamp(j["createdAt"]/1000, timezone.utc).isoformat() if j.get("createdAt") else ""))
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
                    if (ROLE.search(j["title"]) or re.search(r"product development|design verification|mechanisms? engineer|integration engineer", j["title"], re.I)) and not SENIOR.search(j["title"]):
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
            jobs.append(canonical(board, d.get("jobReqId") or path.rsplit("_", 1)[-1], d.get("title", j["title"]), d.get("location", j.get("locationsText", "")), f"https://{board['host']}/en-US/{board['site']}{path}", d.get("jobDescription", ""), employment_type=d.get("timeType", "")))
            time.sleep(0.2)
        except (urllib.error.URLError, ValueError, KeyError) as e:
            complete = False
            errors.append(f"Detail: {e}")
            if isinstance(e, urllib.error.HTTPError) and e.code in (403, 429):
                break
    return jobs, complete, errors


def reconcile(previous, observed, health, timestamp):
    old = {j["id"]: j for j in previous}
    merged = dict(old)
    states = {s["source"]: s["status"] for s in health}
    seen = set()
    for j in observed:
        seen.add(j["id"])
        merged[j["id"]] = {**j, "first_seen": old.get(j["id"], {}).get("first_seen", timestamp), "last_seen": timestamp, "availability": "Seen in latest search"}
    for key, j in list(merged.items()):
        if key not in seen:
            merged[key] = {**j, "availability": "Not seen in latest complete search" if states.get(j["source"]) == "ok" else "Source incomplete / unavailable; retained"}
    return sorted(merged.values(), key=lambda j: (-j["priority"], j["company"], j["id"]))


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
                observed.extend(matching)
                state = "ok" if complete else ("partial" if raw else "failed")
                detail = "; ".join(errors)[:1500]
            except Exception as e:
                raw, matching, state, detail = [], [], "failed", f"{type(e).__name__}: {e}"
            health.append({"source": b["slug"], "company": b["company"], "status": state, "scope": "Keyword search with page/detail caps" if b["provider"] == "workday" else "Paginated board; US hardware-title prefilter" if b["provider"] == "smartrecruiters" else "Full public board", "collected": len(raw), "matched": len(matching), "checked_at": timestamp, "error": detail, "careers_url": b["careers_url"], "context": b["context"]})
            print(f"{b['company']}: {state}; {len(raw)} collected; {len(matching)} matches", flush=True)
    jobs = reconcile(previous, observed, health, timestamp)
    feed = {"schema_version": 1, "generated_at": timestamp, "source_status": sorted(health, key=lambda x: x["company"]), "jobs": jobs, "preferences": {k: prefs[k] for k in ['shortlist_limit','shortlist_per_company','stale_after_hours'] if k in prefs}, "config_hash": hashlib.sha256(json.dumps({'preferences':prefs,'boards':boards},sort_keys=True).encode()).hexdigest()}
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(output)
    with output.with_suffix(".csv").open("w", newline="") as f:
        fields = ["id", "company", "title", "location", "role_score", "location_fit", "priority", "experience", "salary", "flags", "evidence", "url", "source", "first_seen", "last_seen", "availability"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for j in jobs:
            w.writerow({k: ("'" + str(v) if isinstance(v, str) and v[:1] in "=+-@" else v) for k, v in j.items()})
    return feed


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
