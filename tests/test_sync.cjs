const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const ctx={module:{exports:{}},Date,Map,Set,Number,String,JSON};
vm.runInNewContext(fs.readFileSync('google_apps_script/Code.gs','utf8'),ctx);
const {validateFeed,indexRows,shortlist,textCell,statusFormula,ready,dailyModel,HEADERS}=ctx.module.exports;
const feed={schema_version:1,generated_at:new Date().toISOString(),source_status:[],jobs:[{id:'a',title:'Engineer',url:'https://example.com',role_score:70,priority:80}]};
validateFeed(feed);
assert.throws(()=>validateFeed({...feed,jobs:[...feed.jobs,...feed.jobs]}),/duplicate/);
const row=Array(35).fill('');row[26]='Verified active';row[27]=new Date();row[31]='Mechanical Design';row[33]=true;row[9]=80;row[0]='Applied';row[3]='Private note';row[15]='a';row[8]='Austin metro';row[16]='Seen in latest search';
assert.equal(indexRows([row]).get('a'),2);
assert.throws(()=>indexRows([row,row]),/Duplicate/);
assert.equal(shortlist([row]).length,0);
row[0]='Not Applied';row[23]='Apply';assert.equal(shortlist([row]).length,1);
for (const status of ['Applied','Offer','Rejected','Not Interested','Interviewing','Withdrawn']) {
  assert.equal(shortlist([Object.assign([...row], {0: status})]).length, 0);
}
for (const category of ['Stretch','Review','']) {
  assert.equal(shortlist([Object.assign([...row], {23: category})]).length, 0);
}
const offerFormula = statusFormula('Offer');
const formulaParts = offerFormula.match(/^=COUNTIF\(Jobs!A(\d+):A,"([^"]+)"\)$/);
const dashboardRows = [['Status'], ['Offer'], ['Applied']];
assert.equal(dashboardRows.slice(Number(formulaParts[1]) - 1).filter(r => r[0] === formulaParts[2]).length, 1);
assert.equal(shortlist(Array.from({length:25}, (_, i) =>
  Object.assign([...row], {4: 'Employer ' + i, 15: 'job-' + i})), 30).length, 5);
row[8]='Deprioritized region';assert.equal(shortlist([row]).length,0);
assert.equal(textCell('=IMPORTXML("https://evil", "//x")')[0],"'");
// Exercise real sync twice with minimal Sheets mocks and a user edit between runs.
function makeSheet(rows){return {rows,getLastRow(){return this.rows.length},getMaxRows(){return 1000},getMaxColumns(){return 35},insertColumnsAfter(){},getSheetId(){return 1},insertRowsAfter(){},getRange(r,c,n=1,m=1){if(typeof r==='string'){const a=r.match(/^([A-Z]+)([0-9]+)$/);c=a[1].charCodeAt(0)-64;r=Number(a[2]);}const sh=this;return {getValues(){return Array.from({length:n},(_,i)=>Array.from({length:m},(_,k)=>sh.rows[r-1+i]?.[c-1+k]??''))},getValue(){return sh.rows[r-1]?.[c-1]??''},setValues(v){v.forEach((row,i)=>{sh.rows[r-1+i]??=[];row.forEach((x,k)=>sh.rows[r-1+i][c-1+k]=x)});return this},setValue(v){sh.rows[r-1]??=[];sh.rows[r-1][c-1]=v;return this},clearContent(){for(let i=0;i<n;i++)for(let k=0;k<m;k++)if(sh.rows[r-1+i])sh.rows[r-1+i][c-1+k]='';return this},setDataValidation(){return this},setNumberFormat(){return this}}}}}
const headers=['Status','Applied date','Follow-up','Notes','Company','Job title','Location','Role fit','Location fit','Priority','Experience','Salary','Flags','Why match','Link','Job ID','Availability','First seen','Last seen','Source'];
const sheets={Jobs:makeSheet([headers]),Settings:makeSheet([[],['Feed URL','https://raw.githubusercontent.com/test/repo/main/data/jobs.json']]),Sources:makeSheet([Array(9).fill('Header')]),'Apply Next':makeSheet([[],[],[]])};
const properties=new Map();ctx.PropertiesService={getDocumentProperties:()=>({setProperty(k,v){properties.set(k,v)},getProperty(k){return properties.get(k)||null}})};
ctx.LockService={getDocumentLock:()=>({waitLock(){},releaseLock(){}})};
ctx.SpreadsheetApp={getActiveSpreadsheet:()=>({getSheetByName:n=>sheets[n],insertSheet(n){return sheets[n]=makeSheet([])},getUrl:()=> 'https://docs.google.com/spreadsheets/d/test/edit'}),newDataValidation:()=>({requireValueInList(){return this},setAllowInvalid(){return this},build(){return {}}})};
feed.jobs[0]={...feed.jobs[0],company:'Employer',location:'Austin, TX',location_fit:'Austin metro',availability:'Seen in latest search',first_seen:feed.generated_at,last_seen:feed.generated_at,source:'test'};
ctx.UrlFetchApp={fetch:()=>({getResponseCode:()=>200,getContentText:()=>JSON.stringify(feed)})};
ctx.syncJobs();
assert.equal(sheets.Jobs.rows.length,2);
sheets.Jobs.rows[1][0]='Offer';sheets.Jobs.rows[1][1]='10/25/26';sheets.Jobs.rows[1][2]='11/16/26';sheets.Jobs.rows[1][3]='Private note';sheets.Jobs.rows[1][34]='12/01/26';
const originalFirst=sheets.Jobs.rows[1][17];
feed.jobs[0].first_seen=new Date(Date.now()+1000).toISOString();
feed.jobs[0].title='Updated Engineer';ctx.syncJobs();
assert.equal(sheets.Jobs.rows[1][17],originalFirst);
assert.equal(sheets.Jobs.rows.length,2);
assert.equal(sheets.Jobs.rows[1][0],'Offer');
assert.equal(sheets.Jobs.rows[1][2],'11/16/26');
assert.equal(sheets.Jobs.rows[1][1],'10/25/26');
assert.equal(sheets.Jobs.rows[1][3],'Private note');
assert.equal(sheets.Jobs.rows[1][34],'12/01/26');
assert.ok(sheets.Jobs.rows[1][5].includes('Updated Engineer'));
ctx.UrlFetchApp.fetch=()=>({getResponseCode:()=>503});
assert.throws(()=>ctx.syncJobs(),/HTTP 503/);
assert.equal(sheets.Jobs.rows[1][3],'Private note');
ctx.UrlFetchApp.fetch=()=>({getResponseCode:()=>200,getContentText:()=>JSON.stringify({...feed,generated_at:'2000-01-01T00:00:00Z'})});
assert.throws(()=>ctx.syncJobs(),/stale/);
assert.equal(sheets.Jobs.rows[1][3],'Private note');
console.log('Sync tests passed: duplicate guards, shortlist, formula escaping, two refreshes, status/date/notes retention, failed-download preservation.');

