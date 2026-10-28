import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import registerAuth, {verifyBot} from '../src/auth.js';
import {hashPassword, passwordOK, sha256} from '../src/core.js';

const routes = new Map();
registerAuth({on(method, path, handler) { routes.set(method + ' ' + path, handler); }});
const handlers = key => routes.get(key);

// Real SQLite transaction/constraint behavior, with the same bound-statement
// interface consumed by the Worker. This is not a network/Cloudflare test.
function fixture(t) {
  const sqlite = new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('../migrations/0001_initial.sql', import.meta.url), 'utf8'));
  t.after(() => sqlite.close());
  function prepare(sql, args = []) {
    const statement = {
      sql, args,
      bind(...values) { return prepare(sql, values); },
      async first(column) { const row = sqlite.prepare(sql).get(...args); return column ? row?.[column] ?? null : row || null; },
      async all() { const results = sqlite.prepare(sql).all(...args); return {success:true, results, meta:{changes:sqlite.prepare('SELECT changes() n').get().n}}; },
      async run() { const info = sqlite.prepare(sql).run(...args); return {success:true, results:[], meta:{changes:Number(info.changes),last_row_id:Number(info.lastInsertRowid)}}; },
      async raw() { return sqlite.prepare(sql).all(...args).map(row => Object.values(row)); }
    };
    return statement;
  }
  const DB = {
    prepare,
    async batch(statements) {
      sqlite.exec('BEGIN IMMEDIATE');
      try {
        const results = [];
        for (const statement of statements) {
          if (/\bRETURNING\b|^\s*(SELECT|PRAGMA)/i.test(statement.sql)) {
            const rows=sqlite.prepare(statement.sql).all(...statement.args);
            results.push({success:true,results:rows,meta:{changes:sqlite.prepare('SELECT changes() n').get().n}});
          } else {
            const info=sqlite.prepare(statement.sql).run(...statement.args);
            results.push({success:true,results:[],meta:{changes:Number(info.changes)}});
          }
        }
        sqlite.exec('COMMIT');
        return results;
      } catch (error) { sqlite.exec('ROLLBACK'); throw error; }
    },
    async exec(sql) { sqlite.exec(sql); return {count:1,duration:0}; }
  };
  const env = {
    DB, APP_ENV:'development', PUBLIC_ORIGIN:'http://localhost:8787',
    ADMIN_ENCRYPTION_KEY:Buffer.alloc(32, 7).toString('base64url'),
    SETUP_TOKEN:'private-random-bootstrap-token-for-tests-only',
    MAIL_FROM:'Synapse <test@example.com>', MEDIA:{async delete() {}},
  };
  function context(data={}, method='POST', user=null, headers={}) {
    const request = new Request('http://localhost:8787/api/test', {method, headers:{'Content-Type':'application/json',...headers}, ...(method==='GET'?{}:{body:JSON.stringify(data)})});
    return {request,env,ctx:{waitUntil(){}},url:new URL(request.url),params:{},headers:new Headers(),user,sessionHash:'session-current',json:()=>Promise.resolve(data)};
  }
  return {sqlite,DB,env,context};
}
async function actor(f, id='alice', overrides={}) {
  const hash = await hashPassword('a long private test password');
  f.sqlite.prepare("INSERT INTO actors(id,handle,name,kind,password_hash,email,email_verified,created_at,age_band,age_verified_until) VALUES(?,?,?,'human',?,?,1,?,'adult',?)")
    .run(id,id,'Test '+id,hash,id+'@example.com',new Date().toISOString(),Date.now()/1000+3600);
  const user = {...f.sqlite.prepare('SELECT * FROM actors WHERE id=?').get(id),csrf:'test-csrf',...overrides};
  for (const [key,value] of Object.entries(overrides)) f.sqlite.prepare(`UPDATE actors SET ${key}=? WHERE id=?`).run(value,id);
  return user;
}
const signupData = (name='alice', invite='') => ({name:'Test Member',handle:name,email:name+'@example.com',password:'a long private test password',terms_accepted:true,invite_code:invite,turnstile_token:''});
const rejectsStatus = (promise,status) => assert.rejects(promise, error => Number(error.status ?? error.statusCode)===status);

