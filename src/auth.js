import {
  fail, uid, now, stamp, sha256, equal, query, first, run, batch, json, text, email,
  needUser, publicActor, settings, termsVersion, rate, hashPassword,
  setSession, clearSession, issueToken, removeMedia
} from './core.js';

import {isExternal, checkCredential, replaceCredential, confirmCredential} from './credentials.js';
import {provisionCredential, finishProvision, withCredentialLock, processCredentialCleanup} from './credential-operations.js';

const production = c => c.env.APP_ENV !== 'development';
const network = c => c.request.headers.get('CF-Connecting-IP') || 'local';
const changed = result => Number(result?.meta?.changes ?? result?.changes ?? 0);

function fields(data, allowed) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) fail(422, 'Dados inválidos.');
  for (const key of Object.keys(data)) if (!allowed.includes(key)) fail(422, 'Campo não permitido: ' + key);
}
function password(value, minimum = 10) {
  if (typeof value !== 'string' || value.length < minimum || value.length > 128) {
    fail(422, `A senha deve ter de ${minimum} a 128 caracteres.`);
  }
  return value;
}
function handle(value) {
  const h = text(value, 3, 24, 'Usuário').toLowerCase();
  if (!/^[a-z0-9_.]{3,24}$/.test(h)) fail(422, 'Use letras, números, ponto ou sublinhado no usuário.');
  return h;
}
function enumValue(value, fallback, choices, label) {
  const v = value === undefined ? fallback : value;
  if (!choices.includes(v)) fail(422, label + ' inválido.');
  return v;
}
function isConstraint(error) {
  return /UNIQUE constraint failed|PRIMARY KEY constraint failed|SQLITE_CONSTRAINT/i.test(String(error?.message || error));
}

// Verification is always server-side and fails closed in production. A successful
// provider HTTP request alone is not enough: hostname and action must match.
export async function verifyBot(c, value) {
  const configured = Boolean(c.env.TURNSTILE_SITE_KEY && c.env.TURNSTILE_SECRET_KEY);
  if (!configured) {
    if (production(c)) fail(503, 'Cadastro pausado: configure a proteção antiautomação.');
    return;
  }
  const responseToken = text(value, 1, 2048, 'Verificação antiautomação');
  let hostname;
  try { hostname = new URL(c.env.PUBLIC_ORIGIN).hostname; }
  catch { fail(503, 'Endereço público ainda não configurado.'); }
  let response, result;
  try {
    const params = new URLSearchParams({secret: c.env.TURNSTILE_SECRET_KEY, response: responseToken});
    const ip = c.request.headers.get('CF-Connecting-IP');
    if (ip) params.set('remoteip', ip);
    response = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST', body: params, redirect: 'manual', signal: AbortSignal.timeout(8000)
    });
    if (!response.ok) throw new Error('provider status');
    result = await response.json();
  } catch {
    fail(503, 'A proteção antiautomação não respondeu. Tente novamente.');
  }
  if (result?.success !== true || result.hostname !== hostname || result.action !== 'signup') {
    fail(403, 'Verificação antiautomação recusada. Atualize o desafio.');
  }
  const {recordIntegration} = await import('./safety.js');
  await recordIntegration(c, 'turnstile', 'Desafio validado no servidor com domínio e ação.');
}

