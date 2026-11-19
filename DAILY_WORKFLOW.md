# Daily application workflow

Open **Daily Dashboard** → review applications and follow-ups → choose a resume category → submit on the employer site → record completion in Jobs → continue with the refill or Priority Queue. Target 1–3 applications in 30–60 minutes.

- **Mechanical Design:** CAD, mechanisms, assemblies, drawings and prototypes.
- **Test/R&D:** experimentation, validation, instrumentation, fixtures and troubleshooting.
- **Mechatronics:** electromechanical integration, robotics, sensors and embedded hardware.

The automatic daily collector remains the single GitHub Actions workflow (`daily.yml`). The existing bound Apps Script imports that feed; there is no second collection schedule. Its existing `syncJobs` trigger is reused. The Job search menu can refresh views without another collection.

## Views and manual records

Jobs is authoritative. Existing A:D (status, applied date, follow-up, notes), stable IDs, first-seen dates and historical applications are preserved. Closed listings remain in Jobs. AI is an optional manual deferral date and is also preserved. Allowed statuses remain exactly Not Applied, Applied, Interviewing, Offer, Rejected, Not Interested, Withdrawn.

Daily Dashboard holds up to five verified application-ready roles, generally at most two per company. Valid assignments persist for the local calendar day; changes to application status, closure, stale verification or deferral remove a role and trigger refill. Priority Queue holds up to 24 opportunities, including Today assignments and a distinct Backlog. Apply, Stretch and Needs Review are clearly separated. Stretch and uncertain roles never fill the daily quota. A short queue is acceptable.

## Eligibility, dates and verification

A relevant degree, actual hardware duties, 0–1 year or explicitly equivalent project experience, and plausible 2027 graduation/start evidence are required for Apply screening. Generic Engineer I is not explicit May 2027 eligibility. Two required years without equivalence are Stretch; three or more, incompatible dates, factory/process work and internships remain outside the queue. Personal qualification and export/clearance checks remain yours.

Employer publication dates drive recency; first-seen and update times never substitute. Unknown dates get zero recency points. Old publication dates are flagged but can remain suitable when the employer's official ATS and usable application URL have been freshly checked. Verified active means current official ATS listing plus a successful employer URL check, not evidence of active interviewing. Verification becomes stale after 36 hours; unknown/access-denied links remain unverified. Explicit closed text, ATS-disabled applications or HTTP 404/410 can confirm closure. Failed, partial and keyword-scoped source collections never close a job just because it disappeared. Even complete-board absence alone remains uncertain.

URL checks have a daily budget of 40, prioritizing Apply, then Stretch, then the strongest review candidates and a few disappeared prior candidates. The dashboard excludes unverified, stale and closed records. Sources reports coverage/caps and failures, including RTX. No access-control bypass or retry on 403/429 is used.

Exact employer/requisition observations are consolidated across endpoints and locations while retaining stable IDs and aliases. Semantic matching uses employer, normalized title, location and strong description-shingle agreement. Different requisitions are never silently merged; suspected reposts remain separate and link related IDs for application-history review. Similar titles alone do not establish duplicates. All historical Sheet records are retained.

## Install the revised bound script once

Open the existing Sheet → Extensions → Apps Script. Replace **Code.gs** with the current repository `google_apps_script/Code.gs`, save, select **syncJobs**, and Run once; authorize if prompted. Reopen the Sheet for the Job search menu. Reuse the existing syncJobs trigger; do not install another scheduled writer. A repository commit alone does not deploy the bound script. Settings shows the installation/sync state; until installation the previous script can restore older views.

Check timestamps and source warnings before applying. Keep RTX offer notes and follow-up dates intact; record a written offer or deadline only when confirmed.
