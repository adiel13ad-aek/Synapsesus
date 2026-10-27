/* Offline demo adapter. No authentication, no real users, no AI, no fake web results. */
(()=>{'use strict';
if(document.documentElement.dataset.mode!=='demo')return;
const KEY='synapse.discovery.v03';
const id=()=>Math.random().toString(36).slice(2)+Date.now().toString(36);
const now=()=>new Date().toISOString();
const fold=v=>String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
let temporary=false;
function initial(){const stamp=now();const actors=[{id:'synapse',name:'Equipe Synapse',handle:'synapse',bio:'Descubra, guarde, compartilhe. Perfil editorial fictício.',color:'mint',seeded:1},{id:'lia',name:'Lia Martins',handle:'lia.cria',bio:'Design, referências e boas perguntas. Perfil fictício.',color:'rose',seeded:1},{id:'caio',name:'Caio Costa',handle:'caio.explora',bio:'Ciência, tecnologia e curiosidade. Perfil fictício.',color:'blue',seeded:1},{id:'demo-me',name:'Você',handle:'voce',bio:'Explorando o novo Synapse.',color:'mint',seeded:0}].map(a=>({...a,kind:'human',followers:0,created_at:stamp}));return {version:'0.3.0',mode:'demo',search_provider:'external',csrf:'demo-local',me:actors[3],actors,following:[],saved:[],blocked:[],links:[],reports_count:0,posts:[{id:'discover-v03',author_id:'synapse',body:'A internet é grande demais para explorar sozinho.\n\nPesquise um assunto, salve seus links e transforme uma descoberta em conversa. Bem-vindo ao novo Synapse. #descobertas',link_url:'https://pt.wikipedia.org/',link_title:'Um ponto de partida para a sua curiosidade'},{id:'design-v03',author_id:'lia',body:'Hoje a minha pasta de referências virou uma coleção de ideias. Qual foi a melhor coisa que você encontrou na internet esta semana? #design #criacao',link_url:'https://developer.mozilla.org/pt-BR/',link_title:'Referências para criar na web'}].map(p=>({...p,source:'seed',created_at:stamp,comments:[],likes:0,liked:false,image_path:'',image_alt:''}))};}
let D=initial();try{const saved=JSON.parse(localStorage.getItem(KEY)||'null');if(saved?.version==='0.3.0'&&Array.isArray(saved.posts)&&Array.isArray(saved.actors)&&Array.isArray(saved.links))D=saved;}catch{temporary=true;}
function persist(){if(temporary)return;try{localStorage.setItem(KEY,JSON.stringify(D));}catch{throw new Error('Não há espaço para salvar a demo neste navegador. Remova uma imagem ou use a versão com servidor.');}}
function clone(v){return JSON.parse(JSON.stringify(v));}
function toggle(arr,value){const i=arr.indexOf(value);if(i<0){arr.push(value);return true;}arr.splice(i,1);return false;}
function safe(value){try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||u.username||u.password||!u.hostname.includes('.')||/^(127\.|10\.|192\.168\.|169\.254\.)/.test(u.hostname)||u.hostname.endsWith('.local'))throw 0;return u.href;}catch{throw new Error('Use um link público HTTP ou HTTPS, sem usuário e senha.');}}
function snapshot(){const s=clone(D);s.posts=s.posts.filter(p=>!s.blocked.includes(p.author_id)).slice(0,100);s.actors.forEach(a=>a.followers=D.following.includes(a.id)?1:0);return s;}
async function request(path,method='GET',data={}){const u=new URL(path,'https://synapse.demo');const p=u.pathname.split('/').filter(Boolean);if(method==='GET'){
if(u.pathname==='/api/state')return snapshot();
if(u.pathname==='/api/account/export')return clone(D);
if(u.pathname==='/api/search'){const q=u.searchParams.get('q')||'',scope=u.searchParams.get('scope')||'social',needle=fold(q),s=snapshot();if(['web','wiki'].includes(scope))return {query:q,scope,provider:'external',results:[],notice:scope==='wiki'?'Nesta demo sem servidor, use o botão Wikipédia para pesquisar na enciclopédia em outra aba. A versão com servidor inclui um adaptador de busca.':'Nesta demo, escolha um buscador abaixo para abrir uma pesquisa real em outra aba. A demo não possui um índice próprio da web.'};return {query:q,scope,provider:'synapse',results:[],posts:scope==='people'?[]:s.posts.filter(x=>fold(x.body+' '+x.link_title+' '+x.link_url).includes(needle)),people:s.actors.filter(a=>!s.blocked.includes(a.id)&&fold(a.name+' '+a.handle+' '+a.bio).includes(needle))};}
if(p[1]==='messages')return {messages:[]};
throw new Error('Recurso indisponível nesta demonstração.');
}
const before=clone(D);try{let result={ok:true};
if(u.pathname==='/api/posts'&&method==='POST'){const pid=id();D.posts.unshift({id:pid,author_id:D.me.id,body:String(data.body).trim(),source:'human',created_at:now(),link_url:data.link_url?safe(data.link_url):'',link_title:data.link_title||'',image_path:data.image_data||'',image_alt:data.image_alt||'',liked:false,likes:0,comments:[]});result={id:pid};}
else if(p[1]==='posts'){const post=D.posts.find(x=>x.id===p[2]);if(!post)throw new Error('Publicação indisponível.');if(method==='DELETE'){if(post.author_id!==D.me.id)throw new Error('Você só pode excluir suas publicações.');D.posts=D.posts.filter(x=>x.id!==post.id);D.saved=D.saved.filter(x=>x!==post.id);}else if(p[3]==='like'){post.liked=!post.liked;post.likes+=post.liked?1:-1;result={active:post.liked};}else if(p[3]==='save')result={active:toggle(D.saved,post.id)};else if(p[3]==='comments'){post.comments.push({id:id(),post_id:post.id,author_id:D.me.id,body:String(data.body).trim(),created_at:now()});}else if(p[3]==='report')D.reports_count++;else throw new Error('Ação indisponível.');}
else if(p[1]==='actors'){if(p[2]===D.me.id)throw new Error('Escolha outro perfil.');if(p[3]==='follow')result={active:toggle(D.following,p[2])};else if(p[3]==='block'){result={active:toggle(D.blocked,p[2])};if(result.active)D.following=D.following.filter(x=>x!==p[2]);}}
else if(u.pathname==='/api/profile'){Object.assign(D.me,{name:data.name,bio:data.bio});Object.assign(D.actors.find(a=>a.id===D.me.id),{name:data.name,bio:data.bio});}
else if(p[1]==='links'){if(method==='DELETE')D.links=D.links.filter(l=>l.id!==p[2]);else{const url=safe(data.url),existing=D.links.find(l=>l.url===url);if(existing)Object.assign(existing,{title:data.title,collection:data.collection,note:data.note});else{if(D.links.length>=500)throw new Error('Limite: 500 links por conta.');D.links.unshift({id:id(),owner_id:D.me.id,url,title:data.title,collection:data.collection,note:data.note,created_at:now()});}}}
else if(p[1]==='messages')throw new Error('A demo não envia mensagens reais. Use duas contas na versão com servidor.');
else throw new Error('Esta ação requer a versão com servidor.');
persist();return result;}catch(error){D=before;throw error;}
}
window.SynapseDemo={request,get temporary(){return temporary;},reset(){D=initial();try{localStorage.removeItem(KEY);}catch{}persist();}};
})();
