import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,existsSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
const build=spawnSync(process.execPath,['node_modules/wrangler/bin/wrangler.js','deploy','--dry-run','--outdir','.test-build'],{encoding:'utf8',env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
if(build.status!==0)throw Error(build.stderr||build.stdout);
const mf=new Miniflare(convertV4MiniflareOptions({cf:false,host:'127.0.0.1',port:0,workers:[{name:'synapse-runtime',modules:true,scriptPath:'.test-build/index.js',compatibilityDate:'2026-10-28',compatibilityFlags:['nodejs_compat'],d1Databases:['DB'],r2Buckets:['MEDIA'],assets:{directory:'web',binding:'ASSETS',run_worker_first:true,routerConfig:{has_user_worker:true,invoke_user_worker_ahead_of_assets:true},assetConfig:{html_handling:'none',not_found_handling:'none'}},bindings:{APP_ENV:'development',AGE_ENFORCED:'0',PUBLIC_ORIGIN:'http://localhost',ADMIN_ENCRYPTION_KEY:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',SETUP_TOKEN:'test-only-setup-token-over-32-characters',MAIL_FROM:'Synapse <test@example.test>'}}]}));
let passed=0;
try{
 const db=await mf.getD1Database('DB');const sql=new DatabaseSync(':memory:');sql.exec(readFileSync('migrations/0001_initial.sql','utf8'));for(const r of sql.prepare("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 1 WHEN 'index' THEN 2 ELSE 3 END").all())await db.prepare(r.sql).run();await db.prepare("INSERT INTO site_settings VALUES(1,0,0,1,'',?)").bind(new Date().toISOString()).run();sql.close();
 const req=async(path,method='GET',body,session={})=>{const h={'X-Synapse-Client':'web-v10','Content-Type':'application/json',...(session.cookie?{'Cookie':session.cookie,'X-CSRF-Token':session.csrf}:{}),...(session.headers||{})};return mf.dispatchFetch('http://localhost'+path,{method,headers:h,...(body===undefined?{}:{body:JSON.stringify(body)})});};
 const health=await req('/api/health');const hb=await health.text();assert.equal(health.status,200,hb);assert.equal(JSON.parse(hb).runtime,'cloudflare-workers');passed++;
 for(const path of ['/','/instalar','/admin','/conta/seguranca','/operacao','/bem-vindo']){const r=await req(path);assert.equal(r.status,200,path);assert.match(r.headers.get('content-type'),/text\/html/);assert.ok(r.headers.get('content-security-policy'));passed++;}
 const setup=await req('/api/setup','POST',{name:'Owner Test',handle:'owner',email:'owner@example.test',password:'test-owner-long-password'},{headers:{'X-Setup-Token':'test-only-setup-token-over-32-characters'}});const setupBody=await setup.json();assert.equal(setup.status,200,JSON.stringify(setupBody));const owner={cookie:setup.headers.get('set-cookie').split(';')[0],csrf:setupBody.csrf};passed++;
 const state=await (await req('/api/state','GET',undefined,owner)).json();assert.equal(state.me.handle,'owner');assert.equal(state.is_admin,true);assert.equal(state.site.registration_open,false);passed++;
 const login=await req('/api/auth/login','POST',{handle:'owner',password:'test-owner-long-password'});assert.equal(login.status,200,await login.text());passed++;
 const denied=await req('/api/posts','POST',{body:'csrf must block'},{cookie:owner.cookie,csrf:'bad'});assert.equal(denied.status,403);passed++;
 const postResponse=await req('/api/posts','POST',{body:'Worker runtime publication',media_ids:[]},owner);const post=await postResponse.json();assert.equal(postResponse.status,200,JSON.stringify(post));passed++;
 const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jv8cAAAAASUVORK5CYII=';
 // A generated valid JPEG exercises actual Workers crypto, codec and R2 binding.
 const jpeg=(await import('jpeg-js')).default.encode({width:1,height:1,data:Buffer.from([240,50,90,255])},80).data;
 const profile=await req('/api/profile','PATCH',{name:'Owner Test',bio:'Runtime test',color:'violet',interests:[],avatar_data:'data:image/jpeg;base64,'+Buffer.from(jpeg).toString('base64')},owner);assert.equal(profile.status,200,await profile.text());passed++;
 const s2=await (await req('/api/state','GET',undefined,owner)).json();const media=await req(s2.me.avatar_path,'GET',undefined,owner);assert.equal(media.status,200);assert.equal(media.headers.get('content-type'),'image/jpeg');assert.match(media.headers.get('cache-control'),/private/);passed++;
 const admin=await req('/api/manage/overview','GET',undefined,owner);assert.equal(admin.status,403);passed++;
 const end=await req('/api/auth/logout','POST',{},owner);assert.equal(end.status,200);assert.equal((await req('/api/account/export','GET',undefined,owner)).status,401);passed++;
 console.log(JSON.stringify({runtime:'workerd + Miniflare D1/R2',checks:passed,result:'passed'}));
}finally{await mf.dispose();}
