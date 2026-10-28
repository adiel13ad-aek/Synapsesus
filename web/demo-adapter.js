/* Offline demo adapter. No authentication, no real users, no AI, no fake web results. */
(()=>{'use strict';
if(document.documentElement.dataset.mode!=='demo')return;
const KEY='synapse.discovery.v06';
const id=()=>Math.random().toString(36).slice(2)+Date.now().toString(36);
const now=()=>new Date().toISOString();
const fold=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
let temporary=false;
function initial(){
 const stamp=now();
 const actors=[
 {id:'synapse',name:'Equipe Synapse',handle:'synapse',bio:'Um lugar para pessoas curiosas. Perfil editorial fictício.',color:'mint',seeded:1,interests:['Fotografia','Natureza']},
 {id:'lia',name:'Lia Martins',handle:'lia.cria',bio:'Design, arquitetura e um olhar para os detalhes. Perfil editorial fictício.',color:'rose',seeded:1,interests:['Design','Arquitetura']},
 {id:'caio',name:'Caio Costa',handle:'caio.explora',bio:'Um universo inteiro para descobrir. Perfil editorial fictício.',color:'blue',seeded:1,interests:['Ciência','Universo']},
 {id:'nina',name:'Nina Alves',handle:'nina.olhares',bio:'Pausas, cores e pequenas descobertas. Perfil editorial fictício.',color:'rose',seeded:1,interests:['Fotografia','Natureza']},
 {id:'leo',name:'Leo Nunes',handle:'leo.horizontes',bio:'Tecnologia, possibilidades e boas perguntas. Perfil editorial fictício.',color:'amber',seeded:1,interests:['Tecnologia','Ciência']},
 {id:'demo-me',name:'Você',handle:'voce',bio:'Colecionando momentos e novas perspectivas.',color:'violet',seeded:0,interests:['Fotografia','Criatividade']}
 ].map(a=>({...a,kind:'human',followers:0,created_at:stamp,avatar_path:'',cover_path:'',website:''}));
 const examples=[
 {id:'discover-v06',author_id:'synapse',visual:'mountain',body:'Tem descobertas que fazem a gente parar de rolar a tela. Mais horizontes, menos pressa. ⛰️\n#natureza #fotografia',link_url:'',link_title:''},
 {id:'design-v06',author_id:'lia',visual:'architecture',body:'O design também mora nos lugares. Linhas, luz e um novo jeito de olhar. #design #arquitetura',link_url:'https://pt.wikipedia.org/wiki/Arquitetura',link_title:'Um novo olhar para a arquitetura'},
 {id:'science-v06',author_id:'caio',visual:'space',body:'Um universo de perguntas em uma imagem. Qual descoberta te deixa sem palavras? ✨ #universo #ciência',link_url:'https://hubblesite.org/',link_title:'Explore as descobertas do Hubble'},
 {id:'flower-v06',author_id:'nina',visual:'flower',body:'A inspiração está nos detalhes. Às vezes, basta chegar um pouco mais perto. #natureza #fotografia',link_url:'',link_title:''},
 {id:'rocket-v06',author_id:'leo',visual:'rocket',body:'Novos horizontes começam com uma boa pergunta. Para onde vai a sua curiosidade? #tecnologia #ciência',link_url:'https://science.nasa.gov/',link_title:'Ciência e novas perspectivas'},
 {id:'design-details-v06',author_id:'lia',visual:'architecture',body:'Uma coleção de referências, uma ideia de cada vez. #design #criatividade',link_url:'https://developer.mozilla.org/pt-BR/',link_title:'Referências para criar na web'}
 ];
 return {version:'0.6.0',mode:'demo',search_provider:'external',csrf:'demo-local',me:actors.at(-1),actors,following:[],saved:[],blocked:[],links:[],reports_count:0,preferences:{theme:'light',accent:'violet',reduce_motion:false,dm_policy:'everyone'},account:null,
 stories:[['synapse','mountain','Um novo olhar muda tudo.'],['lia','architecture','Design é prestar atenção.'],['caio','space','Nunca perca a curiosidade.'],['nina','flower','Pausa para os detalhes.'],['leo','rocket','Imagine o próximo horizonte.']].map(([author_id,visual,body],i)=>({id:'sample-story-'+i,author_id,visual,body:body+'\nStory editorial de demonstração.',color:'violet',created_at:stamp,expires:Date.now()/1000+86400})),notifications:[],is_admin:false,
 posts:examples.map((p,i)=>({...p,source:'seed',created_at:new Date(Date.now()-(i+1)*1000*60*14).toISOString(),comments:[],likes:0,liked:false,image_path:'',image_alt:''}))};
}
let D=initial();try{const saved=JSON.parse(localStorage.getItem(KEY)||'null');if(saved?.version==='0.6.0'&&Array.isArray(saved.posts)&&Array.isArray(saved.actors)&&Array.isArray(saved.links))D=saved;}catch{temporary=true;}
function persist(){if(temporary)return;try{localStorage.setItem(KEY,JSON.stringify(D));}catch{throw new Error('Não há espaço para salvar a demo neste navegador. Remova uma imagem ou use a versão com servidor.');}}
function clone(v){return JSON.parse(JSON.stringify(v));}
function toggle(arr,value){const i=arr.indexOf(value);if(i<0){arr.push(value);return true;}arr.splice(i,1);return false;}
function safe(value){try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password||!u.hostname.includes('.')||/^(127\.|10\.|192\.168\.|169\.254\.)/.test(u.hostname)||u.hostname.endsWith('.local'))throw 0;return u.href;}catch{throw new Error('Use um link público HTTP ou HTTPS, sem usuário e senha.');}}
function snapshot(){D.stories=D.stories.filter(s=>s.expires>Date.now()/1000);const s=clone(D);s.posts=s.posts.filter(p=>!s.blocked.includes(p.author_id)).slice(0,100);s.actors.forEach(a=>a.followers=D.following.includes(a.id)?1:0);return s;}
async function request(path,method='GET',data={}){const u=new URL(path,'https://synapse.demo');const p=u.pathname.split('/').filter(Boolean);if(method==='GET'){
if(u.pathname==='/api/state')return snapshot();
if(u.pathname==='/api/notifications')return {notifications:clone(D.notifications)};
if(u.pathname==='/api/stories')return {stories:clone(D.stories)};
if(u.pathname==='/api/account/export')return clone(D);
if(u.pathname==='/api/search'){const q=u.searchParams.get('q')||'',scope=u.searchParams.get('scope')||'social',needle=fold(q),s=snapshot();if(['web','wiki'].includes(scope))return {query:q,scope,provider:'external',results:[],shortcuts:(scope==='wiki'?[{name:'Wikipédia',url:'https://pt.wikipedia.org/w/index.php?search='+encodeURIComponent(q)}]:[{name:'Google',url:'https://www.google.com/search?q='+encodeURIComponent(q)},{name:'Brave',url:'https://search.brave.com/search?q='+encodeURIComponent(q)},{name:'DuckDuckGo',url:'https://duckduckgo.com/?q='+encodeURIComponent(q)}]),notice:scope==='wiki'?'Nesta demo sem servidor, use o botão Wikipédia para pesquisar na enciclopédia em outra aba. A versão com servidor inclui um adaptador de busca.':'Nesta demo, escolha um buscador abaixo para abrir uma pesquisa real em outra aba. A demo não possui um índice próprio da web.'};return {query:q,scope,provider:'synapse',results:[],posts:scope==='people'?[]:s.posts.filter(x=>fold(x.body+' '+x.link_title+' '+x.link_url).includes(needle)),people:s.actors.filter(a=>!s.blocked.includes(a.id)&&fold(a.name+' '+a.handle+' '+a.bio).includes(needle))};}
if(p[1]==='messages')return {messages:[]};
throw new Error('Recurso indisponível nesta demonstração.');
}
const before=clone(D);try{let result={ok:true};
if(u.pathname==='/api/posts'&&method==='POST'){const pid=id();D.posts.unshift({id:pid,author_id:D.me.id,body:String(data.body).trim(),source:'human',created_at:now(),link_url:data.link_url?safe(data.link_url):'',link_title:data.link_title||'',image_path:data.image_data||'',image_alt:data.image_alt||'',liked:false,likes:0,comments:[]});result={id:pid};}
else if(p[1]==='posts'){const post=D.posts.find(x=>x.id===p[2]);if(!post)throw new Error('Publicação indisponível.');if(method==='DELETE'){if(post.author_id!==D.me.id)throw new Error('Você só pode excluir suas publicações.');D.posts=D.posts.filter(x=>x.id!==post.id);D.saved=D.saved.filter(x=>x!==post.id);}else if(method==='PATCH'){if(post.author_id!==D.me.id)throw new Error('Você só pode editar suas publicações.');post.body=data.body;post.image_alt=data.image_alt||'';}else if(p[3]==='like'){post.liked=!post.liked;post.likes+=post.liked?1:-1;result={active:post.liked};}else if(p[3]==='save')result={active:toggle(D.saved,post.id)};else if(p[3]==='comments'){post.comments.push({id:id(),post_id:post.id,author_id:D.me.id,body:String(data.body).trim(),created_at:now()});}else if(p[3]==='report')D.reports_count++;else throw new Error('Ação indisponível.');}
else if(p[1]==='actors'){if(p[2]===D.me.id)throw new Error('Escolha outro perfil.');if(p[3]==='follow')result={active:toggle(D.following,p[2])};else if(p[3]==='block'){result={active:toggle(D.blocked,p[2])};if(result.active)D.following=D.following.filter(x=>x!==p[2]);}}
else if(u.pathname==='/api/profile'){const changes={name:data.name,bio:data.bio,website:data.website?safe(data.website):'',interests:data.interests||[],color:data.color||'violet',avatar_path:data.avatar_data||(data.remove_avatar?'':D.me.avatar_path),cover_path:data.cover_data||(data.remove_cover?'':D.me.cover_path)};Object.assign(D.me,changes);Object.assign(D.actors.find(a=>a.id===D.me.id),changes);}
else if(u.pathname==='/api/preferences'){D.preferences=clone(data);}
else if(p[1]==='stories'){if(method==='DELETE')D.stories=D.stories.filter(s=>s.id!==p[2]||s.author_id!==D.me.id);else{const sid=id();D.stories.unshift({id:sid,author_id:D.me.id,body:data.body,color:data.color,image_path:data.image_data||'',created_at:now(),expires:Date.now()/1000+86400});result={id:sid};}}
else if(p[1]==='comments'&&method==='DELETE'){D.posts.forEach(post=>{post.comments=post.comments.filter(c=>c.id!==p[2]||(c.author_id!==D.me.id&&post.author_id!==D.me.id));});}
else if(u.pathname==='/api/reports'){D.reports_count++;}
else if(u.pathname==='/api/notifications/read'){D.notifications.forEach(n=>n.seen=1);}

else if(p[1]==='links'){if(method==='DELETE')D.links=D.links.filter(l=>l.id!==p[2]);else{const url=safe(data.url),existing=D.links.find(l=>l.url===url);if(existing)Object.assign(existing,{title:data.title,collection:data.collection,note:data.note});else{if(D.links.length>=500)throw new Error('Limite: 500 links por conta.');D.links.unshift({id:id(),owner_id:D.me.id,url,title:data.title,collection:data.collection,note:data.note,created_at:now()});}}}
else if(p[1]==='messages')throw new Error('A demo não envia mensagens reais. Use duas contas na versão com servidor.');
else throw new Error('Esta ação requer a versão com servidor.');
persist();return result;}catch(error){D=before;throw error;}
}
window.SynapseDemo={request,get temporary(){return temporary;},reset(){D=initial();try{localStorage.removeItem(KEY);}catch{}persist();}};
})();
