import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import registerAdmin, {requireAdmin, totp} from '../src/admin.js';
import {hashPassword, encryptSecret, sha256} from '../src/core.js';

const routes=new Map();registerAdmin({on(method,path,handler){routes.set(method+' '+path,handler);}});
const call=(key,c)=>routes.get(key)(c);
function fixture(t){
 const db=new DatabaseSync(':memory:');db.exec(readFileSync(new URL('../migrations/0001_initial.sql',import.meta.url),'utf8'));t.after(()=>db.close());
 function prepare(sql,args=[]){return {sql,args,bind(...p){return prepare(sql,p);},async first(){return db.prepare(sql).get(...args)||null;},async all(){return {results:db.prepare(sql).all(...args),meta:{changes:db.prepare('SELECT changes() n').get().n}};},async run(){const r=db.prepare(sql).run(...args);return {meta:{changes:Number(r.changes)}};}};}
 const DB={prepare,async batch(statements){db.exec('BEGIN');try{const r=[];for(const s of statements)r.push(await s.run());db.exec('COMMIT');return r;}catch(e){db.exec('ROLLBACK');throw e;}}};
 const env={DB,APP_ENV:'development',PUBLIC_ORIGIN:'http://localhost:8787',ADMIN_ENCRYPTION_KEY:Buffer.alloc(32,7).toString('base64url'),MEDIA:{async head(){return null;},async put(){},async delete(){}}};
 function context(user,data={},method='POST',params={},path='/api/test'){const request=new Request('http://localhost:8787'+path,{method,headers:{'content-type':'application/json'},...(method==='GET'?{}:{body:JSON.stringify(data)})});return {env,user,request,url:new URL(request.url),params,sessionHash:'session-'+user?.id,headers:new Headers(),ctx:{waitUntil(){}}};}
 function actor(id,role='member'){
  db.prepare("INSERT INTO actors(id,handle,name,kind,password_hash,email,email_verified,created_at) VALUES(?,?,?,'human',?,?,1,?)").run(id,id,'User '+id,hashPassword('a long private test password'),id+'@example.com',new Date().toISOString());
  db.prepare('INSERT INTO sessions VALUES(?,?,?,?)').run('session-'+id,id,'csrf',Date.now()/1000+3600);
  if(role!=='member'){db.prepare('INSERT INTO operators VALUES(?,?)').run(id,new Date().toISOString());db.prepare('INSERT INTO operator_roles VALUES(?,?)').run(id,role);}
  return {...db.prepare('SELECT * FROM actors WHERE id=?').get(id),csrf:'csrf'};
 }
 async function elevated(id,role='owner'){
  const user=actor(id,role),c=context(user),secret='GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ';
  db.prepare('INSERT INTO operator_security(user_id,secret,enabled) VALUES(?,?,1)').run(id,await encryptSecret(c,secret));
  db.prepare('INSERT INTO admin_grants VALUES(?,?,?)').run(c.sessionHash,id,Date.now()/1000+900);return user;
 }
 return {db,env,context,actor,elevated};
}
const denied=(p,status)=>assert.rejects(p,e=>e.status===status);

