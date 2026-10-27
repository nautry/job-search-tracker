# Engineering job search tracker

Python employer collector + GitHub Actions + Google Sheets. Start with [START_HERE.md](START_HERE.md) for definitive activation steps. [CHECK_JOBS.md](CHECK_JOBS.md) defines the repeatable assistant workflow.

Initial sources: RTX, Anduril, Saronic, Skydio, Formlabs and Rocket Lab. Greenhouse and Ashby read full public boards; RTX uses Workday keyword searches with explicit page/detail limits. Source health is stored in every feed. A zero-match source is still included in coverage.

Target roles: entry-level mechanical design/CAD, mechanical test, manufacturing and electromechanical integration, with May 2027 graduation/start-date review. Larger US metros are prioritized; Midwest/Appalachian locations are deprioritized. No salary cutoff is applied. Location and experience parsing are heuristics and require posting review.

```sh
python -m unittest discover -s tests -v
node tests/test_sync.cjs
python -m src.puller
python -m src.search --company RTX
```

No Python dependencies. Daily collector schedule: 11:23 UTC. Public job feed: `data/jobs.json`. The Apps Script sync never rewrites existing manual columns A:D, never deletes application records, and validates IDs before updating. Shortlists and source-health views are derived and may be rebuilt.

## Validation

Local tests cover experience/title filtering, geographic preferences, duplicate IDs, failed-source retention, timestamps, formula escaping and application history across two actual sync-function executions with mocked Google services. These tests do not replace a first live GitHub Actions run and a Google-authorized sync.

## Sources and reference

- Greenhouse public job board API: https://docs.greenhouse.io/job-board
- Ashby public job board API: https://developers.ashbyhq.com/docs/public-job-posting-api
- RTX career site: https://careers.rtx.com/global/en
- Architecture reference: https://github.com/aramasubban/job-puller (implementation written independently; no source code copied).

No resumes, private contact details, application statuses, notes or credentials belong in this repository. Match scores are review priorities, not hiring probabilities.
