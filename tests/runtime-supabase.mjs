import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,readdirSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
import {decryptSecret} from '../src/core.js';

// This exercises the bundled Worker and real D1 bindings locally. Every outbound
// request is intercepted; no Supabase project is mutated and no email is sent.
const build=spawnSync(process.execPath,['node_modules/wrangler/bin/wrangler.js','deploy','--dry-run','--outdir','.test-build-supabase'],{encoding:'utf8',env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
if(build.status!==0)throw Error(build.stderr||build.stdout);
const bindings={APP_ENV:'development',AGE_ENFORCED:'0',PUBLIC_ORIGIN:'http://localhost',
  AUTH_PROVIDER:'supabase',SUPABASE_URL:'https://abcdefghijklmnopqrst.supabase.co',
  SUPABASE_PUBLISHABLE_KEY:'sb_publishable_runtime_testing_only',SUPABASE_SECRET_KEY:'sb_secret_runtime_testing_only',
  ADMIN_ENCRYPTION_KEY:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  SETUP_TOKEN:'test-only-setup-token-over-32-characters',MAIL_FROM:'Synapse <test@example.test>'};
const remoteUsers=new Map();let requests=0,confirmations=0;
const outboundService=async request=>{
  requests++;
  const url=new URL(request.url),body=request.method==='GET'?{}:await request.json();
  assert.equal(url.origin,bindings.SUPABASE_URL);
  assert.equal(request.headers.get('authorization'),null);
  const admin=url.pathname.startsWith('/auth/v1/admin/');
  assert.equal(request.headers.get('apikey'),admin?bindings.SUPABASE_SECRET_KEY:bindings.SUPABASE_PUBLISHABLE_KEY);
  if(url.pathname==='/auth/v1/admin/users'&&request.method==='POST'){
    assert.equal(body.email_confirm,false);
    const user={id:body.id,email:body.email,password:body.password,email_confirmed_at:null};
    remoteUsers.set(user.id,user);return Response.json(user);
  }
  if(url.pathname==='/auth/v1/token'){
    assert.equal(url.searchParams.get('grant_type'),'password');
    const user=[...remoteUsers.values()].find(user=>user.email===body.email&&user.password===body.password);
    if(!user)return Response.json({code:'invalid_credentials'},{status:400});
    if(!user.email_confirmed_at)return Response.json({code:'email_not_confirmed'},{status:400});
    return Response.json({access_token:'runtime-only-access-token',refresh_token:'runtime-only-refresh-token',user});
  }
  const id=url.pathname.match(/^\/auth\/v1\/admin\/users\/([a-f0-9-]+)$/)?.[1];
  if(id){
    const user=remoteUsers.get(id);if(!user)return Response.json({code:'user_not_found'},{status:404});
    if(request.method==='GET')return Response.json(user);
    if(request.method==='PUT'){
      if(body.password)user.password=body.password;
      if(body.email_confirm){user.email_confirmed_at=new Date().toISOString();confirmations++;}
      return Response.json(user);
    }
    if(request.method==='DELETE'){remoteUsers.delete(id);return Response.json({});}
  }
  throw Error('Unrecognized mocked provider request: '+request.method+' '+url.pathname);
};
const mf=new Miniflare(convertV4MiniflareOptions({cf:false,host:'127.0.0.1',port:0,workers:[{
  name:'synapse-supabase-runtime',modules:true,scriptPath:'.test-build-supabase/index.js',
  compatibilityDate:'2026-10-28',compatibilityFlags:['nodejs_compat'],d1Databases:['DB'],r2Buckets:['MEDIA'],
  assets:{directory:'web',binding:'ASSETS',run_worker_first:true,routerConfig:{has_user_worker:true,invoke_user_worker_ahead_of_assets:true},assetConfig:{html_handling:'none',not_found_handling:'none'}},
  bindings,outboundService
}]}));
let passed=0;
try{
  const db=await mf.getD1Database('DB'),sql=new DatabaseSync(':memory:');
  for(const file of readdirSync('migrations').filter(file=>file.endsWith('.sql')).sort())sql.exec(readFileSync('migrations/'+file,'utf8'));
  for(const row of sql.prepare("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 1 WHEN 'index' THEN 2 ELSE 3 END").all())await db.prepare(row.sql).run();
  await db.prepare("INSERT INTO site_settings VALUES(1,0,0,1,'',?)").bind(new Date().toISOString()).run();sql.close();
  const req=(path,method='GET',body,session={})=>mf.dispatchFetch('http://localhost'+path,{method,headers:{
    'X-Synapse-Client':'web-v10','Content-Type':'application/json',
    ...(session.cookie?{'Cookie':session.cookie,'X-CSRF-Token':session.csrf}:{}),...(session.headers||{})
  },...(body===undefined?{}:{body:JSON.stringify(body)})});
  const check=async(response,status)=>{const body=await response.json();assert.equal(response.status,status,JSON.stringify(body));passed++;return body;};
  const account={name:'Runtime Owner',handle:'owner',email:'owner@example.test',password:'runtime owner private password'};
  await check(await req('/api/setup','POST',account),403);
  assert.equal(requests,0);
  const setup=await req('/api/setup','POST',account,{headers:{'X-Setup-Token':bindings.SETUP_TOKEN}});
  const setupBody=await check(setup,200);
  const owner={cookie:setup.headers.get('set-cookie').split(';')[0],csrf:setupBody.csrf};
  assert.equal(confirmations,0);assert.equal(remoteUsers.size,1);
  await check(await req('/api/auth/login','POST',{handle:'owner',password:account.password}),401);
  // Consume the actual encrypted verification mail generated by the Worker.
  const verification=await db.prepare("SELECT encrypted_message FROM mail_jobs WHERE purpose='verify' AND encrypted_message!='' LIMIT 1").first();
  const email=JSON.parse(await decryptSecret({env:bindings},verification.encrypted_message));
  const token=email.text.match(/#verify=([A-Za-z0-9_-]+)/)?.[1];assert.ok(token);
  await check(await req('/api/auth/verify','POST',{token}),200);
  assert.equal(confirmations,1);
  await check(await req('/api/auth/verify','POST',{token}),400);
  const login=await req('/api/auth/login','POST',{handle:'owner',password:account.password});
  const loginBody=await check(login,200),session={cookie:login.headers.get('set-cookie').split(';')[0],csrf:loginBody.csrf};
  assert.ok(session.cookie.startsWith('synapse_session='));assert.ok(!JSON.stringify(loginBody).includes('runtime-only-access-token'));
  const state=await check(await req('/api/state','GET',undefined,session),200);
  assert.equal(state.me.handle,'owner');assert.equal(state.site.registration_open,false);
  await check(await req('/api/manage/overview','GET',undefined,session),403);
  const password='runtime replacement private password';
  await check(await req('/api/account/password','PATCH',{current_password:account.password,password},session),200);
  await check(await req('/api/account/export','GET',undefined,session),401);
  await check(await req('/api/account/export','GET',undefined,owner),401);
  await check(await req('/api/auth/login','POST',{handle:'owner',password:account.password}),401);
  await check(await req('/api/auth/login','POST',{handle:'owner',password}),200);
  await check(await req('/api/auth/forgot','POST',{email:account.email}),200);
  const recovery=await db.prepare("SELECT encrypted_message FROM mail_jobs WHERE purpose='reset' AND encrypted_message!='' LIMIT 1").first();
  const recoveryEmail=JSON.parse(await decryptSecret({env:bindings},recovery.encrypted_message));
  const resetToken=recoveryEmail.text.match(/#reset=([A-Za-z0-9_-]+)/)?.[1];assert.ok(resetToken);
  await check(await req('/api/auth/reset','POST',{token:resetToken,password:'runtime recovered private password'}),200);
  await check(await req('/api/auth/reset','POST',{token:resetToken,password:'replay must fail private password'}),400);
  await check(await req('/api/auth/login','POST',{handle:'owner',password:'runtime recovered private password'}),200);
  console.log(JSON.stringify({runtime:'workerd + Miniflare D1/R2 + mocked Supabase',checks:passed,provider_requests:requests,result:'passed',external_network:false}));
}finally{await mf.dispose();}