test('TOTP follows RFC 6238 SHA1 six-digit vector',async()=>{assert.equal(await totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ',1),'287082');});

test('MFA enrollment stores encrypted seed; code replay and recovery reuse are rejected',async t=>{
 const f=fixture(t),user=f.actor('owner','owner');
 const enrollment=await call('POST /api/manage/security/enroll',f.context(user,{password:'a long private test password'}));
 const pending=f.db.prepare('SELECT pending FROM operator_security').get().pending;
 assert.match(pending,/^v1:/);assert.ok(!pending.includes(enrollment.secret));
 const code=await totp(enrollment.secret,Math.floor(Date.now()/30000));
 const confirmed=await call('POST /api/manage/security/confirm',f.context(user,{code}));
 assert.equal(confirmed.recovery_codes.length,8);assert.ok(confirmed.unlocked_until>Date.now()/1000);
 assert.equal((await requireAdmin(f.context(user))).role,'owner');
 await call('POST /api/manage/lock',f.context(user,{}));await denied(requireAdmin(f.context(user)),403);
 await denied(call('POST /api/manage/unlock',f.context(user,{password:'a long private test password',code})),401);
 const recovery=confirmed.recovery_codes[0];
 assert.equal((await call('POST /api/manage/unlock',f.context(user,{password:'a long private test password',code:recovery}))).ok,true);
 await denied(call('POST /api/manage/unlock',f.context(user,{password:'a long private test password',code:recovery})),401);
 const hashes=JSON.parse(f.db.prepare('SELECT recovery_hashes FROM operator_security').get().recovery_hashes);
 assert.equal(hashes.length,7);assert.ok(!hashes.includes(await sha256(recovery)));
});

test('concurrent use of one recovery code unlocks only once',async t=>{
 const f=fixture(t),u=await f.elevated('owner'),code='aabbccddeeff0011';
 f.db.prepare('UPDATE operator_security SET recovery_hashes=? WHERE user_id=?').run(JSON.stringify([await sha256(code)]),u.id);
 const data={password:'a long private test password',code};
 const results=await Promise.allSettled([call('POST /api/manage/unlock',f.context(u,data)),call('POST /api/manage/unlock',f.context(u,data))]);
 assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.equal(results.filter(r=>r.status==='rejected'&&r.reason.status===401).length,1);
});

test('member cannot manage; moderator cannot change settings or suspend owner',async t=>{
 const f=fixture(t),member=f.actor('member'),owner=await f.elevated('owner'),mod=await f.elevated('mod','moderator');
 await denied(call('GET /api/manage/overview',f.context(member,{},'GET')),403);
 await denied(call('GET /api/manage/settings',f.context(mod,{},'GET')),403);
 await denied(call('POST /api/manage/users/:target_id/actions',f.context(mod,{action:'suspend',reason:'Motivo de teste registrado'},'POST',{target_id:owner.id})),409);
 await denied(call('POST /api/manage/users/:target_id/actions',f.context(owner,{action:'suspend',reason:'Motivo de teste registrado'},'POST',{target_id:owner.id})),409);
});

test('suspending a member revokes sessions and tokens while preserving posts',async t=>{
 const f=fixture(t),owner=await f.elevated('owner'),member=f.actor('member');
 f.db.prepare("INSERT INTO posts(id,author_id,body,source,created_at) VALUES('post',?,'Hello','human',?)").run(member.id,new Date().toISOString());
 f.db.prepare("INSERT INTO auth_tokens VALUES('token',?,'reset',?,?)").run(member.id,Date.now()/1000+600,new Date().toISOString());
 await call('POST /api/manage/users/:target_id/actions',f.context(owner,{action:'suspend',reason:'Denúncia confirmada manualmente'},'POST',{target_id:member.id}));
 assert.equal(f.db.prepare('SELECT active FROM actors WHERE id=?').get(member.id).active,0);
 assert.equal(f.db.prepare('SELECT COUNT(*) n FROM sessions WHERE user_id=?').get(member.id).n,0);
 assert.equal(f.db.prepare('SELECT COUNT(*) n FROM auth_tokens WHERE user_id=?').get(member.id).n,0);
 assert.equal(f.db.prepare('SELECT COUNT(*) n FROM posts WHERE author_id=?').get(member.id).n,1);
});

test('policy content is escaped on public page and linked to reviewed hash',async t=>{
 const f=fixture(t),owner=await f.elevated('owner'),body='<script>alert("x")</script>\n\n'+'Texto da política revisada. '.repeat(20);
 await call('PUT /api/manage/policies/:kind',f.context(owner,{body,reviewed:true,reason:'Revisão do documento para a instalação'},'PUT',{kind:'terms'}));
 const response=await call('GET /termos',f.context(null,{},'GET',{},'/termos')),html=await response.text();
 assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>alert'));
 const review=f.db.prepare('SELECT * FROM policy_reviews').get();assert.equal(review.release,'1.0');assert.equal(review.body_hash,await sha256(body.trim()));
});

test('invitation listing never discloses code or hash and revocation is recorded',async t=>{
 const f=fixture(t),owner=await f.elevated('owner');
 const created=await call('POST /api/manage/invites',f.context(owner,{label:'Teste restrito',max_uses:2,days:7}));assert.match(created.code,/^[A-Za-z0-9_-]{43}$/);
 const listing=await call('GET /api/manage/invites',f.context(owner,{},'GET'));assert.equal(listing.items[0].available,true);assert.equal(listing.items[0].code,undefined);assert.equal(listing.items[0].code_hash,undefined);
 await call('POST /api/manage/invites/:invite_id/revoke',f.context(owner,{reason:'Encerramento do grupo de teste'},'POST',{invite_id:created.id}));
 assert.equal(f.db.prepare('SELECT revoked FROM pilot_invites').get().revoked,1);
});

test('moderation of a post is reversible and no unreported message is returned',async t=>{
 const f=fixture(t),owner=await f.elevated('owner'),member=f.actor('member'),other=f.actor('other');
 const at=new Date().toISOString();f.db.prepare("INSERT INTO posts(id,author_id,body,source,created_at) VALUES('post',?,'Reported post','human',?)").run(member.id,at);
 f.db.prepare("INSERT INTO reports(id,reporter_id,post_id,reason,created_at) VALUES('report',?,'post','Please review',?)").run(other.id,at);
 f.db.prepare("INSERT INTO messages(id,sender_id,recipient_id,body,created_at) VALUES('private',?,?,'PRIVATE UNREPORTED MESSAGE',?)").run(member.id,other.id,at);
 const list=await call('GET /api/manage/reports',f.context(owner,{},'GET'));assert.ok(!JSON.stringify(list).includes('PRIVATE UNREPORTED MESSAGE'));
 await call('POST /api/manage/reports/:report_id',f.context(owner,{action:'remove',reason:'Revisão do conteúdo denunciado'},'POST',{report_id:'report'}));
 assert.equal(f.db.prepare("SELECT hidden FROM posts WHERE id='post'").get().hidden,1);
 assert.equal(f.db.prepare("SELECT body FROM messages WHERE id='private'").get().body,'PRIVATE UNREPORTED MESSAGE');
 await denied(call('POST /api/manage/reports/:report_id',f.context(owner,{action:'dismiss',reason:'Outra decisão concorrente'},'POST',{report_id:'report'})),409);
 await call('POST /api/manage/posts/:post_id',f.context(owner,{hidden:false,reason:'Recurso aceito após nova revisão'},'POST',{post_id:'post'}));
 assert.equal(f.db.prepare("SELECT hidden FROM posts WHERE id='post'").get().hidden,0);
});
