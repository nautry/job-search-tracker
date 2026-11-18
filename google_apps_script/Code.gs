/** @OnlyCurrentDoc */
/* Bound to your tracker: Extensions > Apps Script. No credentials in source. */
const HEADERS = ['Status','Applied date','Follow-up','Notes','Company','Job title','Location','Role fit','Location fit','Priority','Experience','Salary','Flags','Why match','Link','Job ID','Availability','First seen','Last seen','Source','Employer posted','Posting age (days)','Recency points','Recommendation','May 2027 eligibility','Fit reason'];
const STATUSES = ['Not Applied','Applied','Interviewing','Offer','Rejected','Not Interested','Withdrawn'];
const QUEUE_HEADERS = ['Recommendation','Company','Job title','Location','Employer posted','Experience','May 2027 eligibility','Priority','Why it fits','Jobs row'];
const SOURCE_HEADERS = ['Company','Status','Collected','Matched','Checked at','Scope','Error','Careers URL','Context'];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Job search').addItem('Refresh jobs','syncJobs').addItem('Refresh shortlist','refreshViews').addItem('Set up daily refresh','installDailyTrigger').addToUi();
}

function onEdit(e) {
  if (!e || e.range.getSheet().getName() !== 'Jobs' || e.range.getColumn() > 4 || e.range.getLastRow() < 2) return;
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(500)) return;
  try { refreshViews(); } finally { lock.releaseLock(); }
}

function textCell(value) {
  if (typeof value === 'number' || value instanceof Date) return value;
  const s = value == null ? '' : String(value);
  return /^[=+@\-]/.test(s) ? "'" + s : s;
}

