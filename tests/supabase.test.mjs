import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync, readdirSync} from 'node:fs';
import crypto from 'node:crypto';
import {syncBuiltinESMExports} from 'node:module';
import registerAuth from '../src/auth.js';
import registerAdmin from '../src/admin.js';
import {sha256} from '../src/core.js';
import {checkCredential, confirmCredential, deleteExternal} from '../src/credentials.js';
import {provisionCredential, processCredentialCleanup} from '../src/credential-operations.js';

const routes = new Map();
const router = {on(method,path,handler) { routes.set(method+' '+path,handler); }};
registerAuth(router); registerAdmin(router);
const call = (key,context) => routes.get(key)(context);
const denied = (promise,status) => assert.rejects(promise,error=>error.status===status);
const secret = 'a long private testing password';
const project = 'abcdefghijklmnopqrst';
const uuid = () => crypto.randomUUID();

// SQLite executes the same transactional statements used with D1. Provider
// requests are modeled here; these tests do not contact a hosted project.
function fixture(t) {
  const db = new DatabaseSync(':memory:');
  for (const file of readdirSync(new URL('../migrations/',import.meta.url)).filter(f=>f.endsWith('.sql')).sort()) {
    db.exec(readFileSync(new URL('../migrations/'+file,import.meta.url),'utf8'));
  }
  t.after(()=>db.close());
  function prepare(sql,args=[]) {
    return {sql,args,bind(...values){return prepare(sql,values);},
      async first(column){const row=db.prepare(sql).get(...args);return column?row?.[column]??null:row||null;},
      async all(){const results=db.prepare(sql).all(...args);return {results,success:true,meta:{changes:db.prepare('SELECT changes() n').get().n}};},
      async run(){const result=db.prepare(sql).run(...args);return {success:true,meta:{changes:Number(result.changes)}};}
    };
  }
  const DB={prepare,async batch(statements){db.exec('BEGIN IMMEDIATE');try{const result=[];for(const item of statements){
    if(/\bRETURNING\b|^\s*(SELECT|PRAGMA)/i.test(item.sql)){const results=db.prepare(item.sql).all(...item.args);result.push({results,meta:{changes:db.prepare('SELECT changes() n').get().n}});}
    else {const r=db.prepare(item.sql).run(...item.args);result.push({meta:{changes:Number(r.changes)}});}
  }db.exec('COMMIT');return result;}catch(e){db.exec('ROLLBACK');throw e;}}};
  const env={DB,APP_ENV:'development',PUBLIC_ORIGIN:'http://localhost:8787',AUTH_PROVIDER:'supabase',
    SUPABASE_URL:`https://${project}.supabase.co`,SUPABASE_PUBLISHABLE_KEY:'sb_publishable_testingonly123456789',SUPABASE_SECRET_KEY:'sb_secret_testingonly123456789',
    ADMIN_ENCRYPTION_KEY:Buffer.alloc(32,7).toString('base64url'),SETUP_TOKEN:'private-random-bootstrap-token-for-tests-only',
    MAIL_FROM:'Synapse <test@example.com>',MEDIA:{async delete(){}}};
  const context=(data={},method='POST',user=null,headers={})=>{
    const request=new Request('http://localhost:8787/api/test',{method,headers:{'Content-Type':'application/json',...headers},...(method==='GET'?{}:{body:JSON.stringify(data)})});
    return {request,env,url:new URL(request.url),headers:new Headers(),ctx:{waitUntil(){}},params:{},user,sessionHash:'test-session',json:()=>Promise.resolve(data)};
  };
  const users=new Map(),calls=[];
  let wrongIdentity=false, unavailable=false, failDeletes=false;
  const oldFetch=globalThis.fetch;
  globalThis.fetch=async(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url),method=options.method||'GET',body=options.body?JSON.parse(options.body):{},headers=new Headers(options.headers);
    assert.equal(url.origin,env.SUPABASE_URL,'credentials must only reach the configured project');
    assert.equal(options.redirect,'manual','workerd supports manual, but rejects redirect:error');
    assert.equal(headers.get('authorization'),null,'opaque API keys must not be used as bearer JWTs');
    calls.push({path:url.pathname,method,body,apikey:headers.get('apikey')});
    if(unavailable||(failDeletes&&method==='DELETE'))return Response.json({message:'PRIVATE PROVIDER DIAGNOSTIC',secret:'should never appear'},{status:503});
    if(url.pathname==='/auth/v1/admin/users'&&method==='POST'){
      assert.equal(headers.get('apikey'),env.SUPABASE_SECRET_KEY);
      if([...users.values()].some(u=>u.email===body.email))return Response.json({code:'email_exists'},{status:422});
      const user={id:body.id||uuid(),email:body.email,email_confirmed_at:body.email_confirm?new Date().toISOString():null,password:body.password};
      users.set(user.id,user);return Response.json(user);
    }
    if(url.pathname==='/auth/v1/token'){
      assert.equal(headers.get('apikey'),env.SUPABASE_PUBLISHABLE_KEY);
      assert.equal(url.searchParams.get('grant_type'),'password');
      const user=[...users.values()].find(u=>u.email===body.email&&u.password===body.password);
      if(!user)return Response.json({code:'invalid_credentials'},{status:400});
      if(!user.email_confirmed_at)return Response.json({code:'email_not_confirmed'},{status:400});
      return Response.json({access_token:'opaque-test-access-token',refresh_token:'opaque-test-refresh-token',user:{...user,id:wrongIdentity?uuid():user.id}});
    }
    const id=url.pathname.match(/^\/auth\/v1\/admin\/users\/([a-f0-9-]+)$/)?.[1];
    if(id){
      assert.equal(headers.get('apikey'),env.SUPABASE_SECRET_KEY);
      const user=users.get(id);if(!user)return Response.json({code:'user_not_found'},{status:404});
      if(method==='DELETE'){users.delete(id);return Response.json({});}
      if(method==='PUT'){if(body.password)user.password=body.password;if(body.email_confirm)user.email_confirmed_at=new Date().toISOString();return Response.json(user);}
      if(method==='GET')return Response.json(user);
    }
    throw Error('Unexpected provider request '+method+' '+url.pathname);
  };
  const originalPBKDF=crypto.pbkdf2Sync;
  crypto.pbkdf2Sync=()=>{throw new Error('PBKDF2 must never run in Supabase mode');};syncBuiltinESMExports();
  t.after(()=>{globalThis.fetch=oldFetch;crypto.pbkdf2Sync=originalPBKDF;syncBuiltinESMExports();});
  const actor=handle=>({...db.prepare('SELECT * FROM actors WHERE handle=?').get(handle),csrf:'csrf'});
  return {db,env,context,users,calls,actor,set wrongIdentity(value){wrongIdentity=value;},set unavailable(value){unavailable=value;},set failDeletes(value){failDeletes=value;}};
}
const data=(handle='alice')=>({name:'Testing '+handle,handle,email:handle+'@example.com',password:secret,terms_accepted:true});
async function setup(f){return call('POST /api/setup',f.context(data('owner'),'POST',null,{'X-Setup-Token':f.env.SETUP_TOKEN}));}
async function verify(f,user){
  const raw='v'.repeat(43);
  f.db.prepare("INSERT INTO auth_tokens VALUES(?,?,'verify',?,?)").run(await sha256(raw),user.id,Date.now()/1000+600,new Date().toISOString());
  return call('POST /api/auth/verify',f.context({token:raw}));
}
async function member(f,handle='alice'){
  f.db.prepare('UPDATE site_settings SET registration_open=1 WHERE id=1').run();
  await call('POST /api/auth/register',f.context(data(handle)));
  await verify(f,f.actor(handle));return f.actor(handle);
}
async function resetToken(f,user,raw='r'.repeat(43)){
  f.db.prepare("INSERT INTO auth_tokens VALUES(?,?,'reset',?,?)").run(await sha256(raw),user.id,Date.now()/1000+600,new Date().toISOString());return raw;
}

