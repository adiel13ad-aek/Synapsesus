'use strict';
/* Synapse 0.5. All remote services are opt-in; the demo never pretends to be a live network. */
(() => {
  const filePath = value => /^\/media\/[a-f0-9]{32}\.(jpg|mp4)$/.test(value || '') ? value : '';
  let staged = [], uploading = false, epoch = 0, paging = false, pageCursor = '', filterCursor = '';
  const originalCompose = compose, originalPostCard = postCard, originalFeed = feed;
  const originalSettings = settings, originalMessages = messages, originalGrid = discoveryGrid;
  const originalDraw = draw;
  let call = null, callTimer = null, callBusy = false, pendingIncoming = null, activityBusy = false;

  function galleryHTML(p) {
    const items = (p.media || []).filter(m => filePath(m.path));
    if (!items.length) return '';
    return `<section class="media-gallery" aria-label="Mídia da publicação"><div class="gallery-track" id="gallery-${esc(p.id)}">${items.map((m, i) => `<figure class="gallery-slide">${m.kind === 'video' ? `<video class="post-video" controls playsinline preload="metadata" ${filePath(m.thumbnail) ? `poster="${esc(filePath(m.thumbnail))}"` : ''} aria-label="Vídeo de ${esc(A(p.author_id).name)}"><source src="${esc(filePath(m.path))}" type="video/mp4">Seu navegador não reproduz este vídeo.</video>` : `<img class="post-media" src="${esc(filePath(m.path))}" loading="lazy" alt="${esc(p.image_alt || 'Foto compartilhada')} (${i+1} de ${items.length})">`}</figure>`).join('')}</div>${items.length>1 ? `<div class="gallery-controls"><button class="icon-btn" data-plus="gallery-prev" data-id="${esc(p.id)}" aria-label="Foto anterior">${icon('back')}</button><span>Deslize para ver ${items.length} fotos</span><button class="icon-btn" data-plus="gallery-next" data-id="${esc(p.id)}" aria-label="Próxima foto">${icon('arrow')}</button></div>` : items[0]?.kind==='video' ? '<div class="media-type-label">Vídeo · toque para reproduzir</div>' : ''}</section>`;
  }
  postCard = function(p) {
    const html = originalPostCard(p), gallery = galleryHTML(p);
    if (!gallery) return html;
    const node = document.createElement('template'); node.innerHTML = html;
    node.content.querySelector('.post-media-wrap')?.remove();
    node.content.querySelector('.post-head').insertAdjacentHTML('afterend', gallery);
    return node.innerHTML;
  };
  discoveryGrid = function(posts) {
    return originalGrid(posts.map(p => ({...p, image_path: p.media?.[0]?.thumbnail || (p.media?.[0]?.kind==='image' ? p.media[0].path : p.image_path)})));
  };
  feed = function() {
    let result;
    if (V.filter === 'video') {
      result = `${pageHead('Em movimento.','Vídeos da comunidade. Sem reprodução automática com som.')}<div class="topics"><button class="btn secondary" data-plus="all-posts">${icon('back')} Todos os posts</button><button class="btn primary" data-action="new-post">${icon('plus')} Publicar</button></div>`;
      const videos = S.posts.filter(p => (p.media||[]).some(m=>m.kind==='video'));
      result += videos.length ? `<div class="short-video-feed">${videos.map(postCard).join('')}</div>` : empty('Seu vídeo pode ser o primeiro.', DEMO?'Vídeos reais estão disponíveis na versão com servidor.':'Publique um vídeo de até 90 segundos para começar.','play');
    } else result = originalFeed();
    return result + (!DEMO ? '<div class="load-more-wrap"><button class="btn secondary" data-plus="more-posts">Carregar mais publicações</button></div>' : '');
  };

  function stagedHTML() {
    return staged.map(m=>`<div class="upload-tile">${m.kind==='video'?`<video src="${esc(filePath(m.path))}" ${filePath(m.thumbnail)?`poster="${esc(filePath(m.thumbnail))}"`:''} controls muted playsinline></video>`:`<img src="${esc(filePath(m.path))}" alt="Prévia da foto">`}<button type="button" class="icon-btn" data-plus="remove-upload" data-id="${esc(m.id)}" aria-label="Remover arquivo">${icon('close')}</button><small>${m.kind==='video'?'Vídeo pronto':'Foto pronta'}</small></div>`).join('');
  }
  function showUploadState() {
    const grid = $('#gallery-upload-preview'); if(grid) grid.innerHTML = stagedHTML();
    const status = $('#upload-status'); if(status) status.textContent = uploading?'Enviando e processando o arquivo…':staged.length?`${staged.length} arquivo(s) pronto(s).`:'Até seis fotos ou um vídeo. Você decide quando publicar.';
    const button=$('[data-form="post-plus"] [type="submit"]');if(button) button.disabled=uploading;
  }
  compose = function(url='',title='',editId='') {
    if(DEMO || editId) return originalCompose(url,title,editId);
    if(!requireAccount()) return;
    staged=[];uploading=false;epoch++;
    const videos=!!S.capabilities?.video;
    dialog('Sua próxima descoberta.', `<form data-form="post-plus"><div class="form-grid"><label>Legenda<textarea name="body" rows="4" maxlength="2000" placeholder="Conte a história por trás da sua descoberta…" required></textarea></label><div class="upload-area"><label>Fotos${videos?' ou vídeo':''}<input id="gallery-files" type="file" multiple accept="image/jpeg,image/png,image/webp${videos?',video/mp4,video/webm,video/quicktime':''}"></label><p>Até 6 fotos, 3 MB por foto${videos?' · ou 1 vídeo de até 25 MB e 90 segundos':''}.</p>${!videos?'<p class="tiny">Vídeos precisam de FFmpeg instalado no servidor.</p>':''}<p id="upload-status" role="status">Os arquivos só entram no feed quando você publicar.</p><div class="upload-grid" id="gallery-upload-preview"></div></div><label>Descrição para acessibilidade<input name="image_alt" maxlength="250" placeholder="Descreva as imagens para quem não consegue vê-las"></label><label>Link da descoberta (opcional)<input name="link_url" type="url" value="${esc(url)}" maxlength="2048" placeholder="https://"></label><label>Título do link<input name="link_title" maxlength="180" value="${esc(title)}"></label></div>${errorLine}<div class="dialog-footer"><button type="button" class="btn ghost" data-action="close">Cancelar</button><button type="submit" class="btn primary">${icon('send')} Publicar</button></div></form>`, 'Arquivos ainda não publicados só podem ser vistos por sua conta.');
  };
  async function sendUpload(file) {
    const form = new FormData();form.append('file',file);
    let response;
    try { response=await fetch('/api/media/uploads',{method:'POST',credentials:'same-origin',headers:{'X-Synapse-Client':'web-v07','X-CSRF-Token':S.csrf},body:form}); }
    catch { throw new Error('Falha na conexão durante o envio.'); }
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Não foi possível enviar o arquivo.');
    return data;
  }
  document.addEventListener('change',async e=>{
    if(e.target.id!=='gallery-files')return;
    e.stopImmediatePropagation();
    if(uploading)return;
    const files=[...e.target.files];e.target.value='';
    if(files.length+staged.length>6)return toast('Selecione no máximo seis fotos.');
    if((files.some(f=>f.type.startsWith('video/'))||staged.some(f=>f.kind==='video'))&&files.length+staged.length!==1)return toast('Publique um vídeo por vez, separado das fotos.');
    uploading=true;const ticket=epoch;showUploadState();
    try {
      for(const file of files) {
        if(!['image/jpeg','image/png','image/webp','video/mp4','video/webm','video/quicktime'].includes(file.type))throw new Error('Formato não suportado.');
        if(file.size>(file.type.startsWith('video/')?25:3)*1024*1024)throw new Error('Arquivo acima do limite de tamanho.');
        const item=await sendUpload(file);
        if(ticket!==epoch) { await api('/api/media/uploads/'+item.id,'DELETE',{}).catch(()=>{});break; }
        staged.push(item);showUploadState();
      }
    } catch(err) { toast(err.message);const error=$('[data-form="post-plus"] .form-error');if(error)error.textContent=err.message; }
    finally { if(ticket===epoch){uploading=false;showUploadState();} }
  },true);
  document.addEventListener('submit',async e=>{
    const form=e.target.closest('[data-form="post-plus"]');if(!form)return;
    e.preventDefault();e.stopImmediatePropagation();if(uploading)return;
    const button=$('[type="submit"]',form);if(button.disabled)return;button.disabled=true;
    try {
      const values=Object.fromEntries(new FormData(form));values.media_ids=staged.map(m=>m.id);
      await api('/api/posts','POST',values);staged=[];epoch++;closeDialog();V.page='feed';V.filter='all';pageCursor='';await refresh();toast('Publicado. Sua descoberta já está no feed.');
    } catch(err) {$('.form-error',form).textContent=err.message;button.disabled=false;}
  },true);
  $('#dialog').addEventListener('close',()=>{
    if($('#gallery-files')){epoch++;const unused=staged;staged=[];uploading=false;for(const m of unused)api('/api/media/uploads/'+m.id,'DELETE',{}).catch(()=>{});}
  });

  settings = function() {
    return originalSettings()+ (S.me ? `<section class="settings-card"><h3>Notificações do dispositivo</h3><p>Opcional. Uma notificação avisa sobre novas interações sem mostrar o texto de mensagens privadas.</p><p class="tiny">${DEMO?'Disponível na versão com servidor.':S.capabilities?.push?'Envio Web Push configurado. O navegador ainda precisa autorizar.':'O operador ainda não configurou o envio Web Push.'} ${'PushManager' in window?'':'Este navegador não oferece Web Push; a atividade continua dentro do app.'}</p><div class="topics"><button class="btn secondary" data-plus="push-on">Ativar neste dispositivo</button><button class="btn ghost" data-plus="push-off">Desativar</button></div></section>${S.is_admin?'<section class="settings-card"><h3>Preparação para lançamento</h3><p>Confira as configurações que ainda faltam, sem expor chaves e senhas.</p><button class="btn secondary" data-plus="readiness">Verificar servidor</button></section>':''}`:'');
  };
  messages = function() {
    const result=originalMessages();
    return result+(S.me&&V.chat&&!DEMO&&S.capabilities?.calls?`<section class="call-actions"><span>Chamadas com aceite do destinatário</span><button class="btn secondary" data-plus="call-audio">${icon('chat')} Áudio</button><button class="btn primary" data-plus="call-video">${icon('play')} Vídeo</button></section>`:'');
  };
  draw = function() {
    originalDraw();
    // Never autoplay or silently request camera/microphone permission.
    document.querySelectorAll('video.post-video').forEach(v=>v.addEventListener('play',()=>document.querySelectorAll('video.post-video').forEach(other=>{if(other!==v)other.pause();})));
  };
  function mergePage(data,reset=false) {
    const ids=new Set((reset?[]:S.posts).map(p=>p.id));
    S.posts=(reset?[]:S.posts).concat(data.posts.filter(p=>!ids.has(p.id)));
    for(const a of data.actors||[])if(!S.actors.some(x=>x.id===a.id))S.actors.push(a);
  }
  async function morePosts(reset=false) {
    if(paging)return;paging=true;
    const button=$('[data-plus="more-posts"]');if(button){button.disabled=true;button.textContent='Carregando…';}
    try{
      const kind=V.filter==='video'?'video':['following','saved'].includes(V.filter)?V.filter:'all';
      if(filterCursor!==kind){filterCursor=kind;pageCursor='';if(!reset){const visible=S.posts.filter(p=>kind==='all'||kind==='video'&&(p.media||[]).some(m=>m.kind==='video')||kind==='following'&&(S.following.includes(p.author_id)||p.author_id===S.me?.id)||kind==='saved'&&S.saved.includes(p.id));const last=visible.at(-1);if(last)pageCursor=btoa(last.created_at+'|'+last.id).replace(/=+$/,'').replace(/\+/g,'-').replace(/\//g,'_');}}
      const data=await api('/api/feed?kind='+kind+'&limit=25&cursor='+encodeURIComponent(pageCursor));
      mergePage(data,reset);pageCursor=data.next_cursor;draw();
      if(!pageCursor)$('[data-plus="more-posts"]')?.remove();
    }catch(err){toast(err.message);if(button){button.disabled=false;button.textContent='Tentar novamente';}}
    finally{paging=false;}
  }
  function urlBase64(value){const bin=atob(value.replace(/-/g,'+').replace(/_/g,'/').padEnd(Math.ceil(value.length/4)*4,'='));return Uint8Array.from(bin,c=>c.charCodeAt(0));}
  async function changePush(enable) {
    if(DEMO)return toast('Web Push só funciona conectado ao servidor, com sua autorização.');
    if(!('serviceWorker'in navigator)||!('PushManager'in window)||!window.isSecureContext)throw new Error('Use um navegador compatível em HTTPS. WebView Android não oferece Web Push.');
    const config=await api('/api/push/config');
    if(enable&&!config.enabled)throw new Error('O operador precisa configurar as chaves VAPID do servidor.');
    const registration=await navigator.serviceWorker.ready;let sub=await registration.pushManager.getSubscription();
    if(enable){
      if(await Notification.requestPermission()!=='granted')throw new Error('Você não autorizou as notificações.');
      sub=sub||await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64(config.public_key)});
      const data=sub.toJSON();await api('/api/push/subscriptions','POST',{endpoint:data.endpoint,p256dh:data.keys.p256dh,auth:data.keys.auth});toast('Notificações ativadas neste dispositivo.');
    }else{
      if(sub){await api('/api/push/subscriptions','DELETE',{endpoint:sub.endpoint});await sub.unsubscribe();}toast('Notificações desativadas.');
    }
  }

  document.addEventListener('click',async e=>{
    const el=e.target.closest('[data-plus]');if(!el)return;e.preventDefault();const action=el.dataset.plus;
    try{
      if(action.startsWith('gallery-')){const track=$('#gallery-'+el.dataset.id);track?.scrollBy({left:track.clientWidth*(action==='gallery-next'?1:-1),behavior:document.documentElement.dataset.motion==='reduced'?'auto':'smooth'});}
      if(action==='remove-upload'){
        if(uploading)return;const id=el.dataset.id;await api('/api/media/uploads/'+id,'DELETE',{});staged=staged.filter(m=>m.id!==id);showUploadState();
      }
      if(action==='videos'){V.page='feed';V.filter='video';pageCursor='';filterCursor='';draw();if(!DEMO)await morePosts(true);}
      if(action==='all-posts'){V.filter='all';pageCursor='';filterCursor='';await refresh();}
      if(action==='more-posts')await morePosts();
      if(action==='push-on')await changePush(true);if(action==='push-off')await changePush(false);
      if(action==='readiness'){
        const r=await api('/api/operator/readiness');const labels={https_origin:'Endereço HTTPS',demo_disabled:'Exemplos desativados',smtp_configured:'Envio de e-mails',operator_account:'Administrador por identidade',policies_reviewed:'Políticas revisadas pelo operador',operator_identity:'Identidade do operador',support_contact:'Contato de suporte',child_safety_contact:'Contato de proteção infantil'};
        dialog('Verificação de configuração',`<div class="readiness-list">${Object.entries(r.checks).map(([k,v])=>`<p>${v?'✓':'○'} ${esc(labels[k]||k)} <b>${v?'Configurado':'Pendente'}</b></p>`).join('')}</div><p class="dialog-note">${esc(r.notice)}</p>`);
      }
      if(action==='call-audio'||action==='call-video')await startOutgoing(action==='call-video'?'video':'audio');
      if(action==='call-accept'&&pendingIncoming)await acceptIncoming();
      if(action==='call-reject'&&pendingIncoming){await api('/api/calls/'+pendingIncoming.id+'/end','POST',{});pendingIncoming=null;$('#incoming-call')?.remove();}
      if(action==='call-end')await stopCall(true);
      if(action==='call-mute'&&call?.stream){const tracks=call.stream.getAudioTracks();tracks.forEach(t=>t.enabled=!t.enabled);el.textContent=tracks[0]?.enabled?'Silenciar':'Ativar microfone';}
    }catch(err){toast(err.message);}
  });

  // Calling UI is independent from the feed so rerenders never destroy a live stream.
  function ensureCallPane(label) {
    $('#call-pane')?.remove();
    const panel=document.createElement('section');panel.id='call-pane';panel.className='call-pane';panel.setAttribute('aria-label','Chamada em andamento');
    panel.innerHTML=`<header><strong>${esc(label)}</strong><span id="call-status" role="status">Preparando conexão…</span></header><div class="call-video-grid"><video id="remote-call" autoplay playsinline controls></video><video id="local-call" autoplay playsinline muted></video></div><p class="tiny">Câmera e microfone só são usados durante esta chamada. O Synapse não grava a transmissão.</p><div class="topics"><button class="btn secondary" data-plus="call-mute">Silenciar</button><button class="btn danger" data-plus="call-end">Encerrar</button></div>`;
    document.body.appendChild(panel);
  }
  async function createPeer(mode) {
    if(!navigator.mediaDevices?.getUserMedia||!window.RTCPeerConnection)throw new Error('Chamadas precisam de navegador compatível em HTTPS ou localhost.');
    const config=await api('/api/calls/config');
    if(config.iceTransportPolicy==='relay'&&!config.iceServers.some(s=>s.urls.some(u=>u.startsWith('turn'))))throw new Error('O operador precisa configurar o servidor TURN para chamadas privadas entre redes.');
    const stream=await navigator.mediaDevices.getUserMedia({audio:true,video:mode==='video'?{width:{ideal:640},height:{ideal:480}}:false});
    let pc;try{pc=new RTCPeerConnection({iceServers:config.iceServers,iceTransportPolicy:config.iceTransportPolicy});}catch(err){stream.getTracks().forEach(t=>t.stop());throw err;}
    const ctx={pc,stream,id:'',caller:false,cursor:0,offered:false,candidates:[],remoteCandidates:[],mode};
    stream.getTracks().forEach(track=>pc.addTrack(track,stream));
    pc.ontrack=event=>{const video=$('#remote-call');if(video){video.srcObject=event.streams[0]||new MediaStream([event.track]);video.play().catch(()=>{});}};
    pc.onicecandidate=event=>{if(event.candidate)ctx.candidates.push(event.candidate.toJSON());};
    pc.onconnectionstatechange=()=>{const status=$('#call-status');if(status)status.textContent={connected:'Conectado',connecting:'Conectando…',disconnected:'Conexão interrompida',failed:'Não foi possível conectar. Verifique o TURN.',closed:'Chamada encerrada'}[pc.connectionState]||'Preparando conexão…';if(pc.connectionState==='failed')stopCall(true);};
    return ctx;
  }
  async function startOutgoing(mode) {
    if(call)return toast('Encerre a chamada atual primeiro.');if(!requireAccount()||!V.chat)return;
    let ctx=await createPeer(mode);
    try{
      const result=await api('/api/calls','POST',{target_id:V.chat,mode});ctx.id=result.id;ctx.caller=true;call=ctx;ensureCallPane('Chamando '+A(V.chat).name);$('#call-status').textContent='Aguardando aceite…';$('#local-call').srcObject=ctx.stream;startCallPolling();
    }catch(err){ctx.stream.getTracks().forEach(t=>t.stop());ctx.pc.close();throw err;}
  }
  async function acceptIncoming() {
    if(call||!pendingIncoming)return;const incoming=pendingIncoming;
    const ctx=await createPeer(incoming.mode);ctx.id=incoming.id;
    try{
      await api('/api/calls/'+ctx.id+'/accept','POST',{});call=ctx;pendingIncoming=null;$('#incoming-call')?.remove();ensureCallPane('Conversa com '+incoming.caller.name);$('#local-call').srcObject=ctx.stream;startCallPolling();
    }catch(err){ctx.stream.getTracks().forEach(t=>t.stop());ctx.pc.close();throw err;}
  }
  function startCallPolling(){clearInterval(callTimer);callTimer=setInterval(pollCall,1200);pollCall();}
  async function pollCall() {
    if(!call||callBusy)return;callBusy=true;const ctx=call;
    try{
      const data=await api('/api/calls/'+ctx.id+'/signals?after='+ctx.cursor);
      if(call!==ctx)return;
      if(data.status==='ended'){await stopCall(false);toast('A chamada foi encerrada.');return;}
      if(data.status!=='active')return;
      if(ctx.caller&&!ctx.offered){ctx.offered=true;const offer=await ctx.pc.createOffer();await ctx.pc.setLocalDescription(offer);await api('/api/calls/'+ctx.id+'/signals','POST',{kind:'offer',data:offer.sdp});}
      for(const signal of data.signals){
        if(signal.kind==='offer'&&!ctx.caller){await ctx.pc.setRemoteDescription({type:'offer',sdp:signal.data});const answer=await ctx.pc.createAnswer();await ctx.pc.setLocalDescription(answer);await api('/api/calls/'+ctx.id+'/signals','POST',{kind:'answer',data:answer.sdp});}
        if(signal.kind==='answer'&&ctx.caller)await ctx.pc.setRemoteDescription({type:'answer',sdp:signal.data});
        if(signal.kind==='candidate')ctx.remoteCandidates.push(JSON.parse(signal.data));
        ctx.cursor=signal.seq;
      }
      if(ctx.pc.remoteDescription)while(ctx.remoteCandidates.length)await ctx.pc.addIceCandidate(ctx.remoteCandidates.shift());
      while(ctx.candidates.length)await api('/api/calls/'+ctx.id+'/signals','POST',{kind:'candidate',data:JSON.stringify(ctx.candidates.shift())});
    }catch(err){toast(err.message);await stopCall(true);}finally{callBusy=false;}
  }
  async function stopCall(notify) {
    clearInterval(callTimer);const old=call;call=null;
    if(old){old.stream.getTracks().forEach(t=>t.stop());old.pc.onconnectionstatechange=null;old.pc.close();if(notify)await api('/api/calls/'+old.id+'/end','POST',{}).catch(()=>{});}
    $('#call-pane')?.remove();
  }
  async function pollActivity() {
    if(DEMO||!S.me||document.visibilityState!=='visible'||activityBusy)return;activityBusy=true;
    try{
      const data=await api('/api/notifications');const before=S.notifications.filter(n=>!n.seen).length;S.notifications=data.notifications;
      if(S.notifications.filter(n=>!n.seen).length>before&&V.page!=='notifications')toast('Nova interação na sua atividade.');
      if(V.page==='notifications'&&!$('#dialog').open)draw();
      if(S.capabilities?.calls&&!call){
        const data=await api('/api/calls/pending');pendingIncoming=data.calls[0]||null;
        if(!pendingIncoming)$('#incoming-call')?.remove();
        else if(!$('#incoming-call')){const panel=document.createElement('aside');panel.id='incoming-call';panel.className='incoming-call';panel.setAttribute('role','alert');panel.innerHTML=`<b>${esc(pendingIncoming.caller.name)} está chamando por ${pendingIncoming.mode==='video'?'vídeo':'áudio'}</b><p>Seu microfone e câmera só serão usados se você aceitar.</p><div class="topics"><button class="btn primary" data-plus="call-accept">Aceitar</button><button class="btn secondary" data-plus="call-reject">Recusar</button></div>`;document.body.appendChild(panel);}
      }
    }catch{}finally{activityBusy=false;}
  }
  setInterval(pollActivity,5000);
  window.synapsePause=()=>{stopCall(true);document.querySelectorAll('video').forEach(v=>v.pause());};
  window.addEventListener('pagehide',()=>{
    if(call){
      call.stream.getTracks().forEach(t=>t.stop());call.pc.close();
      fetch('/api/calls/'+call.id+'/end',{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json','X-Synapse-Client':'web-v07','X-CSRF-Token':S.csrf},body:'{}'}).catch(()=>{});
    }
    clearInterval(callTimer);
  });
  // Logout removes device subscriptions for this account before invalidating its session.
  document.addEventListener('click',async e=>{
    if(!e.target.closest('[data-action="logout"]')||DEMO||!S.me)return;
    e.stopImmediatePropagation();e.preventDefault();
    try{if('serviceWorker'in navigator){const reg=await navigator.serviceWorker.getRegistration();const sub=await reg?.pushManager?.getSubscription();if(sub){await api('/api/push/subscriptions','DELETE',{endpoint:sub.endpoint});await sub.unsubscribe();}}}catch{}
    await stopCall(true);
    try{await api('/api/auth/logout','POST',{});V.chat=null;V.messages=[];V.page='feed';await refresh();toast('Você saiu da conta.');}catch(err){toast(err.message);}
  },true);
  if(new URLSearchParams(location.search).has('activity'))setTimeout(()=>go('notifications'),400);
})();
