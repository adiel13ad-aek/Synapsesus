import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import jpeg from 'jpeg-js';
import register,{decodeCursor,encodeCursor} from '../src/social.js';

function fixture(){
  const sql=new DatabaseSync(':memory:');sql.exec(readFileSync(new URL('../migrations/0001_initial.sql',import.meta.url),'utf8'));
  let calls=0;const objects=new Map();
  const DB={prepare(statement){return {bind(...args){return {
    async all(){calls++;return {results:sql.prepare(statement).all(...args)};},
    async first(){calls++;return sql.prepare(statement).get(...args)||null;},
    async run(){calls++;const r=sql.prepare(statement).run(...args);return {success:true,meta:{changes:Number(r.changes)}};},
  };}};},async batch(items){sql.exec('BEGIN IMMEDIATE');try{const r=[];for(const s of items)r.push(await s.run());sql.exec('COMMIT');return r;}catch(e){sql.exec('ROLLBACK');throw e;}}};
  const MEDIA={async put(key,data,meta){objects.set(key,{bytes:new Uint8Array(data),meta});},async get(key){const x=objects.get(key);return x?{size:x.bytes.length,body:x.bytes}:null;},async delete(key){objects.delete(key);}};
  const routes=[];register({on(method,path,handler){routes.push({method,path,handler});}});
  const add=(id,extra={})=>{sql.prepare("INSERT INTO actors(id,handle,name,kind,created_at,email,email_verified,age_band,age_verified_until,terms_version,dm_policy,account_private) VALUES(?,?,?,'human',?,?,1,'adult',?,'accepted','following',?)").run(id,id,'Pessoa '+id,new Date().toISOString(),id+'@example.com',Date.now()/1000+86400,extra.private?1:0);return sql.prepare('SELECT * FROM actors WHERE id=?').get(id);};
  const get=id=>sql.prepare('SELECT * FROM actors WHERE id=?').get(id);
  const request=async(method,path,user,data,envExtra={})=>{
    const url=new URL(path,'http://localhost');let found,params={};
    for(const route of routes){if(route.method!==method)continue;const keys=[];const pattern=route.path.replace(/:([^/]+)/g,(_,key)=>{keys.push(key);return '([^/]+)';});const m=url.pathname.match(new RegExp('^'+pattern+'$'));if(m){found=route;params=Object.fromEntries(keys.map((k,i)=>[k,m[i+1]]));break;}}
    if(!found)throw Error('Unknown route '+path);
    const req=new Request(url,{method,headers:data instanceof FormData?{}:{'Content-Type':'application/json'},...(data===undefined?{}:{body:data instanceof FormData?data:JSON.stringify(data)})});
    const c={request:req,url,params,user:typeof user==='string'?get(user):user,headers:new Headers(),env:{DB,MEDIA,APP_ENV:'development',AGE_ENFORCED:'0',...envExtra},ctx:{waitUntil(){}}};
    return found.handler(c);
  };
  return {sql,add,get,request,objects,MEDIA,close:()=>sql.close(),calls:()=>calls,resetCalls:()=>calls=0};
}
const rejectsStatus=(p,status)=>assert.rejects(p,e=>e.status===status);
const dataURI=()=>{const bytes=jpeg.encode({width:2,height:2,data:Buffer.from([255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255])},80).data;return 'data:image/jpeg;base64,'+bytes.toString('base64');};

