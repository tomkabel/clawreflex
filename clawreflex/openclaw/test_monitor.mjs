import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import puppeteer from 'puppeteer';

test('monitor authenticates, shows a proposal, applies and reverts with actual server state', {timeout:30000}, async()=>{
 const html=await readFile(new URL('../web/index.html',import.meta.url));
 const expected='monitor-test-token-'.repeat(2), actions=[];
 let applied=false;
 const server=http.createServer((req,res)=>{
  res.setHeader('Content-Type',req.url==='/'?'text/html':'application/json');
  if(req.url==='/'){res.end(html);return}
  if(req.headers.authorization!=='Bearer '+expected){res.writeHead(401);res.end(JSON.stringify({error:'unauthorized'}));return}
  if(req.url==='/state'){
   res.end(JSON.stringify({title:'ordinary.py',status:applied?'PATCH_APPLIED':'PATCH_VERIFIED',probe:{ok:true},patch:{ok:true,verification:{tests_run:7}},elapsed_s:1.25,applied,'patch.diff':'-return x\n+return x * 2'}));return;
  }
  if(req.method==='POST'&&['/action/apply','/action/revert'].includes(req.url)){
   let body='';req.on('data',chunk=>{body+=chunk});req.on('end',()=>{const params=JSON.parse(body);assert.ok(params.idempotency_key);actions.push(req.url);applied=req.url.endsWith('apply');res.end(JSON.stringify({ok:true,applied}))});return;
  }
  res.writeHead(404);res.end('{}');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await puppeteer.launch({headless:true,args:['--no-sandbox','--disable-setuid-sandbox']});
 try{
  const page=await browser.newPage();
  await page.goto('http://127.0.0.1:'+server.address().port);
  await page.type('#token',expected);await page.click('#connect');
  await page.waitForFunction(()=>document.getElementById('phase').textContent.includes('proposal ready'));
  assert.equal(await page.$eval('#artifact',el=>el.textContent),'proposal only');
  await page.click('#apply');
  await page.waitForFunction(()=>document.getElementById('artifact').textContent==='applied');
  await page.click('#revert');
  await page.waitForFunction(()=>document.getElementById('artifact').textContent==='proposal only');
  assert.deepEqual(actions,['/action/apply','/action/revert']);
  assert.equal(await page.evaluate(()=>localStorage.length),0);
  assert.equal(new URL(page.url()).search,'');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve))}
});

test('monitor applies and reverts a repair verified by the actual sandbox engine', {timeout:45000}, async()=>{
 const {spawn}=await import('node:child_process');
 const {mkdtemp,readFile,rm}=await import('node:fs/promises');
 const {tmpdir}=await import('node:os');const {join}=await import('node:path');
 const directory=await mkdtemp(join(tmpdir(),'clawreflex-ui-'));
 const script=`import json,secrets,sys\nfrom pathlib import Path\nfrom clawreflex.server import RepairRun,RunServer\nfrom clawreflex.fixtures import fixture\nroot=Path(sys.argv[1]);spec=fixture('sql','uismoke');target=root/'app.py';target.write_text(spec['code'])\nrun=RepairRun('sql','uismoke',root/'run',target)\ntoken=secrets.token_hex(32);server=RunServer(('127.0.0.1',0),run,token)\nprint(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'token':token,'code':spec['code'],'reference':spec['reference']}),flush=True)\nserver.serve_forever()\n`;
 const python=process.env.CLAWREFLEX_TEST_PYTHON||new URL('../../.venv-clawreflex/bin/python',import.meta.url).pathname;
 const child=spawn(python,['-u','-c',script,directory],{stdio:['ignore','pipe','pipe']});
 let browser;
 try{
  const info=await new Promise((resolve,reject)=>{let text='',errors='';const timeout=setTimeout(()=>reject(new Error('engine startup timed out: '+errors)),10000);child.stderr.on('data',chunk=>{errors+=chunk});child.stdout.on('data',chunk=>{text+=chunk;if(text.includes('\n')){clearTimeout(timeout);try{resolve(JSON.parse(text.split('\n')[0]))}catch(error){reject(error)}}});child.once('error',reject);child.once('exit',code=>{clearTimeout(timeout);reject(new Error('engine exited '+code+': '+errors))})});
  const headers={'Content-Type':'application/json',Authorization:'Bearer '+info.token};
  const probe='import unittest, app\nclass E(unittest.TestCase):\n def test_injection(self): self.assertFalse(app.authenticate("missing", "\' OR 1=1 --"))\n';
  for(const [name,body]of[['clawreflex_probe',{test_source:probe}],['clawreflex_patch',{source:info.reference,summary:'parameterized query'}]]){
   const response=await fetch(info.url+'/tool/'+name,{method:'POST',headers,body:JSON.stringify(body)});assert.equal(response.ok,true,JSON.stringify(await response.json()));
  }
  assert.equal(await readFile(join(directory,'app.py'),'utf8'),info.code);
  browser=await puppeteer.launch({headless:true,args:['--no-sandbox','--disable-setuid-sandbox']});
  const page=await browser.newPage();await page.goto(info.url);await page.type('#token',info.token);await page.click('#connect');
  await page.waitForFunction(()=>document.getElementById('artifact').textContent==='proposal only');
  await page.click('#apply');await page.waitForFunction(()=>document.getElementById('artifact').textContent==='applied');
  assert.equal(await readFile(join(directory,'app.py'),'utf8'),info.reference);
  await page.click('#revert');await page.waitForFunction(()=>document.getElementById('artifact').textContent==='proposal only');
  assert.equal(await readFile(join(directory,'app.py'),'utf8'),info.code);
 }finally{if(browser)await browser.close();child.kill('SIGTERM');await new Promise(resolve=>{if(child.exitCode!==null)resolve();else child.once('exit',resolve)});await rm(directory,{recursive:true,force:true})}
});