async function signup(c) {
  const data = await json(c);
  fields(data, ['name','handle','email','password','terms_accepted','invite_code','turnstile_token']);
  const name = text(data.name, 2, 50, 'Nome');
  const username = handle(data.handle);
  const address = email(data.email);
  const secret = password(data.password);
  if (data.terms_accepted !== true) fail(422, 'Leia e aceite os Termos para se cadastrar.');
  const invite = data.invite_code === undefined ? '' : text(data.invite_code, 0, 128, 'Convite');
  if (invite && !/^[A-Za-z0-9_-]{32,128}$/.test(invite)) fail(403, 'Convite inválido ou expirado.');
  await rate(c, 'signup:' + network(c), 20, 600);
  const site = await settings(c);
  if (site.maintenance) fail(503, 'Cadastros pausados durante a manutenção.');
  if (!site.registration_open && !invite) fail(403, 'Cadastros fechados. Use um convite válido.');
  if (production(c) && !invite) {
    const {launchReadiness} = await import('./safety.js');
    const readiness = await launchReadiness(c);
    if (!readiness.ready) fail(503, 'A abertura geral aguarda a conclusão das verificações no painel.');
  }
  const codeHash = invite ? await sha256(invite) : '';
  if (invite && !(await first(c, `SELECT id FROM pilot_invites WHERE code_hash=? AND revoked=0 AND expires>? AND uses<max_uses`, codeHash, stamp()))) {
    fail(403, 'Convite inválido, expirado, revogado ou sem vagas.');
  }
  await verifyBot(c, data.turnstile_token || '');
  const id = uid(), created = now(), encoded = await provisionCredential(c, address, secret), terms = await termsVersion(c);
  let results;
  try {
    // All conditional writes run inside one D1 batch transaction. The actor is
    // inserted only if the current settings/invite still permit it. Consuming a
    // code is conditional on that exact actor having been inserted, so two
    // simultaneous requests cannot take the final invitation slot twice.
    results = await batch(c, [
      [`INSERT INTO actors(id,handle,name,kind,bio,color,password_hash,created_at,email,terms_version,dm_policy,account_private)
        SELECT ?,?,?,'human','','violet',?,?,?,?,'following',1
        WHERE EXISTS(SELECT 1 FROM site_settings WHERE id=1 AND maintenance=0
          AND ((registration_open=1 AND ?='') OR EXISTS(SELECT 1 FROM pilot_invites WHERE code_hash=? AND revoked=0 AND expires>? AND uses<max_uses)))`,
        id, username, name, encoded, created, address, terms, invite, codeHash, stamp()],
      [`UPDATE pilot_invites SET uses=uses+1 WHERE code_hash=? AND EXISTS(SELECT 1 FROM actors WHERE id=?)`, codeHash, id],
      [`INSERT INTO audit(id,owner_id,action,subject_id,summary,created_at)
        SELECT ?,?,'account_created',?, ?,? WHERE EXISTS(SELECT 1 FROM actors WHERE id=?)`,
        uid(), id, id, 'Termos ' + terms + ' aceitos. E-mail pendente de confirmação.', created, id],
      ...finishProvision(c, encoded, id)
    ]);
  } catch (error) {
    if (isConstraint(error)) fail(409, 'Não foi possível cadastrar: usuário ou e-mail indisponível.');
    throw error;
  }
  if (changed(results[0]) !== 1) fail(403, 'O cadastro ou convite não está mais disponível.');
  const csrf = await setSession(c, id, encoded);
  await issueToken(c, {id, email: address}, 'verify');
  return {ok: true, csrf, verification_pending: true};
}

async function login(c) {
  const data = await json(c);
  fields(data, ['handle','password']);
  const identifier = text(data.handle, 1, 254, 'Usuário ou e-mail').toLowerCase();
  const secret = password(data.password, 1);
  await rate(c, 'login-account:' + await sha256(identifier), 10, 300);
  await rate(c, 'login-network:' + network(c), 120, 60);
  const user = await first(c, `SELECT * FROM actors WHERE (handle=? COLLATE NOCASE OR email=? COLLATE NOCASE)
    AND kind='human' AND active=1 AND seeded=0`, identifier, identifier);
  const correct = await checkCredential(c, user, secret);
  if (!user || !correct) fail(401, 'Usuário ou senha incorretos.');
  return {ok: true, csrf: await setSession(c, user.id, user.password_hash)};
}

