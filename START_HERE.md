# Activate once, then say “check for jobs”

## What is ready

The existing Google Sheet is your application tracker. This package contains the collector, editable preferences and employer list, daily GitHub workflow, bound Google sync script, and local tests. It does not create a GitHub repository, install a Google script, or authorize your account by itself.

## Step 1: Create an initialized repository

1. Sign into GitHub as `nautry`.
2. Open https://github.com/new.
3. Set repository name to `job-search-tracker`.
4. Choose Public. This version uses a public job feed. Keep resumes, application notes and credentials out of the repository.
5. Enable Add README.
6. Click Create repository.
7. Send the resulting repository URL to the assistant. The assistant can then attempt to upload the project through the connected GitHub tools. If GitHub limits repository access, enable this repository in the ChatGPT GitHub connection and send the link again.

Do not create another Sheet or use an existing coursework repository.

## Step 2: Upload the project (manual alternative)

You can skip this section if the assistant uploads it for you.

1. Download and extract this ZIP. Open the `job-search-tool` folder.
2. In your new GitHub repository, select Add file > Upload files.
3. Drag the CONTENTS of `job-search-tool` into the upload area, not the outer folder. Commit to `main`.
4. Check that `src/puller.py`, `config/preferences.json` and `google_apps_script/Code.gs` appear at those exact paths.
5. Windows/browser upload may omit the hidden `.github` directory. In GitHub choose Add file > Create new file. Enter `.github/workflows/daily.yml` as the filename. Copy the entire contents of that supplied local file, paste, and commit to `main`. If the workflow already uploaded correctly, do not create a second copy.

## Step 3: Run and verify GitHub

1. Open repository > Actions. Enable workflows if GitHub asks.
2. Select Daily employer search > Run workflow > branch main > Run workflow.
3. Open the run and wait for completion. Verify tests and collection succeeded. Review any source warnings; RTX can be partial without the whole run failing.
4. Open `data/jobs.json` and check `generated_at` is recent, `config_hash` exists, and `source_status` explains source failures or limits.
5. If the Save feed step is denied, open repository Settings > Actions > General > Workflow permissions. Select Read and write permissions, save, and rerun the workflow. Only change this if needed for this repository's feed commit.

The workflow runs daily at 11:23 UTC and when collector/configuration files change. Changes to generated data do not trigger another collector run. GitHub may delay scheduled runs. The computer can be off.

## Step 4: Connect the EXISTING Google Sheet

1. Open Engineering Job Search Tracker in your Drive.
2. Go to Settings. Set B2 to `https://raw.githubusercontent.com/nautry/job-search-tracker/main/data/jobs.json` ONLY if those are the repository name and branch you actually used. This URL is a configuration example until the repository exists. Open it separately and confirm that it displays JSON.
3. In the Sheet select Extensions > Apps Script.
4. Replace the starter `Code.gs` contents with the entire supplied `google_apps_script/Code.gs`. Save.
5. Select `syncJobs` in the function selector and click Run.
6. Complete Google's authorization prompts for your own bound script. No password or authorization token needs to be pasted into ChatGPT or GitHub. If an authorization warning blocks you, stop and share its non-secret wording; do not change your account's security settings.
7. Return to Settings in the Sheet. B4 must now contain a sync time and B5 must say Sync succeeded. A stale-feed error means Step 3 must run again first.
8. In Apps Script select `installDailyTrigger` and click Run once. The Sheet sync runs during 15:00–16:00 UTC. Do not also create a ChatGPT task that writes to the same Sheet.
9. Reload the Sheet to show the Job search menu. Refresh jobs gives an on-demand Sheet sync; Refresh shortlist rebuilds the shortlist from your current statuses.

## Step 5: Test history preservation live

1. In Jobs, note one job's ID and original status/date/notes.
2. Temporarily set Status to Applied and enter a test note.
3. Run Job search > Refresh jobs.
4. Confirm there is one row for that ID and the Applied status and test note remain. Confirm Dashboard counts changed.
5. Restore the original status/date/notes. This test is not a real application.

## Daily use

Open this project and say **Check for jobs**. The assistant should follow `CHECK_JOBS.md`: inspect the current configuration and feed, identify new suitable jobs, check the actual employer postings, and preserve your application history. If the feed or Sheet is stale, report and resolve the stale stage before presenting it as a fresh search.

You can also open Apply Next directly. Click a job, apply on the employer site, then update Jobs A:D. This tool does not submit applications.

## Change preferences later

Tell the assistant what changed. `config/preferences.json` is authoritative for role patterns, skills, locations, experience limits, salary policy and shortlist size. `config/boards.json` owns employer coverage. Keep settings private if they contain sensitive details; public config should contain only search criteria you are comfortable publishing.

An employer can be disabled with `enabled: false` in boards.json. A supported platform generally needs only a new verified board entry. A new platform still needs an adapter and tests. Changing a preference file triggers collection automatically after deployment; no Sheet rebuild or script reauthorization is needed for ordinary criteria changes.

Salary floor handling remains review-only in this release. A strict salary filter needs reliable currency/pay-period normalization first. Unknown salaries are retained. Settings in the Sheet describe the search; editing its descriptive text does not change the Python collector.
