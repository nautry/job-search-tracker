# Daily application routine

The scheduled collector and Sheet sync perform discovery automatically. Repeating scraping requests does not improve an unchanged feed. Open this project and say:

> Check today's tracker against my current resume and preferences. Verify the top employer postings, remove already-applied roles from consideration, and recommend up to 15 applications. Explain required experience, May 2027 start eligibility, salary and location uncertainty. Prioritize realistic mechanical/product hardware/test roles and include a few credible stretches. Do not submit applications.

1. Check Settings B5 and Sources; resolve stale feeds or report partial sources before calling coverage complete.
2. Review Apply Next. It shows up to 15 not-applied, currently seen jobs, at most two per employer. It refreshes as statuses change; it is not a fixed daily batch.
3. Spend 5-10 minutes screening the top rows. Open the employer posting and check required experience, degree/start date, city, work authorization and whether duties are hardware-related.
4. Pick 3-5 strong fits first. Tailor the most relevant resume bullets truthfully; use enclosure design, roulette electronics integration and instrumentation evidence where appropriate.
5. Submit on the employer site. Immediately record Applied, application date, follow-up date and useful notes in Jobs A:D. Set unsuitable postings to Not Interested so they leave the queue.
6. Continue only if useful roles and time remain, up to 15 applications total. Because the shortlist refills after status changes, count actual submissions yourself in the Dashboard/by applied date.
7. Review follow-ups and recruiter/interview preparation. A 30-60 minute session may yield 2-4 careful applications; 15 tailored applications can require much longer.

Ranking uses 85% of role-fit score, half the location adjustment, and 80% of the bounded 0-10 posting-freshness bonus. Scores are not hiring probabilities. Salary is shown for manual comparison; unknown pay is retained and salary-band upper endpoints do not establish likely entry-level pay. First-seen dates never substitute for employer publication dates. All filters remain configurable; employer quality is assessed by actual role, not company prestige.

For an immediate fresh collection, GitHub Actions > Daily employer search > Run workflow, then Sheet > Job search > Refresh jobs after successful completion. Otherwise the scheduled daily runs are sufficient. Config changes deploy through GitHub; ordinary preference/source updates do not require replacing Apps Script. Current supported provider adapters: Greenhouse, Ashby, Lever and scoped Workday. Sources marked ok can still be keyword-scoped.
