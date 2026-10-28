import {checkCredential} from './credentials.js';
import {
  fail, uid, now, stamp, sha256, token, equal, query, first, run, batch,
  json, text, needUser, settings, rate, encryptSecret, decryptSecret
} from './core.js';
import { launchReadiness } from './safety.js';

const POLICY_TITLES = { terms: 'Termos de uso', privacy: 'Privacidade', safety: 'Regras e segurança' };
const ATTESTATIONS = {
  audience_review: 'Público e obrigações de privacidade e idade avaliados',
  email_test: 'Confirmação e recuperação recebidas em uma caixa real',
  backup_restore: 'Backup externo e restauração verificados em ambiente separado',
  moderation: 'Responsáveis por denúncias, recursos e segurança definidos',
  browser_test: 'Cadastro, publicação e mensagens testados no domínio HTTPS'
};
const production = c => c.env.APP_ENV !== 'development';
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const reason = d => text(d.reason, 8, 600, 'Justificativa');
const integer = (value, min, max, label) => {
  if (!Number.isInteger(value) || value < min || value > max) fail(422, `${label} inválido.`);
  return value;
};
const boolean = (value, label) => {
  if (typeof value !== 'boolean') fail(422, `${label} deve ser verdadeiro ou falso.`);
  return value ? 1 : 0;
};
const pick = (value, choices, label) => {
  if (!choices.includes(value)) fail(422, `${label} inválido.`);
  return value;
};
const pageNumber = c => {
  const raw = c.url.searchParams.get('page') || '1';
  if (!/^\d{1,7}$/.test(raw)) fail(422, 'Página inválida.');
  return integer(Number(raw), 1, 1000000, 'Página');
};
const queryText = c => text(c.url.searchParams.get('q') || '', 0, 100, 'Pesquisa');
const n = async (c, sql, ...args) => Number((await first(c, sql, ...args))?.n || 0);
const changes = result => Number(result?.meta?.changes ?? result?.changes ?? 0);
const eventStatement = (user, action, targetType = '', targetId = '', why = '') => [
  'INSERT INTO admin_events(id,actor_id,actor_label,action,target_type,target_id,reason,created_at) VALUES(?,?,?,?,?,?,?,?)',
  uid(), user.id, '@' + user.handle, action, targetType, targetId, why, now()
];
export async function adminEvent(c, user, action, targetType = '', targetId = '', why = '') {
  const [sql, ...args] = eventStatement(user, action, targetType, targetId, why);
  return run(c, sql, ...args);
}
export async function operatorRole(c, userId = c.user?.id) {
  if (!userId) return null;
  const row = await first(c, "SELECT COALESCE(r.role,'owner') AS role FROM operators o LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE o.user_id=?", userId);
  return row?.role || null;
}
async function requireOperator(c) {
  const user = needUser(c);
  const role = await operatorRole(c, user.id);
  if (!role) fail(403, 'Conta sem permissão administrativa.');
  if (!user.email_verified) fail(403, 'Confirme o e-mail da conta responsável antes de administrar.');
  return { ...user, role };
}
export async function requireAdmin(c, ownerOnly = false) {
  const user = await requireOperator(c);
  if (ownerOnly && user.role !== 'owner') fail(403, 'Somente o responsável pode alterar esta configuração.');
  const row = await first(c, 'SELECT g.expires FROM admin_grants g JOIN operator_security sec ON sec.user_id=g.user_id JOIN sessions se ON se.token_hash=g.token_hash WHERE g.token_hash=? AND g.user_id=? AND g.expires>? AND se.expires>? AND sec.enabled=1', c.sessionHash, user.id, stamp(), stamp());
  if (!row) fail(403, 'Desbloqueie o painel em /admin com senha e segundo fator.');
  return user;
}
export async function publicSiteSettings(c) {
  const st = await settings(c);
  let ready = false;
  if (st.registration_open) ready = (await launchReadiness(c)).ready;
  return { registration_open: Boolean(st.registration_open && ready && !st.maintenance), maintenance: Boolean(st.maintenance), uploads_enabled: Boolean(st.uploads_enabled), announcement: st.announcement || '' };
}
async function checkedPassword(c, user, value) {
  await rate(c, 'admin-unlock:' + user.id, 5, 300);
  if (typeof value !== 'string' || value.length < 1 || value.length > 128 || !await checkCredential(c, user, value)) fail(401, 'Não foi possível confirmar suas credenciais.');
}
function base32(bytes) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = 0, value = 0, out = '';
  for (const b of bytes) { value = (value << 8) | b; bits += 8; while (bits >= 5) { out += alphabet[(value >>> (bits - 5)) & 31]; bits -= 5; } }
  if (bits) out += alphabet[(value << (5 - bits)) & 31];
  return out;
}
function unbase32(input) {
  if (!/^[A-Z2-7]{16,128}$/.test(input)) fail(503, 'Chave do autenticador inválida.');
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = 0, value = 0, out = [];
  for (const ch of input) { value = (value << 5) | alphabet.indexOf(ch); bits += 5; if (bits >= 8) { out.push((value >>> (bits - 8)) & 255); bits -= 8; } }
  return new Uint8Array(out);
}
export async function totp(secret, counter) {
  const data = new Uint8Array(8); new DataView(data.buffer).setBigUint64(0, BigInt(counter));
  const key = await crypto.subtle.importKey('raw', unbase32(secret), { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']);
  const h = new Uint8Array(await crypto.subtle.sign('HMAC', key, data));
  const offset = h[h.length - 1] & 15;
  const num = ((h[offset] & 127) * 16777216 + h[offset + 1] * 65536 + h[offset + 2] * 256 + h[offset + 3]) % 1000000;
  return String(num).padStart(6, '0');
}
async function validStep(secret, code, lastStep) {
  if (!/^\d{6}$/.test(code || '')) fail(401, 'Código inválido ou já utilizado.');
  const step = Math.floor(stamp() / 30);
  for (const counter of [step - 1, step, step + 1]) if (counter > lastStep && equal(await totp(secret, counter), code)) return counter;
  fail(401, 'Código inválido ou já utilizado. Aguarde o próximo código do autenticador.');
}
async function grant(c, user, action) {
  const expiry = stamp() + 900;
  await batch(c, [
    ['INSERT INTO admin_grants(token_hash,user_id,expires) VALUES(?,?,?) ON CONFLICT(token_hash) DO UPDATE SET user_id=excluded.user_id,expires=excluded.expires', c.sessionHash, user.id, expiry],
    eventStatement(user, action, 'session', '', 'Acesso temporário por 15 minutos.')
  ]);
  return expiry;
}
async function protectUser(c, user, targetId) {
  const target = await first(c, "SELECT id,handle,seeded,active,email_verified FROM actors WHERE id=? AND kind='human'", targetId);
  if (!target || target.seeded) fail(404, 'Conta real não encontrada.');
  if (target.id === user.id) fail(409, 'Não é permitido realizar esta ação na própria conta.');
  const role = await operatorRole(c, targetId);
  if (role && (role === 'owner' || user.role !== 'owner')) fail(409, 'Conta administrativa protegida. A transferência de responsabilidade exige manutenção autenticada da infraestrutura.');
  return target;
}
const publicOrigin = c => {
  try { const u = new URL(c.env.PUBLIC_ORIGIN); if (u.protocol === 'https:' && !u.username && !u.password && u.pathname === '/' && !u.search && !u.hash) return u.origin; } catch {}
  return '';
};
const indexing = c => c.env.PUBLIC_INDEXING === '1' && Boolean(publicOrigin(c));
const htmlResponse = body => new Response(body, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
async function asset(c, path) { return c.env.ASSETS.fetch(new Request(new URL(path, c.request.url), { method: 'GET' })); }
function head(c, title, description, path) {
  const origin = publicOrigin(c), verification = c.env.GOOGLE_SITE_VERIFICATION || '';
  return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(title)} · Synapse</title><meta name="description" content="${escape(description)}"><meta name="robots" content="${indexing(c) ? 'index,follow' : 'noindex,follow'}"><meta name="theme-color" content="#faf9fd"><meta property="og:type" content="website"><meta property="og:site_name" content="Synapse"><meta property="og:title" content="${escape(title)}"><meta property="og:description" content="${escape(description)}">${origin ? `<link rel="canonical" href="${escape(origin + path)}"><meta property="og:url" content="${escape(origin + path)}"><meta property="og:image" content="${escape(origin)}/icon-512.png">` : ''}${/^[A-Za-z0-9_-]{10,200}$/.test(verification) ? `<meta name="google-site-verification" content="${escape(verification)}">` : ''}<link rel="icon" href="/icon.svg"><link rel="stylesheet" href="/launch.css"></head><body><a class="skip" href="#conteudo">Ir para o conteúdo</a><header class="header"><a class="brand" href="/bem-vindo"><span aria-hidden="true">✦</span>synapse<span class="brand-dot">.</span></a><nav aria-label="Navegação principal"><a href="/como-funciona">Como funciona</a><a href="/ajuda">Ajuda</a><a class="button nav-button" href="/">Entrar ↗</a></nav></header><main id="conteudo">`;
}
const footer = '</main><footer><a class="brand" href="/bem-vindo">synapse.</a><p>Descobertas que conectam.</p><nav aria-label="Documentos"><a href="/terms.html">Termos</a><a href="/privacy.html">Privacidade</a><a href="/safety.html">Segurança</a><a href="/delete-account.html">Excluir conta</a><a href="/ajuda">Ajuda</a></nav></footer></body></html>';
async function publicPage(c, path) {
  const st = await publicSiteSettings(c), cta = st.registration_open ? 'Criar minha conta' : 'Abrir a comunidade', url = st.registration_open ? '/?signup=1' : '/';
  const notice = st.announcement || (st.registration_open ? 'Compartilhe uma descoberta e comece uma conversa.' : 'Estamos preparando a abertura. Participantes com convite podem criar conta; quem já tem conta pode entrar.');
  const contact = /^[^\s@<>"\r\n]+@[^\s@<>"\r\n]+\.[^\s@<>"\r\n]+$/.test(c.env.SUPPORT_EMAIL || '') ? `<a href="mailto:${escape(c.env.SUPPORT_EMAIL)}">${escape(c.env.SUPPORT_EMAIL)}</a>` : 'O contato oficial será publicado antes da abertura.';
  let body, title, description;
  if (path === '/bem-vindo') {
    title = 'Descubra, guarde e compartilhe'; description = 'Uma rede social para transformar descobertas em conversas.';
    body = `<section class="hero"><div class="hero-copy"><p class="eyebrow"><span class="live-dot"></span> SUA CURIOSIDADE ENCONTRA COMPANHIA</p><h1>O que você descobre<br>merece <em>ser compartilhado.</em></h1><p class="lead">Encontre uma ideia. Guarde a referência. Comece uma conversa. Sua rede social, conectada ao que você encontra na web.</p><div class="actions"><a class="button primary" href="${url}">${cta} ↗</a><a class="button secondary" href="/como-funciona">Conheça o Synapse</a></div><p class="small">Pessoas, fotos e referências.</p></div><div class="preview" aria-label="Exemplo ilustrativo, não uma publicação de usuário"><div class="preview-top"><span class="mini-logo">✦</span><div><strong>Uma descoberta muda a conversa.</strong><small>Exemplo ilustrativo · Synapse</small></div></div><div class="preview-art"><span class="orbit o1"></span><span class="orbit o2"></span><span class="orbit o3"></span><span class="big-star">✦</span><span class="art-label">SIGA A CURIOSIDADE.</span></div><div class="preview-copy"><p class="preview-icons" aria-hidden="true">♡ &nbsp; ↗ &nbsp; ◇</p><strong>Encontrei algo que vale a conversa.</strong><p>Um tutorial, uma fotografia, uma ideia. Conte por que sua descoberta importa.</p><span class="topic">#descobertas</span> <span class="topic">#criatividade</span></div><span class="floating-note">↗ Encontre. Guarde. Conecte.</span></div></section><section class="status-strip" role="status"><span class="status-pill">${st.registration_open ? 'Cadastros abertos' : 'Lançamento em preparação'}</span><p>${escape(notice)}</p></section><section class="section"><div class="section-heading"><p class="eyebrow">MENOS LINKS PERDIDOS. MAIS CONVERSAS.</p><h2>Da descoberta à conexão.</h2></div><div class="steps"><article><span class="step-number">01</span><h3>Descubra</h3><p>Explore pessoas e publicações. Use os atalhos para continuar sua pesquisa na web.</p></article><article><span class="step-number">02</span><h3>Guarde</h3><p>Organize links em coleções privadas, com suas próprias notas.</p></article><article><span class="step-number">03</span><h3>Compartilhe</h3><p>Publique uma foto ou um link e encontre outras perspectivas.</p></article></div></section><section class="closing"><p class="eyebrow">UMA COMUNIDADE EM CONSTRUÇÃO</p><h2>Uma descoberta útil.<br>Uma pergunta de verdade.</h2><a class="button primary" href="${url}">${cta} ↗</a></section>`;
  } else if (path === '/como-funciona') {
    title = 'Como funciona'; description = 'Conheça o feed, as coleções e os controles de privacidade do Synapse.';
    const items = [
      ['Um feed para conversar', 'Publique textos, fotos e links. Siga perfis, curta e comente. Cada perfil controla a aprovação de seus seguidores.'],
      ['Pesquisa e referências', 'A busca interna encontra perfis e publicações. Os atalhos da web abrem buscadores externos; o Synapse não tem um índice próprio de toda a internet.'],
      ['Coleções que são suas', 'Links e notas das suas coleções ficam restritos à sua conta. Publicar no feed é uma escolha separada.'],
      ['No celular e no computador', 'A interface se adapta à tela. Navegadores compatíveis oferecem instalação como aplicativo web.'],
      ['Controle da sua conta', 'Bloqueie perfis, denuncie conteúdo, reveja sessões abertas e exporte ou exclua sua conta. Mensagens não possuem criptografia de ponta a ponta.'],
      ['Disponibilidade dos recursos', 'Esta edição Cloudflare oferece fotos e galerias. Vídeos, chamadas e notificações push não estão habilitados. A ativação social exige e-mail e faixa etária verificados; contas sociais de menores permanecem desabilitadas.']
    ];
    body = `<section class="text-page"><p class="eyebrow">SEU PRIMEIRO ENCONTRO COM O SYNAPSE</p><h1>Descubra junto.</h1><p class="lead">Uma rede social de pessoas, ideias e referências.</p><div class="info-grid">${items.map(([t, d]) => `<article><h2>${t}</h2><p>${d}</p></article>`).join('')}</div><a class="button primary" href="/">Abrir a comunidade ↗</a></section>`;
  } else {
    title = 'Ajuda'; description = 'Cadastro, privacidade, denúncias e contato da comunidade Synapse.';
    const items = [
      ['Como entro?', 'Abra a comunidade e entre com usuário ou e-mail. Cadastros dependem da abertura pelo responsável ou de um convite válido. Use uma senha exclusiva.'],
      ['Não recebi o e-mail.', 'Confira o spam e solicite um novo envio na Central de segurança. Procure o contato oficial se precisar de ajuda. Não envie senhas nem links de recuperação.'],
      ['Como denuncio ou bloqueio?', 'Use o menu da publicação ou do perfil. As denúncias são revistas pela equipe e o solicitante pode recorrer pela central de suporte.'],
      ['Minhas coleções e mensagens são públicas?', 'Coleções são privadas. Mensagens ficam restritas aos participantes na aplicação, mas não possuem criptografia de ponta a ponta. Apenas mensagens especificamente denunciadas podem ser analisadas no painel de moderação.'],
      ['Como excluo a conta?', 'Abra as configurações da conta e confirme sua senha em Excluir conta. A política publicada explica a retenção dos backups e dos registros operacionais.'],
      ['E crianças e adolescentes?', 'O acesso social de menores permanece desabilitado nesta edição. A aferição de faixa etária é feita pelo serviço contratado pelo responsável. Não envie documentos pelo suporte do Synapse.']
    ];
    body = `<section class="text-page"><p class="eyebrow">CENTRAL DE AJUDA</p><h1>Um lugar para<br>suas perguntas.</h1><div class="faq">${items.map(([t, d], i) => `<details${i === 0 ? ' open' : ''}><summary>${t}</summary><p>${d}</p></details>`).join('')}</div><section class="support"><h2>Contato oficial</h2><p>${contact}</p><p>Suporte, privacidade e segurança. Nunca envie sua senha.</p></section><a class="button secondary" href="/">Voltar à comunidade</a></section>`;
  }
  return htmlResponse(head(c, title, description, path) + body + footer);
}
async function policyPage(c, kind) {
  const row = await first(c, 'SELECT body,reviewed_at FROM site_policies WHERE kind=?', kind);
  if (!row) return htmlResponse(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${POLICY_TITLES[kind]} · Synapse</title><link rel="stylesheet" href="/legal.css"></head><body><header><a href="/bem-vindo">synapse.</a></header><main><h1>${POLICY_TITLES[kind]}</h1><p>O responsável ainda não publicou este documento. Os cadastros gerais permanecem fechados.</p><a href="/ajuda">Contato e ajuda</a></main></body></html>`);
  const paragraphs = row.body.split('\n\n').map(p => '<p>' + escape(p).replace(/\n/g, '<br>') + '</p>').join('');
  return htmlResponse(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${POLICY_TITLES[kind]} · Synapse</title><link rel="stylesheet" href="/legal.css"><script src="/legal.js" defer></script></head><body><header><a href="/">synapse.</a><p>Atualizado em ${escape(row.reviewed_at.slice(0, 10))}</p></header><main><h1>${POLICY_TITLES[kind]}</h1>${paragraphs}<section><h2>Contato</h2><p id="operator-info"></p></section></main><nav><a href="/terms.html">Termos</a><a href="/privacy.html">Privacidade</a><a href="/safety.html">Segurança</a><a href="/delete-account.html">Excluir conta</a></nav></body></html>`);
}

export default function register(router) {
  for (const path of ['/admin', '/admin/']) router.on('GET', path, c => asset(c, '/admin.html'));
  router.on('GET', '/api/manage/session', async c => {
    const user = needUser(c), role = await operatorRole(c);
    if (!role) fail(403, 'Esta conta não tem acesso ao painel.');
    const sec = await first(c, 'SELECT enabled FROM operator_security WHERE user_id=?', user.id);
    const elevated = await first(c, 'SELECT expires FROM admin_grants WHERE token_hash=? AND user_id=? AND expires>?', c.sessionHash, user.id, stamp());
    return { name: user.name, handle: user.handle, role, csrf: user.csrf, email_verified: Boolean(user.email_verified), mfa_enabled: Boolean(sec?.enabled), mfa_required: true, unlocked_until: elevated?.expires || 0, production: production(c) };
  });
  router.on('POST', '/api/manage/security/enroll', async c => {
    const user = await requireOperator(c), d = await json(c); await checkedPassword(c, user, d.password);
    const secret = base32(crypto.getRandomValues(new Uint8Array(20))), encrypted = await encryptSecret(c, secret);
    await run(c, 'INSERT OR IGNORE INTO operator_security(user_id) VALUES(?)', user.id);
    const result = await run(c, 'UPDATE operator_security SET pending=?,pending_expires=? WHERE user_id=? AND enabled=0', encrypted, stamp() + 600, user.id);
    if (changes(result) !== 1) fail(409, 'Segundo fator já ativado. Use um código de recuperação se necessário.');
    await adminEvent(c, user, 'mfa_enrollment_started', 'operator', user.id);
    const params = new URLSearchParams({ secret, issuer: 'Synapse', algorithm: 'SHA1', digits: '6', period: '30' });
    return { secret, uri: 'otpauth://totp/' + encodeURIComponent('Synapse:' + user.handle) + '?' + params, expires_in: 600 };
  });
  router.on('POST', '/api/manage/security/confirm', async c => {
    const user = await requireOperator(c), d = await json(c); await rate(c, 'admin-code:' + user.id, 8, 300);
    const row = await first(c, 'SELECT * FROM operator_security WHERE user_id=?', user.id);
    if (!row || row.enabled || !row.pending || row.pending_expires <= stamp()) fail(409, 'Inicie novamente a configuração do autenticador.');
    const secret = await decryptSecret(c, row.pending), step = await validStep(secret, d.code, -1);
    const recovery = Array.from({ length: 8 }, () => uid().slice(0, 16));
    const hashes = JSON.stringify(await Promise.all(recovery.map(x => sha256(x))));
    const result = await run(c, "UPDATE operator_security SET secret=pending,pending='',pending_expires=0,enabled=1,last_step=?,recovery_hashes=? WHERE user_id=? AND enabled=0 AND pending=? AND pending_expires>?", step, hashes, user.id, row.pending, stamp());
    if (changes(result) !== 1) fail(409, 'A configuração mudou. Recarregue o painel.');
    const expiry = await grant(c, user, 'mfa_enabled');
    return { ok: true, recovery_codes: recovery, unlocked_until: expiry };
  });
  router.on('POST', '/api/manage/unlock', async c => {
    const user = await requireOperator(c), d = await json(c); await checkedPassword(c, user, d.password);
    const row = await first(c, 'SELECT * FROM operator_security WHERE user_id=?', user.id);
    if (!row?.enabled) fail(403, 'Ative o segundo fator antes de desbloquear o painel.');
    const code = typeof d.code === 'string' ? d.code.trim().toLowerCase() : '';
    let result, action = 'admin_unlocked';
    if (/^[a-f0-9]{16}$/.test(code)) {
      const digest = await sha256(code), hashes = JSON.parse(row.recovery_hashes || '[]');
      if (!hashes.some(x => equal(x, digest))) fail(401, 'Código de recuperação inválido ou já utilizado.');
      const remaining = JSON.stringify(hashes.filter(x => !equal(x, digest)));
      result = await run(c, 'UPDATE operator_security SET recovery_hashes=? WHERE user_id=? AND enabled=1 AND recovery_hashes=?', remaining, user.id, row.recovery_hashes);
      action = 'mfa_recovery_used';
    } else {
      const secret = await decryptSecret(c, row.secret), step = await validStep(secret, code, row.last_step);
      result = await run(c, 'UPDATE operator_security SET last_step=? WHERE user_id=? AND enabled=1 AND last_step=? AND secret=?', step, user.id, row.last_step, row.secret);
    }
    if (changes(result) !== 1) fail(401, 'Código já utilizado. Aguarde um novo código.');
    return { ok: true, unlocked_until: await grant(c, user, action) };
  });
  router.on('POST', '/api/manage/lock', async c => { needUser(c); await run(c, 'DELETE FROM admin_grants WHERE token_hash=?', c.sessionHash); return { ok: true }; });
  router.on('GET', '/api/public-info', c => ({operator:c.env.OPERATOR_NAME||'',support_email:c.env.SUPPORT_EMAIL||'',child_safety_email:c.env.CHILD_SAFETY_EMAIL||c.env.SUPPORT_EMAIL||'',production:production(c)}));
  router.on('GET', '/api/site', async c => ({ name: 'Synapse', version: '1.0.0-rc.1', production: production(c), ...await publicSiteSettings(c), support_email: c.env.SUPPORT_EMAIL || '' }));
  router.on('GET', '/api/manage/overview', async c => {
    await requireAdmin(c);
    const counts = {
      users: await n(c, "SELECT COUNT(*) n FROM actors WHERE kind='human' AND seeded=0"),
      active_users: await n(c, "SELECT COUNT(*) n FROM actors WHERE kind='human' AND seeded=0 AND active=1"),
      verified_users: await n(c, "SELECT COUNT(*) n FROM actors WHERE kind='human' AND seeded=0 AND email_verified=1"),
      posts: await n(c, 'SELECT COUNT(*) n FROM posts p JOIN actors a ON a.id=p.author_id WHERE a.seeded=0'),
      hidden_posts: await n(c, 'SELECT COUNT(*) n FROM posts WHERE hidden=1'),
      reports: await n(c, "SELECT (SELECT COUNT(*) FROM reports WHERE status='open')+(SELECT COUNT(*) FROM content_reports WHERE status='open') n"),
      media_bytes: await n(c, 'SELECT COALESCE(SUM(bytes),0) n FROM media_assets'),
      mail_failures_24h: await n(c, "SELECT COUNT(*) n FROM audit WHERE action='mail_delivery_failed' AND created_at>?", new Date(Date.now() - 86400000).toISOString())
    };
    return { counts, settings: await settings(c), events: await query(c, 'SELECT * FROM admin_events ORDER BY created_at DESC,id DESC LIMIT 8'), daily_signups: await query(c, 'SELECT substr(created_at,1,10) day,COUNT(*) users FROM actors WHERE seeded=0 AND created_at>=? GROUP BY day ORDER BY day', new Date(Date.now() - 7 * 86400000).toISOString()), version: '1.0.0-rc.1', production: production(c) };
  });
  router.on('GET', '/api/manage/users', async c => {
    const user = await requireAdmin(c), q = queryText(c), page = pageNumber(c), status = pick(c.url.searchParams.get('status') || 'all', ['all','active','suspended'], 'Estado');
    let where = "a.kind='human' AND a.seeded=0 AND (instr(lower(a.handle),lower(?))>0 OR instr(lower(a.name),lower(?))>0)", params = [q,q];
    if (status !== 'all') { where += ' AND a.active=?'; params.push(status === 'active' ? 1 : 0); }
    const total = await n(c, 'SELECT COUNT(*) n FROM actors a WHERE ' + where, ...params);
    const items = await query(c, "SELECT a.id,a.name,a.handle,a.email,a.email_verified,a.active,a.created_at,CASE WHEN o.user_id IS NULL THEN 'member' ELSE COALESCE(r.role,'owner') END role,(SELECT COUNT(*) FROM posts p WHERE p.author_id=a.id) posts FROM actors a LEFT JOIN operators o ON o.user_id=a.id LEFT JOIN operator_roles r ON r.user_id=a.id WHERE " + where + ' ORDER BY a.created_at DESC,a.id DESC LIMIT 25 OFFSET ?', ...params, (page - 1) * 25);
    if (user.role !== 'owner') for (const item of items) delete item.email;
    return { items, total, page, page_size: 25 };
  });
  router.on('POST', '/api/manage/users/:target_id/actions', async c => {
    const user = await requireAdmin(c), d = await json(c), action = pick(d.action,['suspend','reactivate','revoke_sessions'],'Ação'), why = reason(d), id = c.params.target_id;
    await protectUser(c, user, id);
    const statements = [];
    if (action !== 'revoke_sessions') statements.push(['UPDATE actors SET active=? WHERE id=?', action === 'reactivate' ? 1 : 0, id]);
    if (action !== 'reactivate') statements.push(['DELETE FROM sessions WHERE user_id=?', id], ['DELETE FROM auth_tokens WHERE user_id=?', id], ['DELETE FROM push_subscriptions WHERE user_id=?', id], ['DELETE FROM calls WHERE caller_id=? OR callee_id=?', id,id]);
    statements.push(eventStatement(user, 'user_' + action, 'user', id, why)); await batch(c, statements); return { ok: true };
  });
  router.on('POST', '/api/manage/users/:target_id/role', async c => {
    const user = await requireAdmin(c, true), d = await json(c), role = pick(d.role,['member','moderator'],'Permissão'), why = reason(d), id = c.params.target_id;
    const target = await protectUser(c, user, id), statements = [];
    if (role === 'moderator') {
      if (!target.active || !target.email_verified) fail(409, 'O moderador precisa estar ativo e confirmar seu e-mail.');
      statements.push(['INSERT OR IGNORE INTO operators(user_id,created_at) VALUES(?,?)',id,now()], ["INSERT INTO operator_roles(user_id,role) VALUES(?,'moderator') ON CONFLICT(user_id) DO UPDATE SET role='moderator'",id]);
    } else statements.push(['DELETE FROM operators WHERE user_id=?',id]);
    statements.push(['DELETE FROM admin_grants WHERE user_id=?',id], eventStatement(user,'role_'+role,'user',id,why)); await batch(c,statements); return {ok:true};
  });
  router.on('GET', '/api/manage/posts', async c => {
    await requireAdmin(c); const q=queryText(c),page=pageNumber(c),status=pick(c.url.searchParams.get('status')||'all',['all','visible','hidden'],'Estado');
    let where='a.seeded=0 AND (instr(lower(p.body),lower(?))>0 OR instr(lower(a.handle),lower(?))>0)',params=[q,q];
    if(status!=='all'){where+=' AND p.hidden=?';params.push(status==='hidden'?1:0);}
    return {items:await query(c,'SELECT p.id,p.body,p.created_at,p.hidden,p.link_url,p.image_path,a.handle,a.name FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+where+' ORDER BY p.created_at DESC,p.id DESC LIMIT 20 OFFSET ?',...params,(page-1)*20), total:await n(c,'SELECT COUNT(*) n FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+where,...params),page,page_size:20};
  });
  router.on('POST','/api/manage/posts/:post_id',async c=>{
    const user=await requireAdmin(c),d=await json(c),hidden=boolean(d.hidden,'Visibilidade'),why=reason(d),id=c.params.post_id;
    if(!await first(c,'SELECT id FROM posts WHERE id=?',id))fail(404,'Publicação não encontrada.');
    await batch(c,[['UPDATE posts SET hidden=? WHERE id=?',hidden,id],eventStatement(user,hidden?'post_hidden':'post_restored','post',id,why)]);return {ok:true};
  });
  router.on('GET','/api/manage/reports',async c=>{
    await requireAdmin(c);const page=pageNumber(c),status=pick(c.url.searchParams.get('status')||'open',['all','open','removed','dismissed'],'Estado');
    const union="SELECT id,reporter_id,'post' kind,post_id target_id,reason,status,created_at FROM reports UNION ALL SELECT id,reporter_id,kind,target_id,reason,status,created_at FROM content_reports",where=status==='all'?'':' WHERE status=?',args=status==='all'?[]:[status];
    const items=await query(c,'SELECT * FROM ('+union+')'+where+' ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET ?',...args,(page-1)*20);
    for(const r of items){const table={post:'posts',profile:'actors',comment:'comments',story:'stories',message:'messages'}[r.kind];const target=table?await first(c,'SELECT '+(r.kind==='profile'?'bio':'body')+' content FROM '+table+' WHERE id=?',r.target_id):null;r.content=target?.content||'[Conteúdo não disponível]';r.reporter_handle=(await first(c,'SELECT handle FROM actors WHERE id=?',r.reporter_id))?.handle||'Conta removida';}
    return {items,total:await n(c,'SELECT COUNT(*) n FROM ('+union+')'+where,...args),page,page_size:20};
  });
  router.on('POST','/api/manage/reports/:report_id',async c=>{
    const user=await requireAdmin(c),d=await json(c),action=pick(d.action,['remove','dismiss'],'Decisão'),why=reason(d),id=c.params.report_id;
    let report=await first(c,'SELECT *,post_id AS target_id FROM reports WHERE id=?',id),table='reports';if(report)report.kind='post';else{table='content_reports';report=await first(c,'SELECT * FROM content_reports WHERE id=?',id);}
    if(!report)fail(404,'Denúncia não encontrada.');if(report.status!=='open')fail(409,'A denúncia já foi analisada.');
    // Every effect is conditional inside the same D1 transaction. A concurrent
    // reviewer cannot apply a second decision after another batch closes it.
    const statements=[],guard=" AND EXISTS(SELECT 1 FROM "+table+" WHERE id=? AND status='open')";
    if(action==='remove'){
      if(report.kind==='profile'){await protectUser(c,user,report.target_id);statements.push(['UPDATE actors SET active=0 WHERE id=?'+guard,report.target_id,id],['DELETE FROM sessions WHERE user_id=?'+guard,report.target_id,id],['DELETE FROM auth_tokens WHERE user_id=?'+guard,report.target_id,id]);}
      else if(report.kind==='post')statements.push(['UPDATE posts SET hidden=1 WHERE id=?'+guard,report.target_id,id]);
      else{const targetTable={comment:'comments',story:'stories',message:'messages'}[report.kind];if(!targetTable)fail(422,'Tipo de denúncia inválido.');statements.push(['DELETE FROM '+targetTable+' WHERE id=?'+guard,report.target_id,id]);}
    }
    statements.push(["INSERT INTO admin_events(id,actor_id,actor_label,action,target_type,target_id,reason,created_at) SELECT ?,?,?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM "+table+" WHERE id=? AND status='open')",uid(),user.id,'@'+user.handle,'report_'+action,'report',id,why,now(),id]);
    statements.push(["UPDATE "+table+" SET status=? WHERE id=? AND status='open'",action==='remove'?'removed':'dismissed',id]);
    const results=await batch(c,statements);if(changes(results.at(-1))!==1)fail(409,'A denúncia já foi analisada.');return {ok:true};
  });
  router.on('GET','/api/manage/audit',async c=>{await requireAdmin(c,true);const page=pageNumber(c);return {items:await query(c,'SELECT * FROM admin_events ORDER BY created_at DESC,id DESC LIMIT 30 OFFSET ?',(page-1)*30),total:await n(c,'SELECT COUNT(*) n FROM admin_events'),page,page_size:30};});
  router.on('GET','/api/manage/policies',async c=>{await requireAdmin(c,true);const rows=await query(c,'SELECT * FROM site_policies');return {items:Object.entries(POLICY_TITLES).map(([kind,title])=>({kind,title,body:'',reviewed_at:null,...rows.find(x=>x.kind===kind)}))};});
  router.on('PUT','/api/manage/policies/:kind',async c=>{
    const user=await requireAdmin(c,true),kind=pick(c.params.kind,Object.keys(POLICY_TITLES),'Documento'),d=await json(c),body=text(d.body,300,30000,'Documento'),why=reason(d);if(d.reviewed!==true)fail(422,'Confirme a revisão do documento.');
    const at=now();await batch(c,[['INSERT INTO site_policies(kind,body,reviewed_by,reviewed_at) VALUES(?,?,?,?) ON CONFLICT(kind) DO UPDATE SET body=excluded.body,reviewed_by=excluded.reviewed_by,reviewed_at=excluded.reviewed_at',kind,body,user.id,at],['INSERT INTO policy_reviews(kind,release,body_hash,reviewed_at) VALUES(?,?,?,?) ON CONFLICT(kind) DO UPDATE SET release=excluded.release,body_hash=excluded.body_hash,reviewed_at=excluded.reviewed_at',kind,'1.0',await sha256(body),at],eventStatement(user,'policy_published','policy',kind,why)]);return {ok:true};
  });
  router.on('GET','/api/manage/launch',async c=>{await requireAdmin(c,true);const ready=await launchReadiness(c);return {checks:ready.checks,can_open:ready.ready,settings:await settings(c),notice:'Os testes externos e as declarações do responsável são identificados separadamente. A configuração não equivale a auditoria independente ou certificação jurídica.'};});
  router.on('POST','/api/manage/launch/:name',async c=>{
    const user=await requireAdmin(c,true),name=pick(c.params.name,Object.keys(ATTESTATIONS),'Verificação'),d=await json(c),note=text(d.note,20,800,'Registro');if(d.confirmed!==true)fail(422,'Confirme a verificação.');
    await batch(c,[['INSERT INTO launch_attestations(name,actor_id,note,origin,created_at) VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET actor_id=excluded.actor_id,note=excluded.note,origin=excluded.origin,created_at=excluded.created_at',name,user.id,note,c.env.PUBLIC_ORIGIN||'',now()],eventStatement(user,'launch_attestation','check',name,note)]);return {ok:true};
  });
  router.on('GET','/api/manage/settings',async c=>{await requireAdmin(c,true);return settings(c);});
  router.on('PATCH','/api/manage/settings',async c=>{
    const user=await requireAdmin(c,true),d=await json(c),open=boolean(d.registration_open,'Cadastro'),maintenance=boolean(d.maintenance,'Manutenção'),uploads=boolean(d.uploads_enabled,'Uploads'),announcement=text(d.announcement??'',0,300,'Aviso'),why=reason(d);
    if(open && !(await launchReadiness(c)).ready)fail(409,'Existem pendências na aba Lançamento. Conclua-as antes de abrir novos cadastros.');
    await batch(c,[['UPDATE site_settings SET registration_open=?,maintenance=?,uploads_enabled=?,announcement=?,updated_at=? WHERE id=1',open,maintenance,uploads,announcement,now()],eventStatement(user,'site_settings_changed','site','',why)]);return {ok:true};
  });
  router.on('POST','/api/manage/remove-examples',async c=>{
    const user=await requireAdmin(c,true),d=await json(c),why=reason(d),total=await n(c,'SELECT COUNT(*) n FROM actors WHERE seeded=1');
    await batch(c,[['DELETE FROM actors WHERE seeded=1'],eventStatement(user,'examples_removed','site','',why)]);return {ok:true,removed_profiles:total};
  });
  router.on('GET','/api/manage/health',async c=>{
    await requireAdmin(c,true);const check=await first(c,'PRAGMA quick_check(1)'),ready=await launchReadiness(c);
    return {database_ok:Object.values(check||{}).includes('ok'),free_bytes:null,database_bytes:null,storage:'Cloudflare D1 + R2 privado',media_bytes:await n(c,'SELECT COALESCE(SUM(bytes),0) n FROM media_assets'),unattached_uploads:await n(c,'SELECT COUNT(*) n FROM media_assets WHERE post_id IS NULL'),capabilities:{gallery:true,video:false,push:false,calls:false},mail_mode:c.env.MAIL_PROVIDER||'api',backup:'Consulte o guia de backup da edição Cloudflare. D1 Time Travel e cópias R2 exigem configuração, retenção e teste de restauração; não representam uma cópia externa verificada por este painel.',deployment_checks:Object.fromEntries(ready.checks.map(x=>[x.id,x.ok]))};
  });
  router.on('GET','/api/manage/invites',async c=>{
    await requireAdmin(c,true);const items=await query(c,'SELECT id,label,max_uses,uses,expires,revoked,created_at FROM pilot_invites ORDER BY created_at DESC LIMIT 100');for(const r of items)r.available=!r.revoked&&r.expires>stamp()&&r.uses<r.max_uses;
    return {items,notice:'Convites permitem cadastro limitado com inscrições gerais fechadas. E-mail, faixa etária e demais requisitos de ativação continuam obrigatórios.'};
  });
  router.on('POST','/api/manage/invites',async c=>{
    const user=await requireAdmin(c,true),d=await json(c),label=text(d.label,3,80,'Identificação'),max=integer(d.max_uses??1,1,50,'Vagas'),days=integer(d.days??7,1,30,'Prazo');await rate(c,'invite-create:'+user.id,20,3600);
    const code=token(32),id=uid(),expires=stamp()+days*86400;await batch(c,[['INSERT INTO pilot_invites(id,code_hash,label,created_by,max_uses,uses,expires,revoked,created_at) VALUES(?,?,?,?,?,0,?,0,?)',id,await sha256(code),label,user.id,max,expires,now()],eventStatement(user,'invite_created','invite',id,'Convite: '+label)]);
    return {id,code,url:publicOrigin(c)+'/?signup=1#convite='+code,expires,notice:'Guarde agora. O código só aparece nesta resposta. Compartilhe o convite apenas com as pessoas autorizadas.'};
  });
  router.on('POST','/api/manage/invites/:invite_id/revoke',async c=>{
    const user=await requireAdmin(c,true),d=await json(c),why=reason(d),id=c.params.invite_id;if(!await first(c,'SELECT id FROM pilot_invites WHERE id=?',id))fail(404,'Convite não encontrado.');
    await batch(c,[['UPDATE pilot_invites SET revoked=1 WHERE id=?',id],eventStatement(user,'invite_revoked','invite',id,why)]);return {ok:true};
  });
  router.on('GET','/api/manage/growth',async c=>{
    await requireAdmin(c,true);const cutoff=new Date(Date.now()-7*86400000).toISOString(),members="a.seeded=0 AND a.kind='human' AND NOT EXISTS(SELECT 1 FROM operators o WHERE o.user_id=a.id)";
    const counts={members:await n(c,'SELECT COUNT(*) n FROM actors a WHERE '+members),verified:await n(c,'SELECT COUNT(*) n FROM actors a WHERE '+members+' AND a.email_verified=1'),creators:await n(c,'SELECT COUNT(*) n FROM actors a WHERE '+members+' AND EXISTS(SELECT 1 FROM posts p WHERE p.author_id=a.id AND p.hidden=0)'),new_7d:await n(c,'SELECT COUNT(*) n FROM actors a WHERE '+members+' AND a.created_at>=?',cutoff),posting_7d:await n(c,'SELECT COUNT(DISTINCT p.author_id) n FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+members+' AND p.created_at>=? AND p.hidden=0',cutoff),posts_7d:await n(c,'SELECT COUNT(*) n FROM posts p JOIN actors a ON a.id=p.author_id WHERE '+members+' AND p.created_at>=? AND p.hidden=0',cutoff),invited_signups:await n(c,'SELECT COALESCE(SUM(uses),0) n FROM pilot_invites')};
    counts.activation_percent=counts.members?Math.round(1000*counts.creators/counts.members)/10:0;
    return {counts,daily:await query(c,'SELECT substr(a.created_at,1,10) day,COUNT(*) total FROM actors a WHERE '+members+' AND a.created_at>=? GROUP BY day ORDER BY day',cutoff),notice:'Agregados reais do banco, excluindo exemplos e administradores. Ativação: contas com publicação visível / contas de membros. Não mede visitantes únicos, pessoas online ou retenção.'};
  });
  for(const path of ['/bem-vindo','/como-funciona','/ajuda'])router.on('GET',path,c=>publicPage(c,path));
  for(const [path,kind] of Object.entries({'/terms.html':'terms','/termos':'terms','/privacy.html':'privacy','/privacidade':'privacy','/safety.html':'safety','/regras':'safety'}))router.on('GET',path,c=>policyPage(c,kind));
  router.on('GET','/robots.txt',c=>new Response('User-agent: *\nAllow: /\nDisallow: /*?\n'+(indexing(c)?'Sitemap: '+publicOrigin(c)+'/sitemap.xml\n':''),{headers:{'content-type':'text/plain; charset=utf-8','cache-control':'no-cache'}}));
  router.on('GET','/sitemap.xml',c=>new Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+(indexing(c)?['/bem-vindo','/como-funciona','/ajuda'].map(path=>'<url><loc>'+escape(publicOrigin(c)+path)+'</loc></url>').join(''):'')+'</urlset>',{headers:{'content-type':'application/xml','cache-control':'no-cache'}}));
}