// Native D1 serializes each batch. This adapter deliberately executes the batch
// synchronously between awaited preconditions, covering the stale pre-read case.
test('registration closed by default; a one-use invite cannot be consumed twice', async t => {
  const f = fixture(t);
  await rejectsStatus(handlers('POST /api/auth/register')(f.context(signupData())),403);
  const invite = 'a'.repeat(43), hash = await sha256(invite);
  f.sqlite.prepare('INSERT INTO pilot_invites(id,code_hash,label,max_uses,uses,expires,revoked,created_at) VALUES(?,?,?,1,0,?,0,?)')
    .run('invite',hash,'One account',Date.now()/1000+600,new Date().toISOString());
  const first = await handlers('POST /api/auth/register')(f.context(signupData('alice',invite)));
  assert.equal(first.ok,true);
  assert.equal(first.verification_pending,true);
  assert.ok(first.csrf);
  await rejectsStatus(handlers('POST /api/auth/register')(f.context(signupData('bob',invite))),403);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM actors').get().n,1);
  assert.equal(f.sqlite.prepare('SELECT uses FROM pilot_invites').get().uses,1);
  assert.equal(f.sqlite.prepare('SELECT account_private FROM actors').get().account_private,1);
  assert.equal(f.sqlite.prepare('SELECT email_verified FROM actors').get().email_verified,0);
});

test('duplicate signup rolls back the invitation consumption', async t => {
  const f=fixture(t); await actor(f,'alice');
  const invite='b'.repeat(43);
  f.sqlite.prepare('INSERT INTO pilot_invites(id,code_hash,label,max_uses,uses,expires,revoked,created_at) VALUES(?,?,?,1,0,?,0,?)')
    .run('invite',await sha256(invite),'One account',Date.now()/1000+600,new Date().toISOString());
  await rejectsStatus(handlers('POST /api/auth/register')(f.context(signupData('alice',invite))),409);
  assert.equal(f.sqlite.prepare('SELECT uses FROM pilot_invites').get().uses,0);
});

test('setup requires private token and is permanently one-use; it does not verify email', async t => {
  const f=fixture(t), data=signupData(); delete data.invite_code; delete data.turnstile_token;
  await rejectsStatus(handlers('POST /api/setup')(f.context(data)),403);
  const result=await handlers('POST /api/setup')(f.context(data,'POST',null,{'X-Setup-Token':f.env.SETUP_TOKEN}));
  assert.equal(result.ok,true);
  assert.equal(f.sqlite.prepare('SELECT role FROM operator_roles').get().role,'owner');
  assert.equal(f.sqlite.prepare('SELECT email_verified FROM actors').get().email_verified,0);
  await rejectsStatus(handlers('POST /api/setup')(f.context({...data,handle:'other',email:'other@example.com'},'POST',null,{'X-Setup-Token':f.env.SETUP_TOKEN})),409);
  f.sqlite.prepare('DELETE FROM actors').run();
  await rejectsStatus(handlers('POST /api/setup')(f.context(data,'POST',null,{'X-Setup-Token':f.env.SETUP_TOKEN})),409);
});

test('reset token is single-use and revokes all sessions and all tokens', async t => {
  const f=fixture(t), user=await actor(f), raw='r'.repeat(43);
  f.sqlite.prepare("INSERT INTO sessions VALUES('old-session',?,'csrf',?)").run(user.id,Date.now()/1000+600);
  f.sqlite.prepare("INSERT INTO auth_tokens VALUES(?,?,'reset',?,?)").run(await sha256(raw),user.id,Date.now()/1000+600,new Date().toISOString());
  f.sqlite.prepare("INSERT INTO auth_tokens VALUES('other-token',?,'verify',?,?)").run(user.id,Date.now()/1000+600,new Date().toISOString());
  const result=await handlers('POST /api/auth/reset')(f.context({token:raw,password:'a new private test password'}));
  assert.equal(result.ok,true);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM sessions').get().n,0);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM auth_tokens').get().n,0);
  assert.equal(await passwordOK('a new private test password',f.sqlite.prepare('SELECT password_hash FROM actors').get().password_hash),true);
  await rejectsStatus(handlers('POST /api/auth/reset')(f.context({token:raw,password:'another unwanted password'})),400);
});

test('an expired reset link cannot change password or terminate a live session', async t => {
  const f=fixture(t), user=await actor(f), raw='e'.repeat(43);
  f.sqlite.prepare("INSERT INTO sessions VALUES('live-session',?,'csrf',?)").run(user.id,Date.now()/1000+600);
  f.sqlite.prepare("INSERT INTO auth_tokens VALUES(?,?,'reset',?,?)").run(await sha256(raw),user.id,Date.now()/1000-1,new Date().toISOString());
  await rejectsStatus(handlers('POST /api/auth/reset')(f.context({token:raw,password:'another unwanted password'})),400);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM sessions').get().n,1);
  assert.equal(f.sqlite.prepare('SELECT password_hash FROM actors').get().password_hash,user.password_hash);
});

test('account export excludes credentials, tokens, other accounts and unrelated conversations', async t => {
  const f=fixture(t), alice=await actor(f,'alice'); await actor(f,'bob'); await actor(f,'carol');
  f.sqlite.prepare("INSERT INTO messages(id,sender_id,recipient_id,body,created_at) VALUES('private','bob','carol','private between others',?)").run(new Date().toISOString());
  const response=await handlers('GET /api/account/export')(f.context({},'GET',alice));
  const body=await response.json(), raw=JSON.stringify(body);
  assert.equal(body.email,'alice@example.com');
  assert.equal(body.messages.length,0);
  assert.equal(raw.includes('password_hash'),false);
  assert.equal(raw.includes('token_hash'),false);
  assert.equal(raw.includes('bob@example.com'),false);
  assert.equal(raw.includes('private between others'),false);
});