test('Supabase setup still requires the private token and one-use owner lock; no local PBKDF',async t=>{
  const f=fixture(t);
  await denied(call('POST /api/setup',f.context(data('owner'))),403);
  assert.equal(f.calls.length,0);
  assert.equal((await setup(f)).ok,true);
  const user=f.actor('owner');assert.match(user.password_hash,/^supabase\$/);
  assert.equal(user.email_verified,0);
  assert.equal([...f.users.values()][0].email_confirmed_at,null);
  assert.equal(f.db.prepare('SELECT role FROM operator_roles').get().role,'owner');
  await denied(setup(f),409);
  assert.equal(f.users.size,1);
});

test('Supabase login requires local email proof and matches the immutable provider UUID',async t=>{
  const f=fixture(t);await setup(f);
  await assert.rejects(call('POST /api/auth/login',f.context({handle:'owner',password:secret})),e=>e.status===401||e.status===403);
  await assert.rejects(confirmCredential(f.context(),f.actor('owner')));
  assert.equal([...f.users.values()][0].email_confirmed_at,null);
  await verify(f,f.actor('owner'));
  assert.equal((await call('POST /api/auth/login',f.context({handle:'owner',password:secret}))).ok,true);
  f.wrongIdentity=true;
  await denied(call('POST /api/auth/login',f.context({handle:'owner',password:secret})),401);
});

