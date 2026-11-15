// Development-only browser integration tests. End-user runtime remains native WebView2.
const { createRequire } = require('node:module');
const { spawn } = require('node:child_process');
const { resolve, join } = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const runtime = process.env.AETHER_TEST_NODE_MODULES;
const { chromium } = runtime ? createRequire(join(runtime,'noop.js'))('playwright') : require('playwright');
const root=resolve(__dirname,'..','..','..');
const privateDir=resolve(root,'../../../validation_private/browser-e2e');fs.mkdirSync(privateDir,{recursive:true});
const port=18761;
// Isolated generated validation DB; no user records.
fs.rmSync(join(privateDir,'test.sqlite3'),{force:true});
const startServer=()=>spawn('python',[resolve(root,'web/backend/validation/biosignal_test_server.py'),'--port',String(port),'--static',resolve(root,'web/frontend/dist-offline')],{cwd:resolve(root,'web/backend'),env:{...process.env,AETHER_DB_PATH:join(privateDir,'test.sqlite3')},windowsHide:true,stdio:'ignore'});
let proc=startServer();
const url='http://127.0.0.1:'+port;
const wait=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 let browser; const checks=[]; const errors=[];
 try {
  for(let i=0;i<60;i++){try{if((await fetch(url+'/api/health')).ok)break;}catch{} await wait(500);}
  browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage({viewport:{width:1500,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url+'/?mode=live#/biosignals');
  await page.getByLabel('Local MMASH path',{exact:true}).waitFor();checks.push('Frontend reaches actual biosignal API');
  const archive=resolve(root,'../../../validation_private/MMASH.zip');
  await page.getByLabel('Local MMASH path',{exact:true}).fill(archive);
  await page.getByRole('button',{name:'Inspect participants'}).click();
  await page.getByLabel('MMASH participant',{exact:true}).waitFor();
  await page.getByLabel('MMASH participant',{exact:true}).selectOption('user_1');
  await page.getByRole('checkbox',{name:/I confirm importing/}).check();
  await page.getByRole('button',{name:'Import selected participant'}).click();
  await page.getByRole('heading',{name:'MMASH:user_1',exact:true}).waitFor({timeout:90000});
  await page.getByRole('img',{name:/Recorded signal graph/}).waitFor();checks.push('Original MMASH import -> SQLite -> authentic graph');
  await page.getByRole('button',{name:'Run supported PHANTOM analysis'}).click();
  await page.getByRole('heading',{name:/PHANTOM adapter/}).waitFor({timeout:30000});checks.push('Actual backend features and PHANTOM partial analysis');
  await page.screenshot({path:resolve(root,'validation_1_1/research-ui.png'),fullPage:true});
  const sessions=await (await fetch(url+'/api/biosignals/sessions')).json();assert.equal(sessions.length,1);const id=sessions[0].id;
  await page.getByRole('button',{name:'Open in BODY',exact:true}).click();
  await page.getByRole('heading',{name:'BODY · recorded measurements'}).waitFor();
  await page.getByRole('application',{name:'Original BODY digital twin for recorded physiological signals'}).waitFor();
  await page.screenshot({path:resolve(root,'validation_1_1/body-recording-ui.png'),fullPage:true});checks.push('BODY displays original 3D viewport with recorded source');
  proc.kill();await wait(1500);proc=startServer();for(let i=0;i<60;i++){try{if((await fetch(url+'/api/health')).ok)break;}catch{}await wait(500);}
  await page.reload();await page.getByRole('heading',{name:'MMASH:user_1',exact:true}).waitFor();checks.push('Full backend restart reopens persisted recording in BODY');
  await page.getByRole('button',{name:'Run supported PHANTOM analysis'}).click();await page.getByRole('heading',{name:/PHANTOM adapter/}).waitFor();
  const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'Export research summary'}).click()]);assert.match(download.suggestedFilename(),/summary/);checks.push('Export research summary');
  // Deletion via API is separately verified, avoiding deletion of user-owned recordings.
  const del=await fetch(url+'/api/biosignals/sessions/'+id,{method:'DELETE'});assert.equal(del.status,200);
  assert.equal((await (await fetch(url+'/api/biosignals/sessions')).json()).length,0);checks.push('Actual records removed after deletion');
  await page.goto(url+'/?mode=live#/biosignals');await page.getByRole('status').filter({hasText:'Sensor disconnected'}).waitFor();checks.push('Disconnected sensor displays no invented live HR');
  await page.getByRole('button',{name:'Scan for devices',exact:true}).click();
  await page.getByRole('button',{name:'Connect / reconnect',exact:true}).waitFor();
  await page.getByRole('button',{name:'Connect / reconnect',exact:true}).click();
  await page.getByText('Live sensor — connected.',{exact:true}).waitFor();
  await page.getByRole('img',{name:/Recorded signal graph/}).waitFor();
  await page.getByRole('button',{name:'Run supported PHANTOM analysis'}).click();
  await page.getByRole('heading',{name:'PHANTOM adapter · insufficient_data'}).waitFor();
  checks.push('Test-only fake BLE -> actual acquisition -> SQLite -> graph -> insufficient-data analysis');
  await page.getByRole('button',{name:'Stop, save & disconnect',exact:true}).click();
  await page.getByText('Sensor disconnected — no live measurements.',{exact:true}).waitFor();
  const stopped=await (await fetch(url+'/api/biosignals/sensor/status')).json();assert.equal(stopped.heart_rate,null);
  checks.push('Stop saves fake-transport session and clears current HR');

  await page.getByLabel('Data origin',{exact:true}).selectOption('synthetic');
  await page.goto(url+'/?mode=live#/mission-lab');await page.getByRole('heading',{name:/MISSION LAB|Mission lab|Experiment/i}).first().waitFor();checks.push('Existing synthetic Mission Lab frontend remains reachable');
  assert.deepEqual(errors,[]);
  fs.writeFileSync(resolve(root,'validation_1_1/frontend-e2e.json'),JSON.stringify({status:'pass',checks,errors},null,2));console.log(checks.join('\n'));
 } catch(e){fs.writeFileSync(resolve(root,'validation_1_1/frontend-e2e.json'),JSON.stringify({status:'fail',checks,error:e.stack,errors},null,2));throw e;}
 finally{if(browser)await browser.close();proc.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
