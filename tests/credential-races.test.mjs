import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,readdirSync} from 'node:fs';
import {setSession} from '../src/core.js';
import {withCredentialLock} from '../src/credential-operations.js';

const credential='supabase$abcdefghijklmnopqrst$12345678-1234-4234-8234-123456789abc$'+'a'.repeat(32);
function fixture(t){
  const db=new DatabaseSync(':memory:');
  for(const file of readdirSync(new URL('../migrations/',import.meta.url)).filter(f=>f.endsWith('.sql')).sort())db.exec(readFileSync(new URL('../migrations/'+file,import.meta.url),'utf8'));
  t.after(()=>db.close());
  function prepare(sql,args=[]){return {sql,args,bind(...a){return prepare(sql,a);},async first(){return db.prepare(sql).get(...args)||null;},async run(){return {meta:{changes:Number(db.prepare(sql).run(...args).changes)}};}};}
  const DB={prepare,async batch(statements){db.exec('BEGIN');try{const out=[];for(const s of statements)out.push({meta:{changes:Number(db.prepare(s.sql).run(...s.args).changes)}});db.exec('COMMIT');return out;}catch(e){db.exec('ROLLBACK');throw e;}}};
  db.prepare("INSERT INTO actors(id,handle,name,kind,password_hash,email,created_at) VALUES('alice','alice','Alice','human',?,'alice@example.com',?)").run(credential,new Date().toISOString());
  const context=()=>({env:{DB,APP_ENV:'development'},url:new URL('http://localhost:8787'),headers:new Headers()});
  const user=()=>db.prepare("SELECT * FROM actors WHERE id='alice'").get();
  return {db,context,user};
}

test('external session blocks a live mutation lock but recovers after an abandoned lock expires',async t=>{
  const f=fixture(t);
  f.db.prepare('INSERT INTO auth_operation_locks VALUES(?,?,?)').run('alice','abandoned',Date.now()/1000+300);
  await assert.rejects(setSession(f.context(),'alice',credential),e=>e.status===409);
  assert.equal(f.db.prepare('SELECT count(*) n FROM sessions').get().n,0);
  f.db.prepare('UPDATE auth_operation_locks SET expires=?').run(Date.now()/1000-1);
  const c=f.context();assert.ok(await setSession(c,'alice',credential));
  assert.match(c.headers.get('set-cookie'),/HttpOnly/);
  assert.equal(f.db.prepare('SELECT count(*) n FROM sessions').get().n,1);
});

test('a login verified before credential rotation cannot create a session afterward',async t=>{
  const f=fixture(t),next=credential.slice(0,-32)+'b'.repeat(32);
  f.db.prepare("UPDATE actors SET password_hash=? WHERE id='alice'").run(next);
  await assert.rejects(setSession(f.context(),'alice',credential),e=>e.status===409);
  assert.equal(f.db.prepare('SELECT count(*) n FROM sessions').get().n,0);
  assert.ok(await setSession(f.context(),'alice',next));
});

test('credential lock serializes mutation callbacks and rejects stale actor revisions',async t=>{
  const f=fixture(t),before=f.user();let release,entered;
  const waiting=new Promise(r=>{release=r;}),started=new Promise(r=>{entered=r;});
  const first=withCredentialLock(f.context(),before,async()=>{entered();await waiting;});
  await started;
  let executed=false;
  await assert.rejects(withCredentialLock(f.context(),before,async()=>{executed=true;}),e=>e.status===409);
  assert.equal(executed,false);release();await first;
  assert.equal(f.db.prepare('SELECT count(*) n FROM auth_operation_locks').get().n,0);
  f.db.prepare("UPDATE actors SET password_hash=? WHERE id='alice'").run(credential.slice(0,-32)+'c'.repeat(32));
  await assert.rejects(withCredentialLock(f.context(),before,async()=>{executed=true;}),e=>e.status===409);
  assert.equal(executed,false);
});
