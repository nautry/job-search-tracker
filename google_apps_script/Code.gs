/** @OnlyCurrentDoc */
/* Bound to your tracker: Extensions > Apps Script. No credentials in source. */
const HEADERS = ['Status','Applied date','Follow-up','Notes','Company','Job title','Location','Role fit','Location fit','Priority','Experience','Salary','Flags','Why match','Link','Job ID','Availability','First seen','Last seen','Source'];
const STATUSES = ['Not Applied','Applied','Interviewing','Offer','Rejected','Not Interested','Withdrawn'];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Job search').addItem('Refresh jobs','syncJobs').addItem('Refresh shortlist','refreshViews').addItem('Set up daily refresh','installDailyTrigger').addToUi();
}

function onEdit(e) {
  if (e && e.range.getSheet().getName()==='Jobs' && e.range.getColumn()<=4 && e.range.getRow()>1) refreshViews();
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
  return [textCell(j.company), '=HYPERLINK("'+url+'","'+title+'")', textCell(j.location), Number(j.role_score), textCell(j.location_fit), Number(j.priority), textCell(j.experience), textCell(j.salary), textCell(j.flags), textCell(j.evidence), j.url, textCell(j.id), textCell(j.availability), j.first_seen ? new Date(j.first_seen) : '', j.last_seen ? new Date(j.last_seen) : '', textCell(j.source)];
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
    if (JSON.stringify(sh.getRange(1,1,1,20).getValues()[0]) !== JSON.stringify(HEADERS)) throw new Error('Jobs headers changed. Restore headers before sync.');
    const rows = sh.getLastRow() > 1 ? sh.getRange(2,1,sh.getLastRow()-1,20).getValues() : [];
    const index = indexRows(rows);
    const newJobs = feed.jobs.filter(j=>!index.has(j.id));
    const last = Math.max(2, sh.getLastRow()+newJobs.length);
    if (last > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(),last-sh.getMaxRows());
    // Existing A:D are never written. Sorting the whole table is safe: match by ID.
    feed.jobs.forEach(j=>{if(index.has(j.id)) {
      const fields=autoFields(j);
      const firstSeen=rows[index.get(j.id)-2][17];
      if(firstSeen) fields[13]=firstSeen;
      sh.getRange(index.get(j.id),5,1,16).setValues([fields]);
    }});
    if (newJobs.length) {
      const start = sh.getLastRow()+1;
      sh.getRange(start,1,newJobs.length,20).setValues(newJobs.map(j=>['Not Applied','','','',...autoFields(j)]));
    }
    const feedIds = new Set(feed.jobs.map(j=>j.id));
    const sourceStates = new Map(feed.source_status.map(s=>[s.source,s.status]));
    rows.forEach((r,i)=>{
      if(r[15] && !feedIds.has(String(r[15]))) sh.getRange(i+2,17).setValue(sourceStates.get(String(r[19]))==='ok' ? 'Not seen in latest complete search' : 'Source incomplete / unavailable; retained');
    });
    sh.getRange(2,1,last-1,1).setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(STATUSES,true).setAllowInvalid(false).build());
    sh.getRange(2,2,last-1,2).setNumberFormat('mm/dd/yy');
    sh.getRange(2,18,last-1,2).setNumberFormat('mm/dd/yy');
    const sources = ss.getSheetByName('Sources');
    const values = feed.source_status.map(s=>[s.company,s.status,s.collected,s.matched,new Date(s.checked_at),s.scope,s.error || '',s.careers_url,s.context]);
    if (sources.getLastRow()>1) sources.getRange(2,1,sources.getLastRow()-1,9).clearContent();
    if (values.length) sources.getRange(2,1,values.length,9).setValues(values.map(r=>r.map(textCell)));
    if (values.length) sources.getRange(2,5,values.length,1).setNumberFormat('yyyy-mm-dd hh:mm');
    cfg.getRange('B3').setValue(new Date(feed.generated_at));
    cfg.getRange('B4').setValue(new Date());
    cfg.getRange('B5').setValue('Sync succeeded; '+feed.jobs.length+' feed jobs; '+feed.source_status.filter(s=>s.status!=='ok').length+' sources need review');
    PropertiesService.getDocumentProperties().setProperty('shortlistLimit', String(Number(feed.preferences && feed.preferences.shortlist_limit)||25));
    PropertiesService.getDocumentProperties().setProperty('shortlistPerCompany', String(Number(feed.preferences && feed.preferences.shortlist_per_company)||5));
    refreshViews();
  } catch(e) {
    SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Settings').getRange('B5').setValue('Sync failed: '+e.message);
    throw e;
  } finally { lock.releaseLock(); }
}

function shortlist(rows, limit=25, perCompany=5) {
  const counts = new Map();
  return rows.filter(r=>r[15] && r[0]==='Not Applied' && r[16]==='Seen in latest search' && !/Deprioritized|Location review/.test(r[8])).sort((a,b)=>b[9]-a[9]).filter(r=>{
    const company=String(r[4]);
    const n=counts.get(company)||0;
    if(n>=perCompany) return false;
    counts.set(company,n+1); return true;
  }).slice(0,limit);
}

function refreshViews() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const jobs = ss.getSheetByName('Jobs');
  const rows = jobs.getLastRow()>1 ? jobs.getRange(2,1,jobs.getLastRow()-1,20).getValues() : [];
  const indices = indexRows(rows);
  const view = ss.getSheetByName('Apply Next');
  if (view.getLastRow()>3) view.getRange(4,1,view.getLastRow()-3,9).clearContent();
  const props = PropertiesService.getDocumentProperties();
  const values = shortlist(rows, Number(props.getProperty('shortlistLimit'))||25, Number(props.getProperty('shortlistPerCompany'))||5).map(r=>{
    const jobUrl = String(r[14]).replace(/"/g,'""');
    const title = String(r[5]).replace(/"/g,'""');
    const loc = String(r[6]).length>100 ? 'Multiple US locations; see posting' : textCell(r[6]);
    return [textCell(r[4]), '=HYPERLINK("'+jobUrl+'","'+title+'")',loc,r[7],r[9],textCell(r[10]),textCell(r[12]),'=HYPERLINK("'+ss.getUrl()+'#gid='+jobs.getSheetId()+'&range=A'+indices.get(String(r[15]))+'","Edit status / notes")',textCell(r[15])];
  });
  if (values.length) view.getRange(4,1,values.length,9).setValues(values);
}

function installDailyTrigger() {
  // Only replace this script's sync trigger; never touch unrelated automations.
  ScriptApp.getProjectTriggers().filter(t=>t.getHandlerFunction()==='syncJobs').forEach(t=>ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('syncJobs').timeBased().everyDays(1).atHour(15).inTimezone('Etc/UTC').create();
}

if (typeof module !== 'undefined') module.exports = {autoFields,validateFeed,indexRows,shortlist,textCell};
