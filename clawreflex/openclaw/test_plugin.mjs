import test from 'node:test';
import assert from 'node:assert/strict';
import plugin, { card, connection, request } from './index.mjs';
const env={CLAWREFLEX_URL:'http://127.0.0.1:8787',CLAWREFLEX_TOKEN:'a'.repeat(32)};
test('connection refuses remote hosts, credentials and short tokens',()=>{
 assert.equal(connection(env).origin,env.CLAWREFLEX_URL);
 for(const url of ['https://127.0.0.1','http://example.com','http://localhost@evil.test','http://127.0.0.1/?token=x']) assert.throws(()=>connection({...env,CLAWREFLEX_URL:url}));
 assert.throws(()=>connection({...env,CLAWREFLEX_TOKEN:'short'}));
});
test('request authenticates and preserves structured failure',async()=>{
 let captured;
 const result=await request('/state',undefined,{env,fetcher:async(url,options)=>{captured={url,options};return {ok:false,json:async()=>({error:'unauthorized'})}}});
 assert.equal(captured.options.headers.Authorization,'Bearer '+env.CLAWREFLEX_TOKEN);
 assert.equal(captured.options.method,'GET');assert.equal(result.ok,false);
});
test('card distinguishes proposal from applied and includes actual evidence',()=>{
 const result=card({id:'run1',status:'PATCH_VERIFIED',probe:{ok:true},patch:{ok:true,verification:{tests_run:8}},elapsed_s:2.5,applied:false,'patch.diff':'-bad\n+good'});
 assert.match(result.text,/Applied to target: no/);assert.match(result.text,/GREEN tests: 8/);assert.match(result.text,/\/clawreflex apply run1/);assert.equal(result.continueAgent,false);
});
test('registers proof tools and authorized command, no model apply tool',async()=>{
 const tools=[],commands=[];
 plugin.register({registerTool:tool=>tools.push(tool),registerCommand:command=>commands.push(command)});
 assert.deepEqual(tools.map(tool=>tool.name),['clawreflex_probe','clawreflex_patch']);
 assert.equal(commands[0].requireAuth,true);
 assert.match((await commands[0].handler({args:'erase everything'})).text,/Usage:/);
});
test('commands route explicit apply and status with a local server',async()=>{
 const oldEnv={url:process.env.CLAWREFLEX_URL,token:process.env.CLAWREFLEX_TOKEN},oldFetch=globalThis.fetch;
 Object.assign(process.env,env);
 const calls=[];
 globalThis.fetch=async(url,options)=>{calls.push({url,options});return{ok:true,json:async()=>url.endsWith('/state')?{title:'test',status:'PATCH_VERIFIED',applied:false}:{ok:true,applied:true}}};
 try{
  const commands=[];plugin.register({registerTool(){},registerCommand:c=>commands.push(c)});
  assert.match((await commands[0].handler({args:'apply run123'})).text,/"applied":true/);
  assert.ok(calls[0].url.endsWith('/runs/run123/action/apply'));
  assert.ok(JSON.parse(calls[0].options.body).idempotency_key);
  assert.match((await commands[0].handler({args:'status run123'})).text,/Applied to target: no/);
 }finally{
  globalThis.fetch=oldFetch;
  for(const [key,value]of[['CLAWREFLEX_URL',oldEnv.url],['CLAWREFLEX_TOKEN',oldEnv.token]])if(value===undefined)delete process.env[key];else process.env[key]=value;
 }
});