test('last owner cannot delete own account; regular member deletion cascades and revokes sessions', async t => {
  const f=fixture(t), owner=await actor(f,'owner'), member=await actor(f,'member');
  f.sqlite.prepare('INSERT INTO operators VALUES(?,?)').run(owner.id,new Date().toISOString());
  f.sqlite.prepare("INSERT INTO operator_roles VALUES(?,'owner')").run(owner.id);
  await rejectsStatus(handlers('DELETE /api/account')(f.context({password:'a long private test password'},'DELETE',owner)),409);
  f.sqlite.prepare("INSERT INTO sessions VALUES('member-session',?,'csrf',?)").run(member.id,Date.now()/1000+600);
  await handlers('DELETE /api/account')(f.context({password:'a long private test password'},'DELETE',member));
  assert.equal(f.sqlite.prepare("SELECT count(*) n FROM actors WHERE id='member'").get().n,0);
  assert.equal(f.sqlite.prepare("SELECT count(*) n FROM sessions WHERE user_id='member'").get().n,0);
  assert.equal(f.sqlite.prepare("SELECT count(*) n FROM actors WHERE id='owner'").get().n,1);
});

test('minor accounts cannot enable direct messages via preferences', async t => {
  const f=fixture(t), user=await actor(f,'minor',{age_band:'16_17'});
  await rejectsStatus(handlers('PATCH /api/preferences')(f.context({dm_policy:'everyone'},'PATCH',user)),403);
  assert.equal((await handlers('PATCH /api/preferences')(f.context({dm_policy:'off'},'PATCH',user))).ok,true);
  assert.equal(f.sqlite.prepare('SELECT dm_policy FROM actors').get().dm_policy,'off');
});

test('Turnstile rejects success for the wrong hostname or action', async t => {
  const f=fixture(t); f.env.APP_ENV='production'; f.env.PUBLIC_ORIGIN='https://synapse.example.com';
  f.env.TURNSTILE_SITE_KEY='public-key'; f.env.TURNSTILE_SECRET_KEY='private-key';
  const oldFetch=globalThis.fetch; t.after(()=>{globalThis.fetch=oldFetch;});
  globalThis.fetch=async()=>Response.json({success:true,hostname:'attacker.example.com',action:'signup'});
  await rejectsStatus(verifyBot(f.context(),'valid-looking-token'),403);
  globalThis.fetch=async()=>Response.json({success:true,hostname:'synapse.example.com',action:'different-action'});
  await rejectsStatus(verifyBot(f.context(),'valid-looking-token'),403);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM actors').get().n,0);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM integration_checks').get().n,0);
});


test('concurrent signups cannot oversubscribe the last invitation slot', async t => {
  const f=fixture(t), invite='c'.repeat(43);
  f.sqlite.prepare('INSERT INTO pilot_invites(id,code_hash,label,max_uses,uses,expires,revoked,created_at) VALUES(?,?,?,1,0,?,0,?)')
    .run('invite',await sha256(invite),'One account',Date.now()/1000+600,new Date().toISOString());
  const outcomes=await Promise.allSettled([
    handlers('POST /api/auth/register')(f.context(signupData('alice',invite))),
    handlers('POST /api/auth/register')(f.context(signupData('bob',invite)))
  ]);
  assert.equal(outcomes.filter(o=>o.status==='fulfilled').length,1);
  assert.equal(outcomes.find(o=>o.status==='rejected').reason.status,403);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM actors').get().n,1);
  assert.equal(f.sqlite.prepare('SELECT uses FROM pilot_invites').get().uses,1);
});

test('concurrent reset requests can consume the same token only once', async t => {
  const f=fixture(t), user=await actor(f), raw='z'.repeat(43);
  f.sqlite.prepare("INSERT INTO auth_tokens VALUES(?,?,'reset',?,?)").run(await sha256(raw),user.id,Date.now()/1000+600,new Date().toISOString());
  const outcomes=await Promise.allSettled([
    handlers('POST /api/auth/reset')(f.context({token:raw,password:'first new private password'})),
    handlers('POST /api/auth/reset')(f.context({token:raw,password:'second new private password'}))
  ]);
  assert.equal(outcomes.filter(o=>o.status==='fulfilled').length,1);
  assert.equal(outcomes.find(o=>o.status==='rejected').reason.status,400);
  assert.equal(f.sqlite.prepare('SELECT count(*) n FROM auth_tokens').get().n,0);
});