// Real view generation, full-range offer formula, refill, stable daily assignments and exclusions.
const now=new Date();
const candidate=(id,company='Employer',priority=80)=>Object.assign([...row],{0:'Not Applied',4:company,8:'Austin metro',9:priority,15:id,23:'Apply',26:'Verified active',27:now,33:true,34:''});
const candidates=Array.from({length:12},(_,i)=>candidate('id'+i,'Company '+Math.floor(i/2),100-i));
const first=dailyModel(candidates,{}, {now});
assert.equal(first.daily.length,5);
assert.equal(new Set(first.queue.map(r=>r[15])).size,first.queue.length);
assert.ok(first.queue.every(r=>r[0]==='Not Applied'));
const changed=candidates.map(r=>[...r]);changed[0][0]='Applied';
const next=dailyModel(changed,first,{now});
assert.equal(next.daily.length,5);assert.ok(!next.ids.includes('id0'));
assert.ok(first.ids.slice(1).every(id=>next.ids.includes(id)));
assert.equal(shortlist([Object.assign(candidate('stale'),{27:new Date(Date.now()-48*3600000)})]).length,0);
assert.equal(shortlist([Object.assign(candidate('closed'),{26:'Confirmed closed'})]).length,0);
assert.equal(shortlist([Object.assign(candidate('unverified'),{26:'Unverified'})]).length,0);
assert.equal(shortlist([Object.assign(candidate('deferred'),{34:new Date(Date.now()+86400000)})]).length,0);
assert.equal(shortlist([Object.assign(candidate('dup'),{30:'Possible repost / duplicate; distinct requisitions retained'})]).length,0);
const prior=Object.assign(candidate('old'),{0:'Applied'}),repost=Object.assign(candidate('new'),{29:'old'});
assert.equal(shortlist([prior,repost]).length,0);
const review=Object.assign(candidate('review'),{23:'Review',24:'Start timing unverified'});
assert.equal(dailyModel([review],{}, {now}).daily.length,0);
assert.equal(dailyModel([review],{}, {now}).queue.length,1);
assert.ok(dailyModel([review],{}, {now}).reason.includes('no quota padding'));
ctx.refreshDashboard(ctx.SpreadsheetApp.getActiveSpreadsheet(),sheets.Jobs.rows.slice(1),first);
assert.equal(sheets['Daily Dashboard'].rows[3][7],statusFormula('Offer'));
assert.ok(sheets['Daily Dashboard'].rows[3][1].includes('Jobs!B2:B'));
assert.equal(HEADERS[34],'Deferred until');
console.log('Daily workflow tests passed: stable assignments, refill, employer caps, duplicate/closed/stale/uncertain/deferred exclusion, status formulas and manual deferral preservation.');