async function resetPassword(c) {
  const data = await json(c);
  fields(data, ['token','password']);
  const tokenHash = await sha256(text(data.token, 20, 128, 'Código'));
  const secret = password(data.password);
  await rate(c, 'reset:' + network(c), 6, 300);
  const found = await first(c, `SELECT user_id FROM auth_tokens WHERE token_hash=? AND purpose='reset' AND expires>?`, tokenHash, stamp());
  if (!found) fail(400, 'Link inválido ou expirado. Solicite outro.');
  const user = await first(c, 'SELECT * FROM actors WHERE id=? AND active=1', found.user_id);
  if (!user) fail(400, 'Link inválido ou expirado. Solicite outro.');
  if (c.env.AUTH_PROVIDER === 'supabase' || isExternal(user.password_hash)) {
    return withCredentialLock(c, user, async () => {
      // Atomically consume proof before any remote password mutation. A failed
      // provider operation requires a NEW link, never replaying the old one.
      const claimed = await run(c, "DELETE FROM auth_tokens WHERE token_hash=? AND purpose='reset' AND expires>? AND user_id=?", tokenHash, stamp(), user.id);
      if (changed(claimed) !== 1) fail(400, 'Link inválido ou expirado. Solicite outro.');
      await run(c, 'DELETE FROM sessions WHERE user_id=?', user.id);
      const encoded = isExternal(user.password_hash)
        ? await replaceCredential(c, user, secret)
        : await provisionCredential(c, user.email, secret);
      const saved = await batch(c, [
        ['UPDATE actors SET password_hash=? WHERE id=? AND password_hash=? AND active=1', encoded, user.id, user.password_hash],
        ['DELETE FROM sessions WHERE user_id=?', user.id],
        ["DELETE FROM auth_tokens WHERE user_id=? AND purpose='reset'", user.id],
        ...finishProvision(c, encoded, user.id)
      ]);
      if (changed(saved[0]) !== 1) fail(409, 'A conta foi alterada. Solicite outro link de recuperação.');
      return {ok:true};
    });
  }
  const encoded = await hashPassword(secret), time = stamp();
  const valid = `EXISTS(SELECT 1 FROM auth_tokens WHERE token_hash=? AND purpose='reset' AND expires>? AND user_id=?)`;
  const result = await batch(c, [
    [`UPDATE actors SET password_hash=? WHERE id=? AND active=1 AND ${valid}`, encoded, found.user_id, tokenHash, time, found.user_id],
    [`DELETE FROM sessions WHERE user_id=? AND ${valid}`, found.user_id, tokenHash, time, found.user_id],
    [`DELETE FROM auth_tokens WHERE user_id=? AND ${valid}`, found.user_id, tokenHash, time, found.user_id]
  ]);
  if (changed(result[0]) !== 1) fail(400, 'Link inválido ou expirado. Solicite outro.');
  return {ok: true};
}

async function verifyEmail(c) {
  const data = await json(c); fields(data, ['token']);
  const tokenHash = await sha256(text(data.token, 20, 128, 'Código'));
  await rate(c, 'verify:' + network(c), 10, 300);
  const pending = await first(c, `SELECT a.* FROM actors a JOIN auth_tokens t ON t.user_id=a.id WHERE t.token_hash=? AND t.purpose='verify' AND t.expires>? AND a.active=1`, tokenHash, stamp());
  const result = await batch(c, [
    [`UPDATE actors SET email_verified=1 WHERE active=1 AND id=(SELECT user_id FROM auth_tokens WHERE token_hash=? AND purpose='verify' AND expires>?)`, tokenHash, stamp()],
    [`DELETE FROM auth_tokens WHERE token_hash=? AND purpose='verify'`, tokenHash]
  ]);
  if (changed(result[0]) !== 1) fail(400, 'Link inválido ou expirado. Solicite outro.');
  // Local proof is authoritative. If provider synchronization fails, login
  // retries it using the already-verified D1 record; never fabricate proof.
  if (pending && isExternal(pending.password_hash)) {
    try { await confirmCredential(c, {...pending,email_verified:1}); }
    catch { console.error('credential_confirmation_pending'); }
  }
  const {recordIntegration} = await import('./safety.js');
  await recordIntegration(c, 'email_verification', 'Link de confirmação consumido; evento técnico, não confirmação de entrega na caixa de entrada.');
  return {ok: true};
}

