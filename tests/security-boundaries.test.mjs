import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';
import {development, socialStatus, publicActor, equal, loadSession} from '../src/core.js';

const context={waitUntil(){}};
function database(user=null) {
  return {
    prepare(sql) {
      return {
        bind() {
          return {
            async first() { return sql.includes('durable_rates') ? {count:1} : user; },
            async all() { return {results:[]}; }
          };
        }
      };
    }
  };
}
const production = (user=null) => ({APP_ENV:'production',PUBLIC_ORIGIN:'https://synapse.example.com',DB:database(user),ASSETS:{async fetch(){return new Response('asset');}}});
const request = (path,headers={},body='{}') => new Request('https://synapse.example.com'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Synapse-Client':'web-v10',...headers},body});

test('remote hostname cannot activate development or bypass production origin',async()=>{
  const env={...production(),APP_ENV:'development',AGE_ENFORCED:'0'};
  assert.equal(development({env,url:new URL('https://synapse.example.com')}),false);
  const response=await worker.fetch(new Request('https://synapse.example.com/api/health'),env,context);
  assert.equal(response.status,503);
  const wrongHost=await worker.fetch(new Request('https://other.example.com/api/health'),production(),context);
  assert.equal(wrongHost.status,400);
});

test('cross-origin and cross-site API writes are rejected before account lookup',async()=>{
  const cases=[{'Origin':'https://other.example.com'},{'Sec-Fetch-Site':'cross-site'}, {'Origin':'null'}];
  for(const headers of cases){
    const response=await worker.fetch(request('/api/auth/login',headers),production(),context);
    assert.equal(response.status,403);
    assert.equal(response.headers.get('Cache-Control'),'no-store');
    assert.equal(response.headers.get('Access-Control-Allow-Origin'),null);
  }
});

test('browser form requests without custom protection header cannot mutate API',async()=>{
  const req=new Request('https://synapse.example.com/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const response=await worker.fetch(req,production(),context);
  assert.equal(response.status,403);
});

test('authenticated account mutations require a matching CSRF token',async()=>{
  const user={id:'alice',csrf:'correct-csrf',active:1};
  for(const token of [undefined,'wrong-csrf']){
    const headers={Cookie:'synapse_session='+'a'.repeat(43)};
    if(token)headers['X-CSRF-Token']=token;
    const response=await worker.fetch(request('/api/preferences',headers),production(user),context);
    assert.equal(response.status,403);
    assert.match((await response.json()).detail,/segurança/i);
  }
});

test('health response carries security headers and HEAD has no body',async()=>{
  const response=await worker.fetch(new Request('https://synapse.example.com/api/health',{method:'HEAD'}),production(),context);
  assert.equal(response.status,200);
  assert.equal(await response.text(),'');
  assert.equal(response.headers.get('X-Content-Type-Options'),'nosniff');
  assert.equal(response.headers.get('Referrer-Policy'),'no-referrer');
  assert.equal(response.headers.get('X-Frame-Options'),'DENY');
  assert.ok(response.headers.get('Content-Security-Policy').includes("frame-ancestors 'none'"));
  assert.equal(response.headers.get('Strict-Transport-Security'),'max-age=31536000');
});

test('malformed session cookie is ignored and never used as raw SQL',async()=>{
  let calls=0;
  const c={request:new Request('https://synapse.example.com',{headers:{Cookie:"synapse_session=x' OR 1=1 --"}}),env:{DB:{prepare(){calls++;throw Error('must not query');}}}};
  assert.equal(await loadSession(c),null);
  assert.equal(calls,0);
});

test('public actor projection excludes account secrets and private email',()=>{
  const actor=publicActor({id:'alice',name:'Alice',email:'secret@example.com',password_hash:'secret',csrf:'private-token',age_band:'adult',interests:'["design"]'});
  assert.equal(actor.email,undefined);
  assert.equal(actor.password_hash,undefined);
  assert.equal(actor.csrf,undefined);
  assert.equal(actor.age_band,undefined);
  assert.deepEqual(actor.interests,['design']);
  assert.equal(equal('abc','abcd'),false);
  assert.equal(equal('same','same'),true);
});