test('Supabase missing-user and wrong-password paths never execute the local PBKDF dummy',async t=>{
  const f=fixture(t);await member(f);
  await denied(call('POST /api/auth/login',f.context({handle:'unknown',password:secret})),401);
  await denied(call('POST /api/auth/login',f.context({handle:'alice',password:'incorrect'})),401);
});

test('Supabase missing secrets and outages fail closed without leaking provider diagnostics',async t=>{
  const f=fixture(t);delete f.env.SUPABASE_SECRET_KEY;
  await denied(setup(f),503);assert.equal(f.db.prepare('SELECT count(*) n FROM actors').get().n,0);
  f.env.SUPABASE_SECRET_KEY='sb_secret_testingonly123456789';f.unavailable=true;
  await assert.rejects(setup(f),e=>e.status===503&&!/PRIVATE PROVIDER|should never/.test(e.message));
  assert.equal(f.db.prepare('SELECT count(*) n FROM operators').get().n,0);
});

test('Supabase registration still respects closed registrations before creating provider identities',async t=>{
  const f=fixture(t);
  await denied(call('POST /api/auth/register',f.context(data())),403);
  assert.equal(f.calls.length,0);assert.equal(f.users.size,0);
});

test('Supabase password reset consumes a token once and revokes local sessions',async t=>{
  const f=fixture(t),user=await member(f),raw=await resetToken(f,user);
  f.db.prepare("INSERT INTO sessions VALUES('extra-session',?,'csrf',?)").run(user.id,Date.now()/1000+600);
  const outcomes=await Promise.allSettled([
    call('POST /api/auth/reset',f.context({token:raw,password:'first replacement password'})),
    call('POST /api/auth/reset',f.context({token:raw,password:'second replacement password'}))
  ]);
  assert.equal(outcomes.filter(o=>o.status==='fulfilled').length,1);
  assert.equal(f.db.prepare('SELECT count(*) n FROM sessions WHERE user_id=?').get(user.id).n,0);
  assert.equal(f.db.prepare("SELECT count(*) n FROM auth_tokens WHERE user_id=? AND purpose='reset'").get(user.id).n,0);
  assert.equal(f.calls.filter(c=>c.method==='PUT'&&c.body.password).length,1);
  await denied(call('POST /api/auth/reset',f.context({token:raw,password:'unwanted replay password'})),400);
});

test('Supabase change password requires reauthentication and revokes sessions',async t=>{
  const f=fixture(t),user=await member(f);
  await denied(call('PATCH /api/account/password',f.context({current_password:'incorrect',password:'replacement new password'},'PATCH',user)),401);
  assert.equal((await call('PATCH /api/account/password',f.context({current_password:secret,password:'replacement new password'},'PATCH',user))).ok,true);
  assert.equal(f.db.prepare('SELECT count(*) n FROM sessions WHERE user_id=?').get(user.id).n,0);
  await denied(call('POST /api/auth/login',f.context({handle:'alice',password:secret})),401);
  assert.equal((await call('POST /api/auth/login',f.context({handle:'alice',password:'replacement new password'}))).ok,true);
});

test('Supabase admin MFA enrollment reauthenticates externally; password alone does not grant admin access',async t=>{
  const f=fixture(t);await setup(f);await verify(f,f.actor('owner'));
  const user=f.actor('owner');
  await denied(call('POST /api/manage/security/enroll',f.context({password:'incorrect'},'POST',user)),401);
  const result=await call('POST /api/manage/security/enroll',f.context({password:secret},'POST',user));
  assert.ok(result.secret);assert.equal(f.db.prepare('SELECT enabled FROM operator_security').get().enabled,0);
  assert.equal(f.db.prepare('SELECT count(*) n FROM admin_grants').get().n,0);
});

test('Supabase final owner deletion is blocked before deleting external identity',async t=>{
  const f=fixture(t);await setup(f);await verify(f,f.actor('owner'));
  await denied(call('DELETE /api/account',f.context({password:secret},'DELETE',f.actor('owner'))),409);
  assert.equal(f.db.prepare('SELECT count(*) n FROM actors').get().n,1);
  assert.equal(f.users.size,1);assert.equal(f.calls.filter(c=>c.method==='DELETE').length,0);
});

test('Supabase marker from a different project cannot authenticate or delete identities',async t=>{
  const f=fixture(t),user=await member(f),foreign={...user,password_hash:user.password_hash.replace(project,'zyxwvutsrqponmlkjihg')};
  const before=f.calls.length;
  await assert.rejects(checkCredential(f.context(),foreign,secret));
  await assert.rejects(deleteExternal(f.context(),foreign.password_hash));
  assert.equal(f.calls.length,before);
});