async function changePassword(c) {
  const user = await needUser(c), data = await json(c);
  fields(data, ['current_password','password']);
  const current = password(data.current_password, 1), next = password(data.password);
  await rate(c, 'password:' + user.id, 5, 300);
  if (!await checkCredential(c, user, current)) fail(401, 'Senha atual incorreta.');
  if (isExternal(user.password_hash)) {
    return withCredentialLock(c, user, async () => {
      await run(c, 'DELETE FROM sessions WHERE user_id=?', user.id);
      const encoded = await replaceCredential(c, user, next);
      const saved = await batch(c, [
        ['UPDATE actors SET password_hash=? WHERE id=? AND password_hash=? AND active=1', encoded, user.id, user.password_hash],
        ['DELETE FROM sessions WHERE user_id=?', user.id],
        ["DELETE FROM auth_tokens WHERE user_id=? AND purpose='reset'", user.id]
      ]);
      if (changed(saved[0]) !== 1) fail(409, 'A conta foi alterada. Entre novamente.');
      await clearSession(c);
      return {ok:true,login_required:true};
    });
  }
  const encoded = await hashPassword(next);
  const results = await batch(c, [
    ['UPDATE actors SET password_hash=? WHERE id=? AND password_hash=? AND active=1', encoded, user.id, user.password_hash],
    ['DELETE FROM sessions WHERE user_id=? AND EXISTS(SELECT 1 FROM actors WHERE id=? AND password_hash=?)', user.id, user.id, encoded],
    ["DELETE FROM auth_tokens WHERE user_id=? AND purpose='reset' AND EXISTS(SELECT 1 FROM actors WHERE id=? AND password_hash=?)", user.id, user.id, encoded]
  ]);
  if (changed(results[0]) !== 1) fail(409, 'A conta foi alterada. Entre novamente.');
  await clearSession(c);
  return {ok: true, login_required: true};
}

async function preferences(c) {
  const user = await needUser(c), data = await json(c);
  fields(data, ['theme','accent','reduce_motion','dm_policy']);
  const theme = enumValue(data.theme, 'system', ['light','dark','system'], 'Tema');
  const accent = enumValue(data.accent, 'violet', ['violet','rose','mint','blue'], 'Cor');
  const dmPolicy = enumValue(data.dm_policy, 'following', ['everyone','following','off'], 'Preferência de mensagens');
  if (data.reduce_motion !== undefined && typeof data.reduce_motion !== 'boolean') fail(422, 'Preferência de movimento inválida.');
  if (['under_13','13_15','16_17'].includes(user.age_band) && dmPolicy !== 'off') fail(403, 'Mensagens diretas permanecem desativadas para contas de menores.');
  await run(c, 'UPDATE actors SET theme=?,accent=?,reduce_motion=?,dm_policy=? WHERE id=?', theme, accent, data.reduce_motion ? 1 : 0, dmPolicy, user.id);
  return {ok: true};
}

async function exportAccount(c) {
  const user = await needUser(c), id = user.id;
  await rate(c, 'export:' + id, 5, 3600);
  const result = {
    profile: publicActor(user), email: user.email, email_verified: Boolean(user.email_verified),
    preferences: {theme:user.theme,accent:user.accent,reduce_motion:user.reduce_motion,dm_policy:user.dm_policy},
    exported_at: now(),
    posts: await query(c, 'SELECT * FROM posts WHERE author_id=? OR approved_by=?', id, id),
    comments: await query(c, 'SELECT * FROM comments WHERE author_id=?', id),
    messages: await query(c, 'SELECT * FROM messages WHERE sender_id=? OR recipient_id=?', id, id),
    agents: (await query(c, 'SELECT * FROM actors WHERE owner_id=?', id)).map(publicActor)
  };
  for (const [table, field] of [
    ['drafts','owner_id'],['missions','owner_id'],['audit','owner_id'],['reports','reporter_id'],
    ['media_assets','owner_id'],['stories','author_id'],['notifications','user_id'],['content_reports','reporter_id'],
    ['follows','user_id'],['blocks','user_id'],['likes','user_id'],['bookmarks','user_id'],['usage','user_id'],
    ['web_links','owner_id'],['support_tickets','owner_id']
  ]) result[table] = await query(c, `SELECT * FROM ${table} WHERE ${field}=?`, id);
  result.account_safety = {account_private:user.account_private,age_band:user.age_band,age_verified_until:user.age_verified_until,age_provider:user.age_provider};
  result.guardianships = await query(c, 'SELECT * FROM guardianships WHERE child_id=? OR guardian_id=?', id, id);
  result.follow_requests = await query(c, 'SELECT * FROM follow_requests WHERE requester_id=? OR target_id=?', id, id);
  return new Response(JSON.stringify(result), {headers:{'Content-Type':'application/json; charset=utf-8','Content-Disposition':'attachment; filename="synapse-meus-dados.json"','Cache-Control':'private, no-store'}});
}

