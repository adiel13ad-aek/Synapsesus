import {
  fail, uid, now, stamp, query, first, run, batch, json, text, safeURL,
  needUser, requireSocial, publicActor, canViewAuthor, visiblePost, blocked,
  settings, socialStatus, rate, log, persistImage, removeMedia, development,
} from './core.js';
import {launchReadiness} from './safety.js';

export const capabilities = () => ({gallery:true,video:false,push:false,calls:false,max_photos:6,max_video_mb:0,max_video_seconds:0});
const id = (value) => text(value,1,80,'Identificador');
const me = c => c.user?.id || '';
const colors = new Set(['blue','mint','violet','amber','rose']);
const color = value => colors.has(value) ? value : fail(422,'Cor inválida.');
const array = (value, max) => Array.isArray(value) && value.length <= max ? value : fail(422,'Lista inválida ou acima do limite.');
const changed = result => Number(result?.meta?.changes ?? result?.changes ?? 0);
const ready = async c => await socialStatus(c) === 'ready';
const allowedAuthor = `(a.account_private=0 OR a.id=? OR EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=a.id)) AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=? AND b.target_id=a.id) OR (b.target_id=? AND b.user_id=a.id))`;
const visibilityArgs = c => [me(c),me(c),me(c),me(c)];

async function actor(c, target) {
  const a=await first(c,"SELECT * FROM actors WHERE id=? AND active=1 AND kind='human'",id(target));
  if(!a)fail(404,'Perfil não encontrado.');
  return a;
}
async function actorView(c,a) {
  const result=publicActor(a);
  const canView=Object.hasOwn(a,'can_view')?!!a.can_view:await canViewAuthor(c,a.id,me(c));
  if(!canView) Object.assign(result,{bio:'',cover_path:'',avatar_path:'',website:'',interests:[],restricted:true});
  result.followers=Object.hasOwn(a,'followers')?Number(a.followers):Number((await first(c,'SELECT COUNT(*) n FROM follows WHERE target_id=?',a.id)).n);
  return result;
}
async function expandPosts(c,posts) {
  if(!posts.length)return posts;
  const ids=JSON.stringify(posts.map(p=>p.id));
  const media=await query(c,'SELECT id,post_id,kind,path,thumbnail,width,height,duration FROM media_assets WHERE post_id IN(SELECT value FROM json_each(?)) ORDER BY position',ids);
  const comments=await query(c,`SELECT * FROM (SELECT cm.*,ROW_NUMBER() OVER(PARTITION BY cm.post_id ORDER BY cm.created_at,cm.id) rn FROM comments cm JOIN actors a ON a.id=cm.author_id WHERE cm.post_id IN(SELECT value FROM json_each(?)) AND a.active=1 AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=? AND b.target_id=cm.author_id) OR (b.target_id=? AND b.user_id=cm.author_id))) WHERE rn<=100 ORDER BY created_at,id LIMIT 2000`,ids,me(c),me(c));
  const byId=new Map(posts.map(p=>[p.id,Object.assign(p,{media:[],comments:[]})]));
  for(const m of media){const owner=m.post_id;delete m.post_id;byId.get(owner)?.media.push(m);}
  for(const cm of comments){delete cm.rn;byId.get(cm.post_id)?.comments.push(cm);}
  return posts;
}
export function encodeCursor(p) {return btoa(p.created_at+'|'+p.id).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,'');}
export function decodeCursor(value) {
  try {
    if(typeof value!=='string'||value.length>250||!/^[A-Za-z0-9_-]+$/.test(value))throw new Error();
    const [date,pid,...rest]=atob(value.replaceAll('-','+').replaceAll('_','/')).split('|');
    if(rest.length||!date||date.length>40||!Number.isFinite(Date.parse(date))||!/^[A-Za-z0-9_-]{1,80}$/.test(pid))throw new Error();
    return [date,pid];
  } catch {fail(422,'Cursor inválido.');}
}
async function feed(c, requestedLimit, requestedKind) {
  if(!await ready(c))return {posts:[],actors:[],next_cursor:''};
  const limit=requestedLimit??Number(c.url.searchParams.get('limit')||25);
  if(!Number.isInteger(limit)||limit<1||limit>100)fail(422,'Limite inválido.');
  const kind=requestedKind??c.url.searchParams.get('kind')??'all';
  if(!['all','video','following','saved'].includes(kind))fail(422,'Filtro inválido.');
  const where=["a.kind='human'","a.active=1","p.hidden=0",allowedAuthor],args=visibilityArgs(c);
  const cursor=c.url.searchParams.get('cursor');
  if(cursor){const [date,pid]=decodeCursor(cursor);where.push('(p.created_at<? OR (p.created_at=? AND p.id<?))');args.push(date,date,pid);}
  if(kind==='video')where.push("EXISTS(SELECT 1 FROM media_assets m WHERE m.post_id=p.id AND m.kind='video')");
  if(kind==='following'){where.push('(p.author_id=? OR EXISTS(SELECT 1 FROM follows f WHERE f.user_id=? AND f.target_id=p.author_id))');args.push(me(c),me(c));}
  if(kind==='saved'){where.push('EXISTS(SELECT 1 FROM bookmarks b WHERE b.user_id=? AND b.post_id=p.id)');args.push(me(c));}
  const rows=await query(c,`SELECT p.*,(SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) likes,EXISTS(SELECT 1 FROM likes l WHERE l.post_id=p.id AND l.user_id=?) liked FROM posts p JOIN actors a ON a.id=p.author_id WHERE ${where.join(' AND ')} ORDER BY p.created_at DESC,p.id DESC LIMIT ?`,me(c),...args,limit+1);
  const posts=await expandPosts(c,rows.slice(0,limit));
  const authors=posts.length?await query(c,`SELECT a.*,(SELECT COUNT(*) FROM follows f WHERE f.target_id=a.id) followers,1 can_view FROM actors a WHERE a.id IN(SELECT DISTINCT value FROM json_each(?))`,JSON.stringify(posts.map(p=>p.author_id))):[];
  return {posts,actors:await Promise.all(authors.map(a=>actorView(c,a))),next_cursor:rows.length>limit?encodeCursor(rows[limit-1]):''};
}
async function stories(c) {
  if(!await ready(c))return [];
  return query(c,`SELECT s.* FROM stories s JOIN actors a ON a.id=s.author_id WHERE s.expires>? AND a.active=1 AND ${allowedAuthor} ORDER BY s.created_at DESC,s.id DESC LIMIT 100`,stamp(),...visibilityArgs(c));
}
async function notifications(c) {
  if(!c.user)return [];
  return query(c,`SELECT n.* FROM notifications n JOIN actors a ON a.id=n.actor_id WHERE n.user_id=? AND a.active=1 AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=? AND b.target_id=n.actor_id) OR (b.target_id=? AND b.user_id=n.actor_id)) ORDER BY n.created_at DESC,n.id DESC LIMIT 100`,me(c),me(c),me(c));
}
async function state(c) {
  const user=c.user, who=me(c), active=await ready(c), site=await settings(c);
  const registrationOpen=!!site.registration_open&&(development(c)||(await launchReadiness(c)).ready);
  const people=active?await query(c,`SELECT a.*,(SELECT COUNT(*) FROM follows f WHERE f.target_id=a.id) followers,(${allowedAuthor}) can_view FROM actors a WHERE a.kind='human' AND a.active=1 AND NOT EXISTS(SELECT 1 FROM blocks WHERE user_id=a.id AND target_id=?) ORDER BY a.created_at DESC LIMIT 300`,...visibilityArgs(c),who):user?[{...user,can_view:1,followers:0}]:[];
  const actors=[];for(const a of people)actors.push(await actorView(c,a));
  const timeline=active?await feed(c,100,'all'):{posts:[]};
  const operator=user?await first(c,'SELECT 1 present FROM operators WHERE user_id=?',who):null;
  return {version:'1.0.0-rc.1',mode:'server',search_provider:'external',onboarding:await socialStatus(c),
    me:user?publicActor(user):null,csrf:user?.csrf||'',actors,posts:timeline.posts,
    following:(await query(c,'SELECT target_id FROM follows WHERE user_id=?',who)).map(x=>x.target_id),
    pending_follows:(await query(c,'SELECT target_id FROM follow_requests WHERE requester_id=?',who)).map(x=>x.target_id),
    saved:(await query(c,'SELECT post_id FROM bookmarks WHERE user_id=?',who)).map(x=>x.post_id),
    blocked:(await query(c,'SELECT target_id FROM blocks WHERE user_id=?',who)).map(x=>x.target_id),
    links:user?await query(c,'SELECT * FROM web_links WHERE owner_id=? ORDER BY created_at DESC LIMIT 500',who):[],
    reports_count:user?Number((await first(c,'SELECT COUNT(*) n FROM reports WHERE reporter_id=?',who)).n):0,
    site:{registration_open:registrationOpen,maintenance:!!site.maintenance,uploads_enabled:!!site.uploads_enabled,announcement:site.announcement||''},
    preferences:user?Object.fromEntries(['theme','accent','reduce_motion','dm_policy'].map(k=>[k,user[k]])):{},
    account:user?{email:user.email,email_verified:!!user.email_verified}:null,is_admin:!!operator,
    mail_mode:user?'api':null,capabilities:capabilities(),stories:await stories(c),notifications:await notifications(c)};
}
async function uploadsEnabled(c, attempt=true) {
  if(attempt&&!(await settings(c)).uploads_enabled)fail(503,'O envio de arquivos está pausado.');
}
async function ownedAssets(c,post) {return query(c,'SELECT path,thumbnail FROM media_assets WHERE post_id=? AND owner_id=?',post,me(c));}
async function cleanAssets(c,assets) {for(const a of assets)for(const p of [a.path,a.thumbnail])if(p)await removeMedia(c,p);}
async function toggle(c,table) {
  const user=needUser(c);await requireSocial(c);await rate(c,table+':'+user.id,120,60);
  const post=await visiblePost(c,id(c.params.post_id));
  const old=await first(c,`SELECT 1 present FROM ${table} WHERE user_id=? AND post_id=?`,user.id,post.id);
  if(old)await run(c,`DELETE FROM ${table} WHERE user_id=? AND post_id=?`,user.id,post.id);
  else await run(c,`INSERT OR IGNORE INTO ${table}(user_id,post_id) VALUES(?,?)`,user.id,post.id);
  return {active:!old};
}
export default function register(router) {
  router.on('GET','/api/state',state);
  router.on('GET','/api/feed',async c=>{const lim=Number(c.url.searchParams.get('limit')||25);if(lim>50)fail(422,'Use até 50 publicações por página.');return feed(c,lim);});
  router.on('POST','/api/posts',async c=>{
    const user=needUser(c);await requireSocial(c);await rate(c,'post:'+user.id,20,3600);
    const data=await json(c),body=text(data.body,1,2000,'Legenda'),link=safeURL(data.link_url||'',true),title=text(data.link_title||'',0,180,'Título'),alt=text(data.image_alt||'',0,250,'Descrição');
    const ids=array(data.media_ids||[],6).map(x=>{if(typeof x!=='string'||!/^[a-f0-9]{32}$/.test(x))fail(422,'Arquivo inválido.');return x;});
    if(new Set(ids).size!==ids.length||data.image_data&&ids.length)fail(422,'Selecione fotos diferentes ou use uma única imagem.');
    await uploadsEnabled(c,!!data.image_data||ids.length>0);
    let image='';let committed=false;const pid=uid();
    try {
      if(data.image_data)image=await persistImage(c,data.image_data,user.id);
      const assets=ids.length?await query(c,`SELECT * FROM media_assets WHERE id IN (${ids.map(()=>'?').join(',')}) AND owner_id=? AND post_id IS NULL`,...ids,user.id):[];
      if(assets.length!==ids.length||assets.some(x=>x.kind!=='image'))fail(409,'Uma foto está indisponível ou já foi publicada.');
      const statements=[];
      const claim=ids.length?` AND (SELECT COUNT(*) FROM media_assets WHERE id IN (${ids.map(()=>'?').join(',')}) AND owner_id=? AND post_id IS NULL)=${ids.length}`:'';
      statements.push([`INSERT INTO posts(id,author_id,body,source,created_at,link_url,link_title,image_path,image_alt) SELECT ?,?,?,'human',?,?,?,?,? WHERE EXISTS(SELECT 1 FROM actors WHERE id=? AND active=1)${claim}`,pid,user.id,body,now(),link,title,image,alt,user.id,...ids,...(ids.length?[user.id]:[])]);
      ids.forEach((aid,position)=>statements.push(['UPDATE media_assets SET post_id=?,position=? WHERE id=? AND owner_id=? AND post_id IS NULL AND EXISTS(SELECT 1 FROM posts WHERE id=?)',pid,position,aid,user.id,pid]));
      const result=await batch(c,statements);committed=changed(result[0])>0;
      if(!committed)fail(409,'As fotos já foram usadas. Atualize a página.');
      return {id:pid};
    }catch(error){if(image&&!committed)await removeMedia(c,image);throw error;}
  });
  router.on('PATCH','/api/posts/:post_id',async c=>{
    const user=needUser(c);await requireSocial(c);const post=await visiblePost(c,id(c.params.post_id));
    if(post.author_id!==user.id)fail(403,'Você só pode editar suas publicações.');
    const d=await json(c);await run(c,'UPDATE posts SET body=?,image_alt=? WHERE id=? AND author_id=?',text(d.body,1,2000,'Legenda'),text(d.image_alt||'',0,250,'Descrição'),post.id,user.id);return {ok:true};
  });
  router.on('DELETE','/api/posts/:post_id',async c=>{
    const user=needUser(c),p=await first(c,'SELECT * FROM posts WHERE id=? AND author_id=?',id(c.params.post_id),user.id);
    if(!p)fail(404,'Publicação indisponível.');const assets=await ownedAssets(c,p.id);
    await run(c,'DELETE FROM posts WHERE id=? AND author_id=?',p.id,user.id);await cleanAssets(c,assets);if(p.image_path)await removeMedia(c,p.image_path);
    await log(c,user.id,'post_deleted',p.id,'Publicação removida.');return {ok:true};
  });
  router.on('POST','/api/posts/:post_id/like',c=>toggle(c,'likes'));
  router.on('POST','/api/posts/:post_id/save',c=>toggle(c,'bookmarks'));
  router.on('POST','/api/posts/:post_id/comments',async c=>{
    const u=needUser(c);await requireSocial(c);await rate(c,'comment:'+u.id,60,3600);const p=await visiblePost(c,id(c.params.post_id)),d=await json(c),cid=uid();
    await run(c,'INSERT INTO comments(id,post_id,author_id,body,created_at) VALUES(?,?,?,?,?)',cid,p.id,u.id,text(d.body,1,600,'Comentário'),now());return {id:cid};
  });
  router.on('DELETE','/api/comments/:comment_id',async c=>{
    const u=needUser(c),row=await first(c,'SELECT c.*,p.author_id post_owner FROM comments c JOIN posts p ON p.id=c.post_id WHERE c.id=?',id(c.params.comment_id));
    if(!row||![row.author_id,row.post_owner].includes(u.id))fail(404,'Comentário indisponível.');
    await run(c,'DELETE FROM comments WHERE id=?',row.id);return {ok:true};
  });
  router.on('PATCH','/api/profile',async c=>{
    const u=needUser(c);await requireSocial(c);const d=await json(c),name=text(d.name,2,50,'Nome'),bio=text(d.bio||'',0,300,'Biografia'),website=safeURL(d.website||'',true),col=color(d.color||'violet');
    const interests=array(d.interests||[],8).map(x=>text(x,1,30,'Interesse'));
    await uploadsEnabled(c,!!(d.avatar_data||d.cover_data));let avatar='',cover='',committed=false;
    try {
      if(d.avatar_data)avatar=await persistImage(c,d.avatar_data,u.id);if(d.cover_data)cover=await persistImage(c,d.cover_data,u.id);
      const a=await actor(c,u.id),nextAvatar=avatar||(d.remove_avatar===true?'':a.avatar_path),nextCover=cover||(d.remove_cover===true?'':a.cover_path);
      const obsolete=[[a.avatar_path,nextAvatar],[a.cover_path,nextCover]].filter(([old,next])=>old&&old!==next).map(([old])=>old);
      await batch(c,[['UPDATE actors SET name=?,bio=?,website=?,color=?,interests=?,avatar_path=?,cover_path=? WHERE id=?',name,bio,website,col,JSON.stringify(interests),nextAvatar,nextCover,u.id],...obsolete.map(path=>['INSERT OR IGNORE INTO media_cleanup(path,created_at) VALUES(?,?)',path,now()])]);committed=true;
      for(const old of obsolete){try{await removeMedia(c,old);}catch{/* durable cleanup queue retries */}}
      return {ok:true};
    }catch(error){if(!committed){if(avatar)await removeMedia(c,avatar);if(cover)await removeMedia(c,cover);}throw error;}
  });
  router.on('POST','/api/actors/:target_id/follow',async c=>{
    const u=needUser(c);await requireSocial(c);await rate(c,'follow:'+u.id,30,3600);const target=await actor(c,c.params.target_id);
    if(target.id===u.id||await blocked(c,u.id,target.id))fail(400,'Não é possível seguir esse perfil.');
    const existing=await first(c,'SELECT 1 present FROM follows WHERE user_id=? AND target_id=?',u.id,target.id),pending=await first(c,'SELECT 1 present FROM follow_requests WHERE requester_id=? AND target_id=?',u.id,target.id);
    let status='none';
    if(existing)await run(c,'DELETE FROM follows WHERE user_id=? AND target_id=?',u.id,target.id);
    else if(pending)await run(c,'DELETE FROM follow_requests WHERE requester_id=? AND target_id=?',u.id,target.id);
    else if(target.account_private){await run(c,'INSERT OR IGNORE INTO follow_requests(requester_id,target_id,created_at) VALUES(?,?,?)',u.id,target.id,now());status='pending';}
    else {await run(c,'INSERT OR IGNORE INTO follows(user_id,target_id) SELECT ?,? WHERE EXISTS(SELECT 1 FROM actors WHERE id=? AND active=1 AND account_private=0)',u.id,target.id,target.id);status='following';}
    return {active:status==='following',pending:status==='pending',status};
  });
  router.on('POST','/api/actors/:target_id/block',async c=>{
    const u=needUser(c),a=await actor(c,c.params.target_id);if(a.id===u.id)fail(400,'Você não pode bloquear a própria conta.');
    const old=await first(c,'SELECT 1 present FROM blocks WHERE user_id=? AND target_id=?',u.id,a.id);
    if(old)await run(c,'DELETE FROM blocks WHERE user_id=? AND target_id=?',u.id,a.id);
    else await batch(c,[['INSERT OR IGNORE INTO blocks(user_id,target_id) VALUES(?,?)',u.id,a.id],['DELETE FROM follows WHERE (user_id=? AND target_id=?) OR (user_id=? AND target_id=?)',u.id,a.id,a.id,u.id],['DELETE FROM follow_requests WHERE (requester_id=? AND target_id=?) OR (requester_id=? AND target_id=?)',u.id,a.id,a.id,u.id]]);
    return {active:!old};
  });
  router.on('GET','/api/messages/:target_id',async c=>{
    const u=needUser(c);await requireSocial(c);const a=await actor(c,c.params.target_id);if(await blocked(c,u.id,a.id))fail(403,'Conversa bloqueada.');
    return {messages:await query(c,`SELECT id,sender_id,recipient_id,body,source,model,created_at FROM (SELECT rowid sequence,* FROM messages WHERE (sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?) ORDER BY created_at DESC,rowid DESC LIMIT 100) ORDER BY created_at,sequence`,u.id,a.id,a.id,u.id)};
  });
  router.on('POST','/api/messages/:target_id',async c=>{
    const u=needUser(c);await requireSocial(c);await rate(c,'message:'+u.id,20,60);const a=await actor(c,c.params.target_id),d=await json(c),body=text(d.body,1,1500,'Mensagem');
    if(a.id===u.id||a.seeded||await blocked(c,u.id,a.id))fail(403,'Não é possível enviar a esse perfil.');
    if(a.dm_policy==='off'||a.dm_policy==='following'&&!await first(c,'SELECT 1 present FROM follows WHERE user_id=? AND target_id=?',a.id,u.id))fail(403,'Este perfil não permite mensagens da sua conta.');
    if(!development(c)&&(!a.email_verified||a.age_band!=='adult'||a.age_verified_until<=stamp()))fail(403,'Este perfil não está disponível para mensagens.');
    await run(c,"INSERT INTO messages(id,sender_id,recipient_id,body,source,created_at) VALUES(?,?,?,?,'human',?)",uid(),u.id,a.id,body,now());return {ok:true};
  });
  router.on('POST','/api/links',async c=>{
    const u=needUser(c);await requireSocial(c);const d=await json(c),url=safeURL(d.url),title=text(d.title,1,180,'Título'),collection=text(d.collection||'Favoritos',1,50,'Coleção'),note=text(d.note||'',0,600,'Nota');
    const old=await first(c,'SELECT id FROM web_links WHERE owner_id=? AND url=?',u.id,url),lid=old?.id||uid();
    if(old)await run(c,'UPDATE web_links SET title=?,collection=?,note=? WHERE id=? AND owner_id=?',title,collection,note,lid,u.id);
    else {const r=await run(c,'INSERT INTO web_links(id,owner_id,url,title,collection,note,created_at) SELECT ?,?,?,?,?,?,? WHERE (SELECT COUNT(*) FROM web_links WHERE owner_id=?)<500',lid,u.id,url,title,collection,note,now(),u.id);if(!changed(r))fail(409,'Limite de 500 links por conta.');}
    return {id:lid,updated:!!old};
  });
  router.on('DELETE','/api/links/:link_id',async c=>{const u=needUser(c);if(!changed(await run(c,'DELETE FROM web_links WHERE id=? AND owner_id=?',id(c.params.link_id),u.id)))fail(404,'Link não encontrado.');return {ok:true};});
  router.on('GET','/api/stories',async c=>({stories:await stories(c)}));
  router.on('POST','/api/stories',async c=>{
    const u=needUser(c);await requireSocial(c);await rate(c,'story:'+u.id,10,3600);const d=await json(c),body=text(d.body,1,280,'Story'),col=color(d.color||'violet');await uploadsEnabled(c,!!d.image_data);
    let image='';const sid=uid();try{if(d.image_data)image=await persistImage(c,d.image_data,u.id);await run(c,'INSERT INTO stories(id,author_id,body,image_path,color,created_at,expires) VALUES(?,?,?,?,?,?,?)',sid,u.id,body,image,col,now(),stamp()+86400);return {id:sid};}catch(e){if(image)await removeMedia(c,image);throw e;}
  });
  router.on('DELETE','/api/stories/:story_id',async c=>{const u=needUser(c),s=await first(c,'SELECT * FROM stories WHERE id=? AND author_id=?',id(c.params.story_id),u.id);if(!s)fail(404,'Story não encontrado.');await run(c,'DELETE FROM stories WHERE id=?',s.id);if(s.image_path)await removeMedia(c,s.image_path);return {ok:true};});
  router.on('GET','/api/notifications',async c=>({notifications:await notifications(c)}));
  router.on('POST','/api/notifications/read',async c=>{const u=needUser(c);await run(c,'UPDATE notifications SET seen=1 WHERE user_id=?',u.id);return {ok:true};});
  router.on('POST','/api/posts/:post_id/report',async c=>{
    const u=needUser(c);await rate(c,'report:'+u.id,15,3600);const p=await visiblePost(c,id(c.params.post_id)),d=await json(c);
    await run(c,'INSERT INTO reports(id,reporter_id,post_id,reason,created_at) VALUES(?,?,?,?,?)',uid(),u.id,p.id,text(d.reason,3,500,'Motivo'),now());return {ok:true};
  });
  router.on('POST','/api/reports',async c=>{
    const u=needUser(c);await rate(c,'report:'+u.id,15,3600);const d=await json(c),table={profile:'actors',story:'stories',comment:'comments',message:'messages'}[d.kind];if(!table)fail(422,'Tipo de denúncia inválido.');
    const target=id(d.target_id),row=await first(c,`SELECT * FROM ${table} WHERE id=?`,target);if(!row)fail(404,'Conteúdo não encontrado.');
    if(d.kind==='message'&&![row.sender_id,row.recipient_id].includes(u.id))fail(404,'Conteúdo não encontrado.');
    if(d.kind==='comment')await visiblePost(c,row.post_id);
    if(d.kind==='story'&&(row.expires<=stamp()||!await canViewAuthor(c,row.author_id,u.id)))fail(404,'Conteúdo não encontrado.');
    if(d.kind==='profile'&&(!row.active||row.kind!=='human'))fail(404,'Perfil não encontrado.');
    await run(c,'INSERT INTO content_reports(id,reporter_id,kind,target_id,reason,status,created_at) VALUES(?,?,?,?,?,?,?)',uid(),u.id,d.kind,target,text(d.reason,3,500,'Motivo'),'open',now());return {ok:true};
  });
  router.on('POST','/api/media/uploads',async c=>{
    const u=needUser(c);await requireSocial(c);await uploadsEnabled(c);await rate(c,'uploads:'+u.id,12,600);
    const declared=Number(c.request.headers.get('content-length')||0);if(declared>3*1024*1024+65536)fail(413,'A foto deve ter até 3 MB.');
    const form=await c.request.formData(),file=form.get('file');
    if(!file||typeof file.arrayBuffer!=='function'||file.size===0||file.size>3*1024*1024||!['image/jpeg','image/png'].includes(file.type))fail(422,'Envie uma foto JPEG ou PNG de até 3 MB. Vídeos ainda não estão disponíveis nesta edição.');
    const bytes=new Uint8Array(await file.arrayBuffer());let bin='';for(let i=0;i<bytes.length;i+=16384)bin+=String.fromCharCode(...bytes.subarray(i,i+16384));
    const path=await persistImage(c,`data:${file.type};base64,${btoa(bin)}`,u.id);
    const item=await first(c,'SELECT id,kind,path,thumbnail,bytes,width,height,duration FROM media_assets WHERE owner_id=? AND path=?',u.id,path);
    if(!item){await removeMedia(c,path);fail(500,'Não foi possível registrar a foto.');}return item;
  });
  router.on('DELETE','/api/media/uploads/:asset_id',async c=>{
    const u=needUser(c),a=await first(c,'SELECT * FROM media_assets WHERE id=? AND owner_id=? AND post_id IS NULL',id(c.params.asset_id),u.id);
    if(!a)fail(404,'Arquivo indisponível ou já publicado.');
    const used=await first(c,'SELECT 1 used FROM actors WHERE avatar_path=? OR cover_path=? UNION ALL SELECT 1 FROM stories WHERE image_path=? UNION ALL SELECT 1 FROM posts WHERE image_path=? LIMIT 1',a.path,a.path,a.path,a.path);
    if(used)fail(409,'O arquivo já está em uso.');
    const claimed=await first(c,`DELETE FROM media_assets WHERE id=? AND owner_id=? AND post_id IS NULL AND NOT EXISTS(SELECT 1 FROM actors WHERE avatar_path=? OR cover_path=?) AND NOT EXISTS(SELECT 1 FROM stories WHERE image_path=?) AND NOT EXISTS(SELECT 1 FROM posts WHERE image_path=?) RETURNING path`,a.id,u.id,a.path,a.path,a.path,a.path);
    if(!claimed)fail(409,'O arquivo foi publicado. Atualize a página.');await removeMedia(c,claimed.path);return {ok:true};
  });
  router.on('GET','/media/:filename',serveMedia);
  router.on('HEAD','/media/:filename',serveMedia);
  router.on('GET','/api/search',search);
  router.on('GET','/api/push/config',async c=>{needUser(c);return {enabled:false,public_key:''};});
  router.on('DELETE','/api/push/subscriptions',async c=>{const u=needUser(c),d=await json(c);await run(c,'DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?',u.id,text(d.endpoint,1,2048,'Endereço'));return {ok:true};});
  router.on('POST','/api/push/subscriptions',async c=>{needUser(c);fail(503,'Notificações de dispositivo não estão disponíveis nesta edição.');});
  router.on('GET','/api/calls',async c=>{needUser(c);return {calls:[],enabled:false};});
}
async function serveMedia(c) {
  needUser(c);await requireSocial(c);const filename=c.params.filename;
  if(!/^[a-f0-9]{32}\.(jpg|png|webp|mp4)$/.test(filename))fail(404,'Arquivo não encontrado.');
  const path='/media/'+filename,asset=await first(c,'SELECT m.*,a.active FROM media_assets m JOIN actors a ON a.id=m.owner_id WHERE m.path=? OR m.thumbnail=?',path,path);
  let visible=false;
  if(asset?.active){if(asset.post_id){await visiblePost(c,asset.post_id);visible=true;}else if(asset.owner_id===me(c))visible=true;}
  if(!visible){for(const a of await query(c,'SELECT id FROM actors WHERE active=1 AND (avatar_path=? OR cover_path=?)',path,path))if(await canViewAuthor(c,a.id,me(c))){visible=true;break;}}
  if(!visible){for(const p of await query(c,'SELECT id,author_id FROM posts WHERE image_path=? AND hidden=0',path))if(await canViewAuthor(c,p.author_id,me(c))){visible=true;break;}}
  if(!visible){for(const s of await query(c,'SELECT author_id FROM stories WHERE image_path=? AND expires>?',path,stamp()))if(await canViewAuthor(c,s.author_id,me(c))){visible=true;break;}}
  if(!visible)fail(404,'Arquivo não encontrado.');
  const object=await c.env.MEDIA.get(filename);if(!object)fail(404,'Arquivo não encontrado.');
  const type={jpg:'image/jpeg',png:'image/png',webp:'image/webp',mp4:'video/mp4'}[filename.split('.').at(-1)];
  const headers=new Headers({'Content-Type':type,'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Disposition':'inline','Content-Length':String(object.size)});
  return new Response(c.request.method==='HEAD'?null:object.body,{headers});
}
async function search(c) {
  const q=text(c.url.searchParams.get('q'),1,200,'Pesquisa'),scope=c.url.searchParams.get('scope')||'social';
  if(!['social','people','web','wiki'].includes(scope))fail(422,'Tipo de pesquisa inválido.');
  await rate(c,'search:'+(me(c)||c.request.headers.get('cf-connecting-ip')||'anonymous'),40,60);
  const esc=encodeURIComponent(q),shortcuts=[{name:'Google',url:'https://www.google.com/search?q='+esc},{name:'Brave',url:'https://search.brave.com/search?q='+esc},{name:'DuckDuckGo',url:'https://duckduckgo.com/?q='+esc}];
  if(['web','wiki'].includes(scope))return {query:q,scope,provider:'external',results:[],shortcuts:scope==='wiki'?[{name:'Wikipédia',url:'https://pt.wikipedia.org/w/index.php?search='+esc},...shortcuts]:shortcuts,notice:'Abra a pesquisa no serviço escolhido. A pesquisa integrada não está habilitada nesta edição.'};
  if(!await ready(c))return {query:q,scope,posts:[],people:[],results:[],provider:'synapse',shortcuts};
  const needle='%'+q.replaceAll('\\','\\\\').replaceAll('%','\\%').replaceAll('_','\\_')+'%';
  const rows=await query(c,`SELECT a.*,(SELECT COUNT(*) FROM follows f WHERE f.target_id=a.id) followers,(${allowedAuthor}) can_view FROM actors a WHERE a.active=1 AND a.kind='human' AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=? AND b.target_id=a.id) OR (b.target_id=? AND b.user_id=a.id)) AND (a.name LIKE ? ESCAPE '\\' OR a.handle LIKE ? ESCAPE '\\' OR ((${allowedAuthor}) AND a.bio LIKE ? ESCAPE '\\')) ORDER BY a.created_at DESC LIMIT 30`,...visibilityArgs(c),me(c),me(c),needle,needle,...visibilityArgs(c),needle);
  const people=[];for(const a of rows)people.push(await actorView(c,a));const posts=[];
  if(scope==='social')for(const p of await query(c,`SELECT p.*,(SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) likes,EXISTS(SELECT 1 FROM likes l WHERE l.post_id=p.id AND l.user_id=?) liked FROM posts p JOIN actors a ON a.id=p.author_id WHERE a.active=1 AND a.kind='human' AND p.hidden=0 AND ${allowedAuthor} AND (p.body LIKE ? ESCAPE '\\' OR p.link_title LIKE ? ESCAPE '\\') ORDER BY p.created_at DESC LIMIT 30`,me(c),...visibilityArgs(c),needle,needle)){posts.push(p);}
  await expandPosts(c,posts);return {query:q,scope,posts,people,results:[],provider:'synapse',shortcuts};
}
