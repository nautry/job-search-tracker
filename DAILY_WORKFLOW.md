# Daily job application workflow

GitHub Actions collects employer postings daily. The existing bound Apps Script imports the feed, preserves application history by stable job ID, and rebuilds Apply Next. See Settings for timestamps and Sources for coverage. RTX remains included; its Workday search can hit page or detail limits.

Spend 5–10 minutes checking the strongest roles in Apply Next. Choose 1–3 that fit in a 30–60 minute session. Match your resume to the duties:

- **Design** for CAD, mechanical assemblies, mechanisms, drawings and prototypes.
- **Test/R&D** for experimentation, validation, fixtures, instrumentation and troubleshooting.
- **Mechatronics** for electromechanical integration, controls, sensors and embedded work.

Submit on the employer site. Update the application status, date, follow-up and notes in Jobs A:D. Use Dashboard to identify due follow-ups.

Apply candidates have a relevant degree and hardware-duty signal and plausible 2027 timing. Review means something material is unclear or outside the search preferences. Stretch generally means a two-year requirement with no clear project or internship equivalence. Three or more required years, incompatible cohorts, unknown start timing, internships, and factory/process work stay out of Apply Next. Employer qualification and personal export/clearance checks still apply.

Employer publication dates drive recency. Unknown dates get zero points, and anything over 45 days is flagged for another availability check. Product-use flags do not alter scores. The queue has at most 12 roles and prefers up to two per employer. The sector target only applies among similarly qualified roles.

When installing an updated version, replace Code.gs in the existing Sheet's Extensions → Apps Script project. Save and run syncJobs once when the matching feed is current. The existing trigger uses the same function name, so reuse it.