async function deleteAccount(c) {
  const user = await needUser(c), data = await json(c);
  fields(data, ['password']);
  await rate(c, 'delete-account:' + user.id, 5, 300);
  if (!await checkCredential(c, user, password(data.password, 1))) fail(401, 'Senha incorreta.');
  const remove = async () => {
  const paths = new Set([user.avatar_path, user.cover_path]);
  for (const item of await query(c, 'SELECT image_path FROM posts WHERE author_id=? UNION SELECT image_path FROM stories WHERE author_id=?', user.id, user.id)) paths.add(item.image_path);
  for (const item of await query(c, 'SELECT path,thumbnail FROM media_assets WHERE owner_id=?', user.id)) { paths.add(item.path); paths.add(item.thumbnail); }
  // The final-owner condition is part of DELETE itself, avoiding concurrent
  // deletions removing the last two responsible accounts simultaneously.
  const ownedPaths = [...paths].filter(value => typeof value === 'string' && /^\/media\/[a-f0-9]{32}\.[a-z0-9]+$/.test(value));
  const result = await batch(c, [
    [`DELETE FROM actors WHERE id=? AND password_hash=? AND (
      NOT EXISTS(SELECT 1 FROM operators o LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE o.user_id=? AND COALESCE(r.role,'owner')='owner')
      OR EXISTS(SELECT 1 FROM operators o JOIN actors a ON a.id=o.user_id LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE a.active=1 AND a.id!=? AND COALESCE(r.role,'owner')='owner'))`,
      user.id, user.password_hash, user.id, user.id],
    ['DELETE FROM search_usage WHERE user_id=? AND NOT EXISTS(SELECT 1 FROM actors WHERE id=?)', user.id, user.id],
    ...ownedPaths.map(path => ['INSERT OR IGNORE INTO media_cleanup(path,created_at) SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM actors WHERE id=?)',path,now(),user.id]),
    ...(isExternal(user.password_hash) ? [['INSERT OR IGNORE INTO credential_cleanup SELECT ?,? WHERE NOT EXISTS(SELECT 1 FROM actors WHERE id=?)',user.password_hash,stamp(),user.id]] : [])
  ]);
  if (changed(result[0]) !== 1) fail(409, 'A última conta responsável não pode ser excluída, ou a conta mudou. Transfira a responsabilidade ou encerre o serviço no console.');
  // DB deletion revokes read authorization immediately, even if an R2 delete
  // needs retry. A durable cleanup table retains every remaining object key.
  if (ownedPaths.length) {
    for (const path of ownedPaths) {
      try { await removeMedia(c, path); await run(c, 'DELETE FROM media_cleanup WHERE path=?', path); }
      catch { /* The scheduled cleanup retries; never expose the orphan. */ }
    }
  }
  if (isExternal(user.password_hash)) await processCredentialCleanup(c);
  await clearSession(c);
  return {ok: true};
  };
  return isExternal(user.password_hash) ? withCredentialLock(c, user, remove) : remove();
}