function autoFields(j) {
  if (!/^https:\/\//i.test(j.url)) throw new Error('Invalid job link: ' + j.id);
  const title = String(j.title).replace(/"/g,'""');
  const url = String(j.url).replace(/"/g,'""');
  return [textCell(j.company), '=HYPERLINK("'+url+'","'+title+'")', textCell(j.location), Number(j.role_score), textCell(j.location_fit), Number(j.priority), textCell(j.experience), textCell(j.salary), textCell(j.flags), textCell(j.evidence), j.url, textCell(j.id), textCell(j.availability), j.first_seen ? new Date(j.first_seen) : '', j.last_seen ? new Date(j.last_seen) : '', textCell(j.source),
    postingDate(j.posted_at), j.posting_age ?? 'Unknown', Number(j.recency_points || 0),
    ['Apply','Stretch'].includes(j.category) ? j.category : 'Review',
    textCell(j.start_eligibility || 'Start timing unverified'),
    textCell(j.fit_reason || 'Employer requirements need review')];
}

function postingDate(value) {
  const ms = Date.parse(value || '');
  return Number.isFinite(ms) && ms <= Date.now() ? new Date(ms) : '';
}

function validateFeed(feed) {
  if (feed.schema_version !== 1 || !Array.isArray(feed.jobs) || !Array.isArray(feed.source_status) || !Number.isFinite(Date.parse(feed.generated_at))) throw new Error('Feed schema is invalid');
  const ids = new Set();
  feed.jobs.forEach(j => {
    if (!j.id || ids.has(j.id) || !j.title || !/^https:\/\//.test(j.url) || !Number.isFinite(j.role_score) || !Number.isFinite(j.priority)) throw new Error('Invalid or duplicate job: '+j.id);
    ids.add(j.id);
  });
  if (feed.jobs.length > 20000) throw new Error('Feed exceeds supported 20,000 jobs');
}

function indexRows(rows) {
  const index = new Map();
  rows.forEach((r,i) => {
    const id = String(r[15] || '');
    if (id && index.has(id)) throw new Error('Duplicate Sheet job ID: '+id+'. Resolve before sync.');
    if (id) index.set(id,i+2);
  });
  return index;
}

function syncJobs() {
  const lock = LockService.getDocumentLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const cfg = ss.getSheetByName('Settings');
    const feedUrl = String(cfg.getRange('B2').getValue()).trim();
    if (!/^https:\/\/raw\.githubusercontent\.com\//.test(feedUrl)) throw new Error('Set Settings!B2 to your raw GitHub data/jobs.json URL.');
    const response = UrlFetchApp.fetch(feedUrl,{muteHttpExceptions:true});
    if (response.getResponseCode() !== 200) throw new Error('Feed HTTP '+response.getResponseCode()+'. Existing jobs were preserved.');
    const feed = JSON.parse(response.getContentText());
    validateFeed(feed);
    const maxAge = Number(feed.preferences && feed.preferences.stale_after_hours) || 36;
    if (Date.now()-Date.parse(feed.generated_at)>maxAge*3600000) throw new Error('Feed is stale. Run the GitHub collector first. Existing jobs were preserved.');
    const sh = ss.getSheetByName('Jobs');
    const existing = sh.getRange(1, 1, 1, HEADERS.length).getValues()[0];
    if (existing.some((value, i) => i < 20 ? value !== HEADERS[i] : value && value !== HEADERS[i])) {
      throw new Error('Unexpected Jobs headers. Restore the expected headers before sync.');
    }
    sh.getRange(1, 21, 1, HEADERS.length - 20).setValues([HEADERS.slice(20)]);
    const lastExisting = sh.getLastRow();
    const rows = lastExisting > 1 ? sh.getRange(2, 1, lastExisting - 1, HEADERS.length).getValues() : [];
    const index = indexRows(rows);
    const newJobs = feed.jobs.filter(j => !index.has(j.id));
    const last = Math.max(2, lastExisting + newJobs.length);
    if (last > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), last - sh.getMaxRows());
    const byId = new Map(feed.jobs.map(j => [j.id, j]));
    const states = new Map(feed.source_status.map(source => [source.source, source.status]));

    // Batch contiguous automated writes. Keep historical first-seen and all A:D values.
    let start = 0;
    let batch = [];
    const flush = () => {
      if (batch.length) sh.getRange(start, 5, batch.length, HEADERS.length - 4).setValues(batch);
      batch = [];
    };
    rows.forEach((row, i) => {
      const j = byId.get(String(row[15]));
      if (!j) {
        flush();
        if (row[15]) {
          sh.getRange(i + 2, 17).setValue(states.get(String(row[19])) === 'ok'
            ? 'Not seen in latest complete search' : 'Source incomplete / unavailable; retained');
          sh.getRange(i + 2, 24).setValue('Review');
        }
        return;
      }
      if (!batch.length) start = i + 2;
      const fields = autoFields(j);
      if (row[17] !== '') fields[13] = row[17];
      batch.push(fields);
    });
    flush();
    if (newJobs.length) {
      sh.getRange(lastExisting + 1, 1, newJobs.length, HEADERS.length)
        .setValues(newJobs.map(j => ['Not Applied', '', '', '', ...autoFields(j)]));
    }
    sh.getRange(2,1,last-1,1).setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(STATUSES,true).setAllowInvalid(false).build());
    sh.getRange(2,2,last-1,2).setNumberFormat('mm/dd/yy');
    sh.getRange(2,18,last-1,2).setNumberFormat('mm/dd/yy');
    sh.getRange(2,21,last-1,1).setNumberFormat('mmm d, yyyy');
    const values = feed.source_status.map(s=>[s.company,s.status,s.collected,s.matched,new Date(s.checked_at),s.scope,s.error || '',s.careers_url,s.context]);
    writeSourceStatus(ss, values);
    cfg.getRange('B3').setValue(new Date(feed.generated_at));
    cfg.getRange('B4').setValue(new Date());
    cfg.getRange('B5').setValue('Sync succeeded; '+feed.jobs.length+' feed jobs; '+feed.source_status.filter(s=>s.status!=='ok').length+' sources need review');
    PropertiesService.getDocumentProperties().setProperty('shortlistLimit', String(Number(feed.preferences && feed.preferences.shortlist_limit)||12));
    PropertiesService.getDocumentProperties().setProperty('shortlistPerCompany', String(Number(feed.preferences && feed.preferences.shortlist_per_company)||2));
    PropertiesService.getDocumentProperties().setProperty('defenseTarget', String(Number(feed.preferences && feed.preferences.defense_target)||0.725));
    PropertiesService.getDocumentProperties().setProperty('defenseIds', JSON.stringify(feed.jobs.filter(j => j.defense).map(j => j.id)));
    refreshViews();
  } catch(e) {
    SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Settings').getRange('B5').setValue('Sync failed: '+e.message);
    throw e;
  } finally { lock.releaseLock(); }
}

function writeSourceStatus(ss, values) {
  let sources = ss.getSheetByName('Sources');
  const writeRows = sheet => {
    const previousLast = sheet.getLastRow();
    if (values.length) sheet.getRange(2,1,values.length,9).setValues(values.map(r=>r.map(textCell)));
    if (previousLast > values.length + 1) sheet.getRange(values.length + 2,1,previousLast-values.length-1,9).clearContent();
    if (values.length) sheet.getRange(2,5,values.length,1).setNumberFormat('yyyy-mm-dd hh:mm');
  };
  if (!sources) {
    sources = ss.insertSheet('Sources');
    sources.getRange(1,1,1,SOURCE_HEADERS.length).setValues([SOURCE_HEADERS]);
    sources.setFrozenRows(1);
    writeRows(sources);
    return;
  }
  try {
    writeRows(sources);
  } catch (e) {
    // Google Sheets Tables with typed columns reject Apps Script cell clears.
    // Keep the generated report intact in an archive tab and replace it with a
    // plain grid that Apps Script can refresh on future runs.
    if (!/typed columns/i.test(String(e && e.message))) throw e;
    if (sources) {
      let archiveName = 'Sources Archive';
      let suffix = 2;
      while (ss.getSheetByName(archiveName)) archiveName = 'Sources Archive ' + suffix++;
      sources.setName(archiveName);
    }
    sources = ss.insertSheet('Sources');
    sources.getRange(1,1,1,SOURCE_HEADERS.length).setValues([SOURCE_HEADERS]);
    sources.setFrozenRows(1);
    writeRows(sources);
  }
}

function shortlist(rows, limit=12, perCompany=2, defenseIds=new Set(), defenseTarget=0.725) {
  limit = Math.min(12, Math.max(0, limit));
  const candidates = rows.filter(r => r[15] && r[0] === 'Not Applied' && r[23] === 'Apply' &&
    r[16] === 'Seen in latest search' && !/Deprioritized|Location review/.test(r[8]))
    .sort((a, b) => b[9] - a[9] || String(a[15]).localeCompare(String(b[15])));
  const selected = [];
  const counts = new Map();
  function add(row) {
    const n = counts.get(row[4]) || 0;
    if (selected.length >= limit || selected.includes(row) || n >= perCompany) return false;
    selected.push(row);
    counts.set(row[4], n + 1);
    return true;
  }
  // Fill reserved slots only with similarly qualified roles, then backfill by fit.
  const close = candidates.filter(r => r[9] >= (candidates[0]?.[9] ?? 0) - 10);
  const defenseSlots = Math.round(limit * defenseTarget);
  for (const [isDefense, slots] of [[true, defenseSlots], [false, limit - defenseSlots]]) {
    let taken = 0;
    for (const r of close) {
      if (taken < slots && defenseIds.has(String(r[15])) === isDefense && add(r)) taken++;
    }
  }
  candidates.forEach(add);
  return selected.sort((a, b) => b[9] - a[9]);
}

function statusFormula(status) {
  if (!STATUSES.includes(status)) throw new Error('Unknown application status: ' + status);
  return '=COUNTIF(Jobs!A2:A,"' + status + '")';
}

function refreshDashboard(ss) {
  const dashboard = ss.getSheetByName('Dashboard');
  if (!dashboard) return;
  dashboard.getRange(7, 2, 4, 1).setValues(['Applied','Interviewing','Offer','Rejected'].map(s => [statusFormula(s)]));
  dashboard.getRange(20, 2, 2, 1).setValues(['Not Interested','Withdrawn'].map(s => [statusFormula(s)]));
  dashboard.getRange(5, 2, 2, 1).setValues([
    ['=COUNTIF(Jobs!Q2:Q,"Seen in latest search")'],
    ['=COUNTIF(Jobs!A2:A,"Not Applied")'],
  ]);
  dashboard.getRange(22, 2).setValue(
    '=COUNTIFS(Jobs!C2:C,">0",Jobs!C2:C,"<="&TODAY(),Jobs!A2:A,"Applied")' +
    '+COUNTIFS(Jobs!C2:C,">0",Jobs!C2:C,"<="&TODAY(),Jobs!A2:A,"Interviewing")' +
    '+COUNTIFS(Jobs!C2:C,">0",Jobs!C2:C,"<="&TODAY(),Jobs!A2:A,"Offer")'
  );
  dashboard.getRange(23, 2).setValue(
    '=IFERROR(INDEX(FILTER(Jobs!C2:C,Jobs!P2:P="workday:rtx:01879801"),1),"")'
  ).setNumberFormat('mmm d, yyyy');
  dashboard.getRange(24, 2).setValue('=COUNTIFS(Jobs!R2:R,Settings!B3,Jobs!Q2:Q,"Seen in latest search")');
  dashboard.getRange(25, 2).setValue("=COUNTIF('Apply Next'!A4:A15,\"Apply\")");
  dashboard.getRange(26, 2).setValue('=COUNTIFS(Jobs!A2:A,"Not Applied",Jobs!Q2:Q,"Seen in latest search",Jobs!X2:X,"Apply")');
}

function refreshViews() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const jobs = ss.getSheetByName('Jobs');
  const rows = jobs.getLastRow() > 1 ? jobs.getRange(2,1,jobs.getLastRow()-1,HEADERS.length).getValues() : [];
  const index = indexRows(rows);
  refreshDashboard(ss);
  const view = ss.getSheetByName('Apply Next');
  const props = PropertiesService.getDocumentProperties();
  const defense = new Set(JSON.parse(props.getProperty('defenseIds') || '[]'));
  const chosen = shortlist(rows, Number(props.getProperty('shortlistLimit')) || 12,
    Number(props.getProperty('shortlistPerCompany')) || 2, defense, Number(props.getProperty('defenseTarget')) || 0.725);
  if (view.getLastRow() > 3) view.getRange(4,1,view.getLastRow()-3,12).clearContent();
  view.getRange(3,1,1,12).clearContent();
  view.getRange(3,1,1,QUEUE_HEADERS.length).setValues([QUEUE_HEADERS]);
  view.getRange(2,1).setValue(chosen.length + ' Apply candidates. Stretch and Review stay in Jobs.');
  const values = chosen.map(r => {
    const url = String(r[14]).replace(/"/g, '""');
    const title = String(r[5]).replace(/"/g, '""');
    const location = String(r[6]).length > 100 ? 'Multiple US locations; see posting' : r[6];
    return ['Apply', textCell(r[4]), '=HYPERLINK("' + url + '","' + title + '")', textCell(location),
      r[20] || 'Unknown', textCell(r[10]), textCell(r[24]), r[9], textCell(r[25]),
      '=HYPERLINK("' + ss.getUrl() + '#gid=' + jobs.getSheetId() + '&range=A' + index.get(String(r[15])) + '","Track")'];
  });
  if (values.length) {
    view.getRange(4,1,values.length,QUEUE_HEADERS.length).setValues(values);
    view.getRange(4,5,values.length,1).setNumberFormat('mmm d, yyyy');
  }
}

function installDailyTrigger() {
  // Only replace this script's sync trigger; never touch unrelated automations.
  ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()==='syncJobs').forEach(t=>ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('syncJobs').timeBased().everyDays(1).atHour(15).inTimezone('Etc/UTC').create();
}

if (typeof module !== 'undefined') module.exports = {autoFields,validateFeed,indexRows,shortlist,textCell,statusFormula,HEADERS,STATUSES,QUEUE_HEADERS};
