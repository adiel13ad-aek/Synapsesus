'use strict';
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const date = x => x ? new Date(x).toLocaleString('pt-BR') : '—';
const fmt = x => Number(x || 0).toLocaleString('pt-BR');
let csrf = '', timer, busy = false;
const states = { queued: 'Na fila', failed: 'Falhou', sent: 'Aceito pelo provedor', sending: 'Enviando', cancelled: 'Substituído', expired: 'Expirado' };
function toast(message) { clearTimeout(timer); $('#notice').textContent = message; timer = setTimeout(() => $('#notice').textContent = '', 7000); }
async function api(path, method = 'GET', body) {
  const headers = { 'X-Synapse-Client': 'web-v10' };
  if (method !== 'GET') { headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = csrf; }
  const r = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store', headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const d = await r.json().catch(() => ({ detail: 'Resposta inesperada.' }));
  if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : 'Revise os dados.'); return d;
}
async function load() {
  if (busy) return; busy = true;
  try { const s = await api('/api/manage/session'); csrf = s.csrf; const [ops, support, launch] = await Promise.all([api('/api/manage/operations'), api('/api/manage/support'), api('/api/manage/launch')]); render(ops, support.items, launch); }
  catch (e) { $('#panels').innerHTML = `<section class="card"><h2>Desbloqueie seu painel.</h2><p>${esc(e.message)}</p><p>Use a senha e o segundo fator no painel principal.</p><div class="actions"><a class="button primary" href="/admin">Abrir painel principal</a><button data-action="refresh">Já desbloqueei</button></div></section>`; }
  finally { busy = false; }
}
function render(o, tickets, l) {
  const passed = l.checks.filter(x => x.ok).length;
  $('#panels').innerHTML = `<section id="overview"><div class="metrics"><div class="metric"><span>Banco D1</span><strong>${o.database_ok ? 'Conectado' : 'Revisar'}</strong></div><div class="metric"><span>Solicitações abertas</span><strong>${fmt(o.open_tickets)}</strong></div><div class="metric"><span>Requisitos atendidos</span><strong>${passed}/${l.checks.length}</strong></div></div><div class="alert info">${esc(o.notice)}</div><div class="actions"><button data-action="refresh">Atualizar agora</button><button data-action="storage-test">Testar armazenamento de mídias</button></div></section>
<section class="card" id="mail"><p class="eyebrow">CONFIABILIDADE</p><h2>Acompanhe os e-mails.</h2><p>A fila permanece no D1. Falhas temporárias geram novas tentativas e os links vencidos ou substituídos são descartados.</p><div class="metrics"><div class="metric"><span>Na fila</span><strong>${fmt(o.mail.queued)}</strong></div><div class="metric"><span>Aceitos pelo provedor</span><strong>${fmt(o.mail.sent)}</strong></div><div class="metric"><span>Falhas definitivas</span><strong>${fmt(o.mail.failed)}</strong></div></div><div class="actions"><button class="primary" data-action="mail-test">Enviar teste para meu e-mail</button></div>${o.mail_jobs.length ? `<div class="table-wrap"><table><thead><tr><th>Tipo</th><th>Situação</th><th>Tentativas</th><th>Ação</th></tr></thead><tbody>${o.mail_jobs.map(j => `<tr><td>${esc(j.purpose)}</td><td>${esc(states[j.status] || j.status)}<br><small>${esc(j.error_code)}</small></td><td>${fmt(j.attempts)}</td><td>${j.status === 'failed' ? `<button data-action="retry" data-id="${esc(j.id)}">Tentar novamente</button>` : 'Automática'}</td></tr>`).join('')}</tbody></table></div>` : '<p class="empty">Nenhuma falha ou pendência de envio.</p>'}<p class="muted">Destinatários e links privados não aparecem aqui. “Aceito pelo provedor” não confirma entrega na caixa de entrada; teste confirmação e recuperação no endereço público.</p></section>
<section class="card" id="backups"><p class="eyebrow">RECUPERAÇÃO</p><h2>Banco e mídias têm caminhos de recuperação diferentes.</h2><p>O D1 oferece Time Travel para recuperação do banco dentro da janela do seu plano. Ele não recupera imagens do R2.</p><div class="alert">Nenhuma cópia externa ou restauração foi comprovada por este painel.</div><ol><li>Exporte o banco D1 e copie o bucket R2 para um destino privado separado, seguindo o guia de hospedagem.</li><li>Guarde as chaves separadamente das cópias. Não envie banco, mídias ou segredos ao GitHub.</li><li>Restaure uma cópia em ambiente separado e confira contas, publicações e mídias antes de registrar o teste no painel de lançamento.</li></ol><p class="muted">As ferramentas de backup criptografado da edição Python continuam preservadas no código legado; elas não executam backups do D1/R2. Consulte o guia incluído no projeto 1.0.</p></section>
<section class="card" id="support"><p class="eyebrow">ATENDIMENTO HUMANO</p><h2>Pedidos de ajuda, privacidade e revisão.</h2><p>As respostas aparecem na Central de segurança de quem enviou o pedido.</p>${tickets.length ? tickets.map(t => `<article class="ticket"><span class="badge ${t.status === 'closed' ? 'good' : 'warn'}">${t.status === 'closed' ? 'Encerrado' : 'Aberto'} · ${esc(t.kind)}</span><h3>${esc(t.subject)}</h3><p>@${esc(t.handle)} · ${esc(date(t.created_at))}</p><p>${esc(t.body)}</p><form data-form="reply" data-id="${esc(t.id)}"><label>Resposta<textarea name="reply" minlength="10" maxlength="3000" required>${esc(t.reply)}</textarea></label><label>Situação<select name="status"><option value="open" ${t.status === 'open' ? 'selected' : ''}>Manter em análise</option><option value="closed" ${t.status === 'closed' ? 'selected' : ''}>Responder e encerrar</option></select></label><button class="primary" type="submit">Registrar resposta</button></form><p class="detail-code">Protocolo ${esc(t.id)}</p></article>`).join('') : '<div class="empty">Nenhuma solicitação recebida.</div>'}</section>
<section class="card checklist" id="launch"><p class="eyebrow">ABERTURA AO PÚBLICO</p><h2>${passed} de ${l.checks.length} verificações atendidas.</h2><p>Configuração, evidência técnica e declaração do responsável são informações distintas.</p>${l.checks.map(c => `<div class="item"><div><strong>${esc(c.label || c.id)}</strong><p>${c.kind === 'operator_attestation' ? 'Declaração documentada pelo responsável; não executa o teste' : c.kind === 'integration' ? 'Evidência técnica observada pela aplicação' : c.kind === 'operator_review' ? 'Revisão do responsável' : 'Configuração verificada pelo sistema'}</p></div><span class="badge ${c.ok ? 'good' : 'warn'}">${c.ok ? 'Atendido' : 'Pendente'}</span></div>`).join('')}<div class="actions"><a class="button primary" href="/admin">Gerenciar lançamento</a></div><p class="muted">${esc(l.notice)}</p></section>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-action]'); if (!b) return; b.disabled = true;
  try {
    const action = b.dataset.action;
    if (action === 'refresh') { await load(); return; }
    if (action === 'mail-test') { await api('/api/manage/mail/test', 'POST', {}); toast('Teste enfileirado. Confirme o recebimento na sua caixa de entrada.'); }
    if (action === 'retry') { await api('/api/manage/mail/' + b.dataset.id + '/retry', 'POST', {}); toast('Nova tentativa enfileirada.'); }
    if (action === 'storage-test') { await api('/api/manage/integrations/storage', 'POST', {}); toast('Escrita, leitura e remoção do objeto de diagnóstico concluídas.'); }
    await load();
  } catch (error) { toast(error.message); } finally { b.disabled = false; }
});
document.addEventListener('submit', async e => { const form = e.target.closest('form[data-form]'); if (!form) return; e.preventDefault(); const b = form.querySelector('[type=submit]'); b.disabled = true; try { await api('/api/manage/support/' + form.dataset.id, 'POST', Object.fromEntries(new FormData(form))); toast('Resposta registrada.'); await load(); } catch (error) { toast(error.message); } finally { b.disabled = false; } });
load();