async function setup(c) {
  await rate(c, 'setup:' + network(c), 10, 600);
  const configured = String(c.env.SETUP_TOKEN || '');
  const supplied = c.request.headers.get('X-Setup-Token') || '';
  if (configured.length < 32 || !equal(supplied, configured)) fail(403, 'Código de configuração inválido.');
  if (await first(c, 'SELECT id FROM setup_locks WHERE id=1') || await first(c, 'SELECT user_id FROM operators LIMIT 1')) fail(409, 'A configuração inicial já foi concluída.');
  const data = await json(c);
  fields(data, ['name','handle','email','password','terms_accepted']);
  const name = text(data.name, 2, 50, 'Nome'), username = handle(data.handle), address = email(data.email);
  const encoded = await provisionCredential(c, address, password(data.password, 16));
  // Bootstrap creates the operator who will publish the policies. It is not a
  // fabricated acceptance of policies that may not exist yet.
  const id = uid(), created = now(), terms = '';
  let results;
  try {
    results = await batch(c, [
      ['INSERT INTO setup_locks(id,user_id,consumed_at) SELECT 1,?,? WHERE NOT EXISTS(SELECT 1 FROM operators)', id, created],
      [`INSERT INTO actors(id,handle,name,kind,bio,color,password_hash,created_at,email,terms_version,dm_policy,account_private)
        SELECT ?,?,?,'human','','violet',?,?,?,?,'following',1 WHERE EXISTS(SELECT 1 FROM setup_locks WHERE id=1 AND user_id=?)`,
        id, username, name, encoded, created, address, terms, id],
      ['INSERT INTO operators(user_id,created_at) SELECT ?,? WHERE EXISTS(SELECT 1 FROM actors WHERE id=?)', id, created, id],
      ["INSERT INTO operator_roles(user_id,role) SELECT ?,'owner' WHERE EXISTS(SELECT 1 FROM actors WHERE id=?)", id, id],
      ["INSERT INTO audit(id,owner_id,action,subject_id,summary,created_at) SELECT ?,?,'setup_completed',?,'Conta responsável criada pelo código privado de configuração.',? WHERE EXISTS(SELECT 1 FROM actors WHERE id=?)", uid(), id, id, created, id],
      ...finishProvision(c, encoded, id)
    ]);
  } catch (error) {
    if (isConstraint(error)) fail(409, 'Configuração já concluída ou usuário/e-mail indisponível.');
    throw error;
  }
  if (changed(results[1]) !== 1) fail(409, 'A configuração inicial já foi concluída.');
  const csrf = await setSession(c, id, encoded);
  await issueToken(c, {id,email:address}, 'verify');
  return {ok:true,csrf,verification_pending:true,next:'/admin',notice:'Confirme seu e-mail, configure o autenticador e remova SETUP_TOKEN da hospedagem. Os cadastros permanecem fechados.'};
}

export default function register(router) {
  router.on('POST', '/api/auth/register', signup);
  router.on('POST', '/api/auth/login', login);
  router.on('POST', '/api/auth/logout', async c => { await needUser(c); await clearSession(c); return {ok:true}; });
  router.on('POST', '/api/auth/forgot', async c => {
    const data = await json(c); fields(data, ['email']);
    const address = email(data.email);
    await rate(c, 'forgot:' + network(c), 4, 300);
    await rate(c, 'forgot-account:' + await sha256(address), 3, 900);
    const user = await first(c, 'SELECT id,email,email_verified,password_hash FROM actors WHERE email=? AND active=1 AND seeded=0', address);
    if (user) {
      try { await issueToken(c, user, isExternal(user.password_hash) && !user.email_verified ? 'verify' : 'reset'); }
      catch { console.error('password_reset_enqueue_failed'); }
    }
    return {ok:true,message:'Se o e-mail corresponder a uma conta, as instruções serão enviadas pelo canal configurado.'};
  });
  router.on('POST', '/api/auth/reset', resetPassword);
  router.on('POST', '/api/auth/verify', verifyEmail);
  router.on('POST', '/api/auth/resend-verification', async c => {
    const user = await needUser(c);
    await rate(c, 'resend:' + user.id, 2, 300);
    if (!user.email) fail(400, 'Conta sem e-mail. Procure o responsável para uma migração verificada.');
    if (!user.email_verified) await issueToken(c, user, 'verify');
    return {ok:true};
  });
  router.on('PATCH', '/api/account/password', changePassword);
  router.on('PATCH', '/api/preferences', preferences);
  router.on('GET', '/api/account/export', exportAccount);
  router.on('DELETE', '/api/account', deleteAccount);
  router.on('POST', '/api/setup', setup);
}