test('cursors validate structure and round trip',()=>{
  const p={created_at:'2026-10-28T12:00:00.000Z',id:'a'.repeat(32)};
  assert.deepEqual(decodeCursor(encodeCursor(p)),[p.created_at,p.id]);
  for(const value of ['!','x'.repeat(251),btoa('wrong|id'),btoa('2026-10-28|id|extra')])assert.throws(()=>decodeCursor(value),e=>e.status===422);
});
test('private profile content stays protected across feed, search, stories and media',async t=>{
  const f=fixture();t.after(f.close);f.add('alice',{private:true});f.add('bob');
  const p=await f.request('POST','/api/posts','alice',{body:'Private discovery',image_data:dataURI()});
  await f.request('POST','/api/stories','alice',{body:'Private story'});
  const media=f.sql.prepare('SELECT image_path FROM posts WHERE id=?').get(p.id).image_path;
  assert.equal((await f.request('GET','/api/feed','bob')).posts.length,0);
  assert.equal((await f.request('GET','/api/stories','bob')).stories.length,0);
  assert.equal((await f.request('GET','/api/search?q=Private','bob')).posts.length,0);
  await rejectsStatus(f.request('GET',media,'bob'),404);
  assert.equal((await f.request('POST','/api/actors/alice/follow','bob',{})).pending,true);
  assert.equal((await f.request('GET','/api/feed','bob')).posts.length,0);
  f.sql.prepare('INSERT INTO follows VALUES(?,?)').run('bob','alice');
  assert.equal((await f.request('GET','/api/feed','bob')).posts.length,1);
  assert.equal((await f.request('GET',media,'bob')).status,200);
  f.sql.prepare('DELETE FROM follows WHERE user_id=? AND target_id=?').run('bob','alice');
  await rejectsStatus(f.request('GET',media,'bob'),404);
  await rejectsStatus(f.request('POST',`/api/posts/${p.id}/like`,'bob',{}),404);
});
test('gallery attachments cannot be stolen or reused, and JPEGs use private R2',async t=>{
  const f=fixture();t.after(f.close);f.add('alice');f.add('bob');
  const form=new FormData();form.set('file',new Blob([Buffer.from(dataURI().split(',')[1],'base64')],{type:'image/jpeg'}),'photo.jpg');
  const upload=await f.request('POST','/api/media/uploads','alice',form);
  assert.equal(upload.kind,'image');assert.equal(f.objects.size,1);
  await rejectsStatus(f.request('GET',upload.path,null),401);
  await rejectsStatus(f.request('GET',upload.path,'bob'),404);
  const response=await f.request('GET',upload.path,'alice');assert.equal(response.headers.get('cache-control'),'private, no-store');
  await rejectsStatus(f.request('POST','/api/posts','bob',{body:'stolen',media_ids:[upload.id]}),409);
  assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM posts').get().n,0);
  const p=await f.request('POST','/api/posts','alice',{body:'my photo',media_ids:[upload.id]});
  await rejectsStatus(f.request('POST','/api/posts','alice',{body:'reused',media_ids:[upload.id]}),409);
  await rejectsStatus(f.request('DELETE','/api/media/uploads/'+upload.id,'alice'),404);
  assert.equal((await f.request('GET','/api/state','bob')).posts[0].media[0].id,upload.id);
  await f.request('DELETE','/api/posts/'+p.id,'alice');assert.equal(f.objects.size,0);
});
test('message policies, blocks and report ownership prevent reading or reporting other conversations',async t=>{
  const f=fixture();t.after(f.close);f.add('alice');f.add('bob');f.add('eve');
  await rejectsStatus(f.request('POST','/api/messages/bob','alice',{body:'hello'}),403);
  f.sql.prepare('INSERT INTO follows VALUES(?,?)').run('bob','alice');
  await f.request('POST','/api/messages/bob','alice',{body:'hello'});
  const messages=(await f.request('GET','/api/messages/alice','bob')).messages;assert.equal(messages.length,1);
  assert.equal((await f.request('GET','/api/messages/alice','eve')).messages.length,0);
  await rejectsStatus(f.request('POST','/api/reports','eve',{kind:'message',target_id:messages[0].id,reason:'third party'}),404);
  await f.request('POST','/api/reports','bob',{kind:'message',target_id:messages[0].id,reason:'recipient report'});
  await f.request('POST','/api/actors/alice/block','bob',{});
  await rejectsStatus(f.request('GET','/api/messages/alice','bob'),403);
  await rejectsStatus(f.request('POST','/api/messages/bob','alice',{body:'blocked'}),403);
  assert.equal(f.sql.prepare('SELECT COUNT(*) n FROM follows').get().n,0);
});
test('state/feed queries stay bounded with 300 profiles and 100 posts',async t=>{
  const f=fixture();t.after(f.close);f.add('viewer');
  const insert=f.sql.prepare("INSERT INTO posts(id,author_id,body,source,created_at) VALUES(?,?,?,'human',?)");
  for(let i=0;i<300;i++){f.add('p'+i);if(i<100)insert.run('post'+i,'p'+i,'Discovery '+i,'2026-10-28T12:00:00.000Z');}
  f.resetCalls();const s=await f.request('GET','/api/state','viewer');
  assert.equal(s.posts.length,100);assert.equal(s.actors.length,300);assert.ok(f.calls()<35,`Used ${f.calls()} queries`);
  assert.equal(s.me.email,undefined);assert.equal(s.actors.some(a=>'password_hash'in a||'email'in a),false);
  const first=await f.request('GET','/api/feed?limit=10','viewer');assert.equal(first.posts.length,10);assert.ok(first.next_cursor);
  const next=await f.request('GET','/api/feed?limit=10&cursor='+first.next_cursor,'viewer');
  assert.equal(next.posts.length,10);assert.equal(next.posts.some(p=>first.posts.some(x=>x.id===p.id)),false);
  const results=await f.request('GET','/api/search?q=Discovery','viewer');assert.equal(results.posts.length,30);
});
test('unverified production users cannot use alternate social entry points',async t=>{
  const f=fixture();t.after(f.close);f.add('alice');f.add('bob');
  const p=await f.request('POST','/api/posts','alice',{body:'Public content'});
  f.sql.prepare('UPDATE actors SET email_verified=0 WHERE id=?').run('bob');
  const env={APP_ENV:'production'};
  assert.equal((await f.request('GET','/api/state','bob',undefined,env)).posts.length,0);
  assert.equal((await f.request('GET','/api/feed','bob',undefined,env)).posts.length,0);
  assert.equal((await f.request('GET','/api/search?q=Public','bob',undefined,env)).posts.length,0);
  await rejectsStatus(f.request('POST',`/api/posts/${p.id}/like`,'bob',{},env),403);
});
test('ownership, deletion, links and notifications follow persisted SQLite state',async t=>{
  const f=fixture();t.after(f.close);f.add('alice');f.add('bob');
  const p=await f.request('POST','/api/posts','alice',{body:'hello'});
  await rejectsStatus(f.request('PATCH','/api/posts/'+p.id,'bob',{body:'stolen'}),403);
  const comment=await f.request('POST','/api/posts/'+p.id+'/comments','bob',{body:'nice'});
  assert.equal((await f.request('GET','/api/notifications','alice')).notifications.length,1);
  await f.request('POST','/api/notifications/read','alice',{});
  assert.equal((await f.request('GET','/api/notifications','alice')).notifications[0].seen,1);
  await f.request('DELETE','/api/comments/'+comment.id,'alice');
  const link=await f.request('POST','/api/links','alice',{url:'https://example.com',title:'Example'});
  await rejectsStatus(f.request('DELETE','/api/links/'+link.id,'bob'),404);
  assert.equal((await f.request('GET','/api/state','bob')).links.length,0);
  await f.request('DELETE','/api/links/'+link.id,'alice');
  await f.request('PATCH','/api/profile','alice',{name:'Novo nome',bio:'bio',interests:['tech'],color:'blue'});
  assert.equal(f.get('alice').name,'Novo nome');
});

test('profile updates retain new media when old object cleanup temporarily fails',async t=>{
  const f=fixture();t.after(f.close);f.add('alice');
  await f.request('PATCH','/api/profile','alice',{name:'Alice',avatar_data:dataURI()});
  const old=f.get('alice').avatar_path;
  f.MEDIA.delete=async key=>{if(key===old.slice(7))throw Error('temporary R2 failure');f.objects.delete(key);};
  await f.request('PATCH','/api/profile','alice',{name:'Alice Updated',avatar_data:dataURI()});
  const current=f.get('alice').avatar_path;assert.notEqual(current,old);
  assert.ok(f.objects.has(current.slice(7)));
  assert.ok(f.sql.prepare('SELECT path FROM media_cleanup WHERE path=?').get(old));
});
test('public state never advertises open registration with incomplete production readiness',async t=>{
  const f=fixture();t.after(f.close);f.add('alice');f.sql.exec('UPDATE site_settings SET registration_open=1');
  const s=await f.request('GET','/api/state','alice',undefined,{APP_ENV:'production',PUBLIC_ORIGIN:'https://example.com'});
  assert.equal(s.site.registration_open,false);
});