test('Supabase member deletion revokes local access immediately and durably retries failed remote cleanup',async t=>{
  const f=fixture(t),user=await member(f);
  f.failDeletes=true;
  assert.equal((await call('DELETE /api/account',f.context({password:secret},'DELETE',user))).ok,true);
  assert.equal(f.db.prepare('SELECT count(*) n FROM actors WHERE id=?').get(user.id).n,0);
  assert.equal(f.db.prepare('SELECT count(*) n FROM sessions WHERE user_id=?').get(user.id).n,0);
  assert.equal(f.db.prepare('SELECT count(*) n FROM credential_cleanup').get().n,1);
  assert.equal(f.users.size,1);
  f.failDeletes=false;f.db.prepare('UPDATE credential_cleanup SET not_before=0').run();
  await processCredentialCleanup(f.context());
  assert.equal(f.db.prepare('SELECT count(*) n FROM credential_cleanup').get().n,0);
  assert.equal(f.users.size,0);
});

test('Supabase provisioning records cleanup before remote creation and reaps abandoned identities',async t=>{
  const f=fixture(t);
  const credential=await provisionCredential(f.context(),'abandoned@example.com',secret);
  assert.equal(f.users.size,1);
  assert.equal(f.db.prepare('SELECT credential FROM credential_cleanup').get().credential,credential);
  // Model a request that terminates after the provider created the identity,
  // before the D1 actor transaction could commit.
  f.db.prepare('UPDATE credential_cleanup SET not_before=0').run();
  await processCredentialCleanup(f.context());
  assert.equal(f.users.size,0);
  assert.equal(f.db.prepare('SELECT count(*) n FROM credential_cleanup').get().n,0);
});

test('Supabase cleanup preserves active identities after a password revision change',async t=>{
  const f=fixture(t),user=await member(f),oldCredential=user.password_hash;
  await call('PATCH /api/account/password',f.context({current_password:secret,password:'new private account password'},'PATCH',user));
  assert.notEqual(f.actor('alice').password_hash,oldCredential);
  f.db.prepare('INSERT INTO credential_cleanup VALUES(?,0)').run(oldCredential);
  await processCredentialCleanup(f.context());
  assert.equal(f.users.size,1);
  assert.equal(f.calls.filter(c=>c.method==='DELETE').length,0);
  assert.equal(f.db.prepare('SELECT count(*) n FROM credential_cleanup').get().n,0);
});

test('Supabase failed password reset invalidates its proof and sessions without revealing remote errors',async t=>{
  const f=fixture(t),user=await member(f),raw=await resetToken(f,user);
  f.unavailable=true;
  await assert.rejects(call('POST /api/auth/reset',f.context({token:raw,password:'replacement account password'})),e=>e.status===503&&!/PRIVATE PROVIDER|should never/.test(e.message));
  assert.equal(f.db.prepare('SELECT count(*) n FROM sessions WHERE user_id=?').get(user.id).n,0);
  f.unavailable=false;
  await denied(call('POST /api/auth/reset',f.context({token:raw,password:'unwanted replay password'})),400);
  assert.equal((await call('POST /api/auth/login',f.context({handle:'alice',password:secret}))).ok,true);
});

test('Supabase recovery migrates a legacy account after email proof without evaluating PBKDF',async t=>{
  const f=fixture(t),legacy='pbkdf2_sha256$600000$'+'0'.repeat(32)+'$'+'1'.repeat(64);
  f.db.prepare("INSERT INTO actors(id,handle,name,kind,password_hash,email,email_verified,created_at) VALUES('legacy','legacy','Legacy member','human',?,'legacy@example.com',1,?)").run(legacy,new Date().toISOString());
  const user=f.actor('legacy'),raw=await resetToken(f,user);
  await denied(call('POST /api/auth/login',f.context({handle:'legacy',password:secret})),503);
  assert.equal((await call('POST /api/auth/reset',f.context({token:raw,password:'migrated private password'}))).ok,true);
  const migrated=f.actor('legacy');assert.equal(migrated.id,user.id);assert.match(migrated.password_hash,/^supabase\$/);
  assert.equal((await call('POST /api/auth/login',f.context({handle:'legacy',password:'migrated private password'}))).ok,true);
  assert.equal(f.users.size,1);
});

test('Supabase refuses to confirm a remotely changed email using local proof for another address',async t=>{
  const f=fixture(t);await setup(f);
  const user={...f.actor('owner'),email_verified:1},remote=[...f.users.values()][0];
  remote.email='someone-else@example.com';
  await denied(confirmCredential(f.context(),user),503);
  assert.equal(remote.email_confirmed_at,null);
  assert.equal(f.calls.filter(c=>c.method==='PUT'&&c.body.email_confirm).length,0);
});
