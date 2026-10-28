import { fail, uid, now, stamp, token, sha256, equal, query, first, run, batch, json, text, email, needUser, requireSocial, development, termsVersion, socialStatus, rate, log, sendMail, decryptSecret } from './core.js';
import { requireAdmin, adminEvent } from './admin.js';

const encoder = new TextEncoder();
const messages = {
  login_required: 'Entre na sua conta.', email_required: 'Confirme seu e-mail antes de acessar os recursos sociais.',
  age_required: 'Conclua a aferição de faixa etária com o verificador contratado.',
  age_not_supported: 'O acesso social de menores está desativado nesta versão.',
  minors_not_enabled: 'O acesso social de menores está desativado nesta versão.',
  terms_required: 'Leia e aceite a versão atual dos Termos de uso.',
  ready: 'Conta habilitada para usar os recursos sociais.'
};
const minor = u => !!u && ['under_13', '13_15', '16_17'].includes(u.age_band);
const enforced = c => !(development(c) && c.env.AGE_ENFORCED === '0');
const origin = c => String(c.env.PUBLIC_ORIGIN || '').replace(/\/$/, '');
const changes = r => r?.meta?.changes ?? r?.changes ?? 0;
function unb64(v) {
  if (typeof v !== 'string' || !/^[A-Za-z0-9_-]+$/.test(v)) throw new Error('invalid_base64');
  return Uint8Array.from(atob(v.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - v.length % 4) % 4)), c => c.charCodeAt(0));
}
function httpsURL(v) { try { const u = new URL(v); return u.protocol === 'https:' && !u.username && !u.password && !u.hash && !!u.hostname; } catch { return false; } }
function validEmail(v) { try { return email(v) === v; } catch { return false; } }
export async function verifierReady(c) {
  if (!httpsURL(c.env.AGE_PROVIDER_URL) || !String(c.env.AGE_PROVIDER_ID || '').trim()) return false;
  try { const bytes = unb64(c.env.AGE_PUBLIC_KEY); if (bytes.length !== 32) return false; await crypto.subtle.importKey('raw', bytes, 'Ed25519', false, ['verify']); return true; } catch { return false; }
}
export async function integrationFingerprint(c, name) {
  const fields = name === 'turnstile' ? ['TURNSTILE_SITE_KEY', 'TURNSTILE_SECRET_KEY'] : name === 'age_verifier' ? ['AGE_PROVIDER_URL', 'AGE_PROVIDER_ID', 'AGE_PUBLIC_KEY'] : name === 'email_verification' || name === 'email_api' ? ['RESEND_API_KEY', 'MAIL_FROM'] : name === 'storage' ? ['MEDIA_BUCKET_NAME'] : [];
  return sha256(JSON.stringify(fields.map(k => c.env[k] || '')));
}
export async function recordIntegration(c, name, detail) {
  if (!['turnstile', 'age_verifier', 'email_verification', 'email_api', 'storage'].includes(name)) fail(422, 'Integração desconhecida.');
  await run(c, 'INSERT INTO integration_checks(name,origin,checked_at,detail,fingerprint) VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET origin=excluded.origin,checked_at=excluded.checked_at,detail=excluded.detail,fingerprint=excluded.fingerprint', name, origin(c), stamp(), detail, await integrationFingerprint(c, name));
}
export async function validateAgeReceipt(c, receipt, timestamp = stamp()) {
  const invalid = () => fail(400, 'Comprovante inválido, incompatível ou expirado. Reinicie a verificação.');
  try {
    if (typeof receipt !== 'string' || receipt.length < 80 || receipt.length > 4096) return invalid();
    const pieces = receipt.split('.'); if (pieces.length !== 2) return invalid();
    const [body, signature] = pieces;
    const keyBytes = unb64(c.env.AGE_PUBLIC_KEY); if (keyBytes.length !== 32) return invalid();
    const key = await crypto.subtle.importKey('raw', keyBytes, 'Ed25519', false, ['verify']);
    if (!await crypto.subtle.verify('Ed25519', key, unb64(signature), encoder.encode(body))) return invalid();
    const p = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(unb64(body)));
    if (!p || Array.isArray(p) || Object.keys(p).sort().join(',') !== 'aud,band,challenge,exp,iat,iss,v') return invalid();
    if (p.v !== 1 || p.iss !== c.env.AGE_PROVIDER_ID || p.aud !== origin(c)) return invalid();
    if (!['under_13', '13_15', '16_17', 'adult'].includes(p.band)) return invalid();
    if (typeof p.iat !== 'number' || typeof p.exp !== 'number' || !Number.isFinite(p.iat) || !Number.isFinite(p.exp)) return invalid();
    if (!(p.exp > timestamp && p.exp - p.iat > 0 && p.exp - p.iat <= 300 && p.iat >= timestamp - 300 && p.iat <= timestamp + 30)) return invalid();
    if (typeof p.challenge !== 'string' || !/^[A-Za-z0-9_-]{40,100}$/.test(p.challenge)) return invalid();
    return p;
  } catch { return invalid(); }
}

/** The checklist distinguishes configuration, integration evidence, and operator declarations. */
export async function launchReadiness(c) {
  const checks = [], add = (id, ok, kind, label, extra = {}) => checks.push({ id, ok: !!ok, kind, label, ...extra });
  let dbOK = false; try { await first(c, 'SELECT id FROM actors LIMIT 1'); dbOK = true; } catch { /* fail closed */ }
  if (c.env.AUTH_PROVIDER === 'supabase') {
    add('external_auth_configured', /^https:\/\/[a-z0-9]{20}\.supabase\.co\/?$/.test(c.env.SUPABASE_URL || '') && /^sb_publishable_/.test(c.env.SUPABASE_PUBLISHABLE_KEY || '') && /^sb_secret_/.test(c.env.SUPABASE_SECRET_KEY || ''), 'configuration', 'Supabase Auth e chave privada configurados no Worker');
  }
  add('production_mode', c.env.APP_ENV === 'production', 'configuration', 'Ambiente de produção');
  add('https_origin', httpsURL(origin(c)), 'configuration', 'Endereço público HTTPS configurado');
  add('database_connected', dbOK, 'integration', 'Banco D1 acessível');
  add('media_binding', !!c.env.MEDIA, 'configuration', 'Armazenamento R2 privado vinculado');
  let keyOK = false; try { keyOK = unb64(String(c.env.ADMIN_ENCRYPTION_KEY || '').replace(/=+$/, '')).length === 32; } catch { /* invalid */ }
  add('admin_encryption_key', keyOK, 'configuration', 'Chave de criptografia administrativa configurada');
  add('mail_configured', !!c.env.RESEND_API_KEY && !!c.env.MAIL_FROM, 'configuration', 'Provedor de e-mail Resend e remetente configurados');
  add('support_contact', validEmail(c.env.SUPPORT_EMAIL), 'configuration', 'Contato público de suporte');
  add('operator_identity', String(c.env.OPERATOR_NAME || '').trim().length >= 3, 'configuration', 'Identidade pública do responsável pela operação');
  add('bot_protection_configured', !!c.env.TURNSTILE_SITE_KEY && !!c.env.TURNSTILE_SECRET_KEY, 'configuration', 'Turnstile configurado');
  add('age_verifier_configured', await verifierReady(c), 'configuration', 'Emissor externo de faixa etária configurado');
  add('minor_access_disabled', c.env.MINOR_ACCOUNTS_ENABLED !== '1', 'configuration', 'Acesso social de menores desativado nesta versão');
  if (!dbOK) return { ready: false, checks };
  const [owner, seeded, policies, integrations, attestations, failed] = await Promise.all([
    first(c, "SELECT a.id FROM operators o JOIN actors a ON a.id=o.user_id JOIN operator_security sec ON sec.user_id=o.user_id LEFT JOIN operator_roles r ON r.user_id=o.user_id WHERE a.active=1 AND a.email_verified=1 AND sec.enabled=1 AND COALESCE(r.role,'owner')='owner' LIMIT 1"),
    first(c, 'SELECT COUNT(*) n FROM actors WHERE seeded=1'),
    query(c, 'SELECT p.kind,p.body,r.body_hash,r.release FROM site_policies p LEFT JOIN policy_reviews r ON r.kind=p.kind'),
    query(c, 'SELECT * FROM integration_checks WHERE origin=?', origin(c)),
    query(c, 'SELECT name,note,created_at FROM launch_attestations WHERE origin=?', origin(c)),
    first(c, "SELECT COUNT(*) n FROM mail_jobs WHERE status='failed' AND expires>?", stamp())
  ]);
  add('owner_mfa_verified', !!owner, 'configuration', 'Responsável ativo com e-mail confirmado e segundo fator');
  add('demo_records_removed', Number(seeded?.n) === 0, 'configuration', 'Perfis demonstrativos removidos');
  let policiesOK = true;
  for (const kind of ['terms', 'privacy', 'safety']) { const p = policies.find(p => p.kind === kind); if (!p || p.release !== '1.0' || !p.body.trim() || p.body_hash !== await sha256(p.body)) policiesOK = false; }
  add('public_policies', policiesOK, 'operator_review', 'Três políticas publicadas e revisadas para a versão 1.0');
  for (const [name, label] of [['turnstile', 'Turnstile validado no domínio configurado'], ['age_verifier', 'Comprovante etário assinado validado'], ['email_verification', 'Link real de confirmação de e-mail consumido'], ['storage', 'Escrita, leitura e remoção de teste no R2 concluídas']]) {
    const evidence = integrations.find(x => x.name === name);
    const ok = evidence && evidence.checked_at > stamp() - 30 * 86400 && equal(evidence.fingerprint, await integrationFingerprint(c, name));
    add(name + '_validated', ok, 'integration', label, { checked_at: evidence?.checked_at || null });
  }
  add('mail_queue_healthy', Number(failed?.n) === 0, 'integration', 'Sem mensagens válidas em falha definitiva');
  const labels = { audience_review: 'Público e obrigações de privacidade e idade avaliados pelo responsável', email_test: 'Recebimento e recuperação de senha testados pelo responsável', backup_restore: 'Exportação D1 e cópia R2 restauradas em ambiente separado', moderation: 'Atendimento e moderação definidos pelo responsável', browser_test: 'Fluxo completo testado no domínio HTTPS pelo responsável' };
  for (const [name, label] of Object.entries(labels)) { const a = attestations.find(a => a.name === name); add(name, !!a, 'operator_attestation', label, { record: a || null }); }
  return { ready: checks.every(x => x.ok), checks };
}

/** Atomic leases and a stable provider idempotency key prevent concurrent duplicate sends. */
export async function processMail(c, limit = 3) {
  const ts = stamp();
  await batch(c, [
    ["UPDATE mail_jobs SET status='expired',encrypted_message='',lease_until=0 WHERE status IN ('queued','sending','failed') AND expires<=?", ts],
    ["UPDATE mail_jobs SET status='queued',lease_until=0 WHERE status='sending' AND lease_until<=?", ts],
    ["UPDATE mail_jobs SET status='cancelled',encrypted_message='',lease_until=0 WHERE status IN ('queued','failed') AND (NOT EXISTS(SELECT 1 FROM actors WHERE id=mail_jobs.user_id AND active=1) OR (purpose IN ('verify','reset') AND NOT EXISTS(SELECT 1 FROM auth_tokens WHERE token_hash=mail_jobs.token_hash AND expires>?)))", ts]
  ]);
  if (!c.env.RESEND_API_KEY || !c.env.MAIL_FROM) return { sent: 0, configured: false };
  let sent = 0;
  for (let n = 0; n < Math.min(Math.max(limit, 1), 10); n++) {
    const t = stamp();
    const job = await first(c, "UPDATE mail_jobs SET status='sending',lease_until=?,attempts=attempts+1 WHERE id=(SELECT id FROM mail_jobs WHERE status='queued' AND next_attempt<=? AND expires>? ORDER BY created_at LIMIT 1) AND status='queued' RETURNING *", t + 90, t, t);
    if (!job) break;
    let code = 'mail_delivery_error', retry = true;
    try {
      // Never extend a retry beyond the provider's 24 hour idempotency window.
      if (Date.parse(job.created_at) / 1000 < t - 23 * 3600 && job.attempts > 1) { code = 'mail_retry_window_expired'; retry = false; throw new Error(code); }
      let payload;
      try { payload = JSON.parse(await decryptSecret(c, job.encrypted_message)); } catch { code = 'mail_key_error'; retry = false; throw new Error(code); }
      if (!payload || typeof payload.to !== 'string' || typeof payload.subject !== 'string' || typeof payload.text !== 'string') { code = 'mail_payload_error'; retry = false; throw new Error(code); }
      const response = await fetch('https://api.resend.com/emails', { method: 'POST', redirect: 'manual', signal: AbortSignal.timeout(12000), headers: { 'Authorization': 'Bearer ' + c.env.RESEND_API_KEY, 'Content-Type': 'application/json', 'Idempotency-Key': 'synapse-mail/' + job.id }, body: JSON.stringify({ from: payload.from || c.env.MAIL_FROM, to: [payload.to], subject: payload.subject, text: payload.text }) });
      if (!response.ok) { code = response.status === 429 ? 'mail_rate_limited' : response.status >= 500 ? 'mail_provider_unavailable' : 'mail_provider_rejected'; retry = response.status === 429 || response.status === 409 || response.status >= 500; throw new Error(code); }
      const result = await response.json(); if (typeof result.id !== 'string' || !result.id) throw new Error('mail_provider_invalid_response');
      await run(c, "UPDATE mail_jobs SET status='sent',encrypted_message='',error_code='',completed_at=?,lease_until=0 WHERE id=? AND status='sending'", now(), job.id);
      await recordIntegration(c, 'email_api', 'O provedor aceitou uma mensagem. Isso não comprova chegada à caixa de entrada.'); sent++;
    } catch {
      await run(c, 'UPDATE mail_jobs SET status=?,error_code=?,next_attempt=?,lease_until=0 WHERE id=? AND status=\'sending\'', retry && job.attempts < 6 ? 'queued' : 'failed', code, t + Math.min(30 * 2 ** job.attempts, 1800), job.id);
    }
  }
  return { sent, configured: true };
}

export default function register(router) {
  const on = (method, path, fn) => router.on(method, path, fn);
  on('GET', '/api/auth/options', async c => ({
    turnstile_site_key: c.env.TURNSTILE_SITE_KEY || '',
    turnstile_required: c.env.APP_ENV === 'production' || !!c.env.TURNSTILE_SECRET_KEY,
    age_required: enforced(c), age_verifier_ready: await verifierReady(c), minors_enabled: false,
    notice: 'Em produção, confirme seu e-mail e sua faixa etária antes de usar a rede. O acesso social de menores permanece desativado.'
  }));
  on('GET', '/api/account/security', async c => {
    const u = needUser(c), current = await termsVersion(c), state = await socialStatus(c);
    const incoming = await query(c, 'SELECT a.id,a.name,a.handle,r.created_at FROM follow_requests r JOIN actors a ON a.id=r.requester_id WHERE r.target_id=? AND a.active=1 AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=r.target_id AND b.target_id=r.requester_id) OR (b.user_id=r.requester_id AND b.target_id=r.target_id)) ORDER BY r.created_at DESC LIMIT 100', u.id);
    return { handle: u.handle, email_verified: !!u.email_verified, private: !!u.account_private, social_status: state, message: messages[state] || 'Revise os requisitos de ativação da conta.', age_band: u.age_band, age_verified_until: u.age_verified_until, age_required: enforced(c), verifier_ready: await verifierReady(c), minors_enabled: false, terms_current: current, terms_accepted: current === u.terms_version, follow_requests: incoming, guardian: null, children: [], is_minor: minor(u), csrf: u.csrf };
  });
  on('PATCH', '/api/account/privacy', async c => {
    const u = needUser(c), d = await json(c); if (typeof d.private !== 'boolean') fail(422, 'Informe a privacidade desejada.');
    if (!d.private) { await requireSocial(c); if (minor(u)) fail(403, 'O perfil deve permanecer privado.'); }
    await run(c, 'UPDATE actors SET account_private=? WHERE id=?', +d.private, u.id);
    await log(c, u.id, 'privacy_changed', u.id, d.private ? 'Perfil privado.' : 'Perfil visível aos membros habilitados.');
    return { ok: true, private: d.private };
  });
  on('POST', '/api/account/terms', async c => {
    const u = needUser(c), d = await json(c), version = await termsVersion(c);
    if (d.accepted !== true) fail(422, 'O aceite deve ser explícito.'); if (d.version !== version) fail(409, 'Os Termos mudaram. Atualize e leia a versão atual.');
    await run(c, 'UPDATE actors SET terms_version=? WHERE id=?', version, u.id); await log(c, u.id, 'terms_accepted', u.id, version); return { ok: true };
  });
  on('POST', '/api/account/follow-requests/:requester_id', async c => {
    const u = needUser(c); await requireSocial(c); const d = await json(c); if (typeof d.approve !== 'boolean') fail(422, 'Informe a decisão.');
    const r = await first(c, 'SELECT requester_id FROM follow_requests WHERE target_id=? AND requester_id=?', u.id, c.params.requester_id); if (!r) fail(404, 'Solicitação indisponível.');
    if (d.approve) {
      const out = await batch(c, [
        ['INSERT OR IGNORE INTO follows(user_id,target_id) SELECT r.requester_id,r.target_id FROM follow_requests r JOIN actors a ON a.id=r.requester_id WHERE r.requester_id=? AND r.target_id=? AND a.active=1 AND NOT EXISTS(SELECT 1 FROM blocks WHERE (user_id=r.requester_id AND target_id=r.target_id) OR (user_id=r.target_id AND target_id=r.requester_id))', c.params.requester_id, u.id],
        ['DELETE FROM follow_requests WHERE target_id=? AND requester_id=?', u.id, c.params.requester_id]
      ]); if (!changes(out[0])) fail(409, 'Não foi possível aprovar a solicitação; revise os bloqueios.');
    } else await run(c, 'DELETE FROM follow_requests WHERE target_id=? AND requester_id=?', u.id, c.params.requester_id);
    await log(c, u.id, 'follow_request_decided', c.params.requester_id, d.approve ? 'Aprovada.' : 'Recusada.'); return { ok: true };
  });
  on('DELETE', '/api/account/followers/:follower_id', async c => { const u = needUser(c); await batch(c, [['DELETE FROM follows WHERE user_id=? AND target_id=?', c.params.follower_id, u.id], ['DELETE FROM follow_requests WHERE requester_id=? AND target_id=?', c.params.follower_id, u.id]]); return { ok: true }; });
  on('GET', '/api/account/followers', async c => { const u = needUser(c); return { items: await query(c, 'SELECT a.id,a.handle,a.name FROM follows f JOIN actors a ON a.id=f.user_id WHERE f.target_id=? AND a.active=1 ORDER BY a.handle LIMIT 500', u.id) }; });
  on('GET', '/api/account/sessions', async c => {
    const u = needUser(c), missing = await query(c, 'SELECT token_hash FROM sessions WHERE user_id=? AND expires>? AND token_hash NOT IN (SELECT token_hash FROM session_devices) LIMIT 100', u.id, stamp());
    if (missing.length) await batch(c, missing.map(s => ['INSERT OR IGNORE INTO session_devices(id,token_hash,created_at,device) VALUES(?,?,?,?)', uid(), s.token_hash, now(), 'Sessão registrada após atualização']));
    const rows = await query(c, 'SELECT d.id,d.created_at,d.device,s.expires,s.token_hash FROM session_devices d JOIN sessions s ON s.token_hash=d.token_hash WHERE s.user_id=? AND s.expires>? ORDER BY d.created_at DESC LIMIT 100', u.id, stamp());
    return { items: rows.map(({ token_hash, ...r }) => ({ ...r, current: token_hash === c.sessionHash })) };
  });
  on('DELETE', '/api/account/sessions/:session_id', async c => {
    const u = needUser(c), row = await first(c, 'SELECT s.token_hash FROM session_devices d JOIN sessions s ON s.token_hash=d.token_hash WHERE d.id=? AND s.user_id=?', c.params.session_id, u.id);
    if (!row) fail(404, 'Sessão não encontrada.'); if (row.token_hash === c.sessionHash) fail(409, 'Use Sair para encerrar a sessão atual.'); await run(c, 'DELETE FROM sessions WHERE token_hash=?', row.token_hash); return { ok: true };
  });
  on('POST', '/api/account/sessions/revoke-others', async c => { const u = needUser(c); const r = await run(c, 'DELETE FROM sessions WHERE user_id=? AND token_hash!=?', u.id, c.sessionHash); return { ok: true, revoked: changes(r) }; });
  on('POST', '/api/account/age/start', async c => {
    const u = needUser(c); if (!u.email_verified) fail(403, 'Confirme primeiro seu e-mail.'); if (!await verifierReady(c)) fail(503, 'Verificador externo ainda não configurado. Não envie documentos pelo suporte.');
    await rate(c, 'age-start:' + u.id, 4, 600); const challenge = token(32);
    await batch(c, [['DELETE FROM age_challenges WHERE user_id=? OR expires<=?', u.id, stamp()], ['INSERT INTO age_challenges(challenge_hash,user_id,expires) VALUES(?,?,?)', await sha256(challenge), u.id, stamp() + 900]]);
    const url = new URL(c.env.AGE_PROVIDER_URL); url.searchParams.set('challenge', challenge); url.searchParams.set('audience', origin(c)); url.searchParams.set('return_url', origin(c) + '/conta/seguranca');
    return { url: url.href, notice: 'Você será direcionado ao verificador contratado. O Synapse recebe uma faixa etária assinada, não documentos.' };
  });
  on('POST', '/api/account/age/confirm', async c => {
    const u = needUser(c); if (!u.email_verified) fail(403, 'Confirme primeiro seu e-mail.'); await rate(c, 'age-confirm:' + u.id, 8, 600);
    if (!await verifierReady(c)) fail(503, 'Verificador não configurado.'); const d = await json(c), p = await validateAgeReceipt(c, d.receipt), hash = await sha256(p.challenge), until = stamp() + 30 * 86400;
    const result = await batch(c, [
      ['UPDATE actors SET age_band=?,age_verified_until=?,age_provider=? WHERE id=? AND EXISTS(SELECT 1 FROM age_challenges WHERE challenge_hash=? AND user_id=? AND expires>?)', p.band, until, c.env.AGE_PROVIDER_ID, u.id, hash, u.id, stamp()],
      ['DELETE FROM age_challenges WHERE challenge_hash=? AND user_id=? AND expires>?', hash, u.id, stamp()]
    ]);
    if (changes(result[0]) !== 1) fail(400, 'Verificação já utilizada ou pertencente a outra conta.');
    if (p.band !== 'adult') await batch(c, [
      ["UPDATE actors SET account_private=1,dm_policy='off' WHERE id=?", u.id],
      ['INSERT OR IGNORE INTO follow_requests SELECT user_id,target_id,? FROM follows WHERE target_id=?', now(), u.id],
      ['DELETE FROM follows WHERE target_id=?', u.id],
      ['DELETE FROM push_subscriptions WHERE user_id=?', u.id],
      ['DELETE FROM calls WHERE caller_id=? OR callee_id=?', u.id, u.id]
    ]);
    await log(c, u.id, 'age_band_verified', u.id, 'Faixa recebida de emissor configurado; sem documento armazenado.');
    await recordIntegration(c, 'age_verifier', 'Assinatura e desafio aceitos; a integração não certifica a confiabilidade do fornecedor.');
    return { ok: true, band: p.band, verified_until: until };
  });
  // No unverified parental relationship is advertised as an activation path.
  for (const [method, path] of [['POST', '/api/account/guardian/invite'], ['POST', '/api/account/guardian/accept'], ['PATCH', '/api/account/guardian/:child_id'], ['GET', '/api/account/guardian/:child_id/requests'], ['POST', '/api/account/guardian/:child_id/requests/:requester_id']]) on(method, path, async c => { needUser(c); fail(403, 'Supervisão e acesso social de menores não estão habilitados nesta versão.'); });
  on('DELETE', '/api/account/guardian', async c => { const u = needUser(c); await batch(c, [['DELETE FROM guardianships WHERE child_id=?', u.id], ['DELETE FROM guardian_invites WHERE child_id=?', u.id]]); return { ok: true, notice: 'Vínculo removido. O acesso social de menores permanece desativado.' }; });
  on('POST', '/api/account/support', async c => {
    const u = needUser(c), d = await json(c); await rate(c, 'support:' + u.id, 5, 3600); if (!['privacy', 'appeal', 'safety', 'bug'].includes(d.kind)) fail(422, 'Categoria inválida.');
    const id = uid(); await run(c, "INSERT INTO support_tickets(id,owner_id,kind,subject,body,status,reply,created_at,updated_at) VALUES(?,?,?,?,?,'open','',?,?)", id, u.id, d.kind, text(d.subject, 5, 120, 'Assunto'), text(d.body, 20, 3000, 'Descrição'), now(), now()); return { id, status: 'open' };
  });
  on('GET', '/api/account/support', async c => { const u = needUser(c); return { items: await query(c, 'SELECT id,kind,subject,body,status,reply,created_at,updated_at FROM support_tickets WHERE owner_id=? ORDER BY created_at DESC LIMIT 50', u.id) }; });

  on('GET', '/api/manage/support', async c => { await requireAdmin(c); return { items: await query(c, "SELECT t.*,a.handle FROM support_tickets t JOIN actors a ON a.id=t.owner_id ORDER BY (t.status='open') DESC,t.created_at DESC LIMIT 100") }; });
  on('POST', '/api/manage/support/:ticket_id', async c => {
    const u = await requireAdmin(c), d = await json(c); if (!['open', 'closed'].includes(d.status)) fail(422, 'Situação inválida.');
    const r = await run(c, 'UPDATE support_tickets SET reply=?,status=?,updated_at=? WHERE id=?', text(d.reply, 10, 3000, 'Resposta'), d.status, now(), c.params.ticket_id); if (!changes(r)) fail(404, 'Protocolo não encontrado.');
    await adminEvent(c, u, 'support_replied', 'ticket', c.params.ticket_id, 'Resposta registrada; ' + d.status); return { ok: true };
  });
  on('GET', '/api/manage/operations', async c => {
    await requireAdmin(c, true);
    const [mail, failures, tickets, backups] = await Promise.all([
      query(c, 'SELECT status,COUNT(*) n FROM mail_jobs GROUP BY status'),
      query(c, "SELECT id,purpose,status,attempts,error_code,created_at FROM mail_jobs WHERE status IN ('failed','queued') ORDER BY created_at DESC LIMIT 30"),
      first(c, "SELECT COUNT(*) n FROM support_tickets WHERE status='open'"),
      query(c, 'SELECT id,status,sha256,bytes,error_code,created_at,completed_at FROM backup_jobs ORDER BY created_at DESC LIMIT 15')
    ]);
    return { mail: Object.fromEntries(mail.map(r => [r.status, r.n])), mail_jobs: failures, backups, database_ok: true, disk_free_bytes: null, metrics_since_restart: null, open_tickets: tickets.n, backup_encrypted: false, backup_offsite_configured: false, auto_backup_enabled: false, single_instance: false, backup_mode: 'd1-time-travel-and-export', backup_verified: false, notice: 'D1 e R2 são serviços gerenciados. Envio aceito pela API não confirma entrega na caixa. O painel não afirma que exportações ou restaurações foram executadas; confira o procedimento no guia de hospedagem.' };
  });
  on('POST', '/api/manage/mail/:job_id/retry', async c => {
    const u = await requireAdmin(c, true), row = await first(c, 'SELECT * FROM mail_jobs WHERE id=?', c.params.job_id);
    if (!row || row.status !== 'failed' || row.expires <= stamp() || Date.parse(row.created_at) / 1000 < stamp() - 23 * 3600 || !row.encrypted_message) fail(409, 'Mensagem não pode ser reenviada. Solicite um novo link.');
    await run(c, "UPDATE mail_jobs SET status='queued',attempts=0,next_attempt=?,lease_until=0 WHERE id=? AND status='failed'", stamp(), row.id); await adminEvent(c, u, 'mail_retry', 'mail', row.id, 'Reenvio solicitado sem exibir destinatário ou conteúdo.'); return { ok: true };
  });
  on('POST', '/api/manage/mail/test', async c => {
    const u = await requireAdmin(c, true); await rate(c, 'mail-test:' + u.id, 2, 300);
    const id = await sendMail(c, u.email, 'Synapse — teste de entrega', 'Mensagem de teste solicitada no painel. Recebê-la não testa recuperação de senha nem SPF, DKIM ou DMARC. Não responda com senhas.', { userId: u.id, purpose: 'test', expires: stamp() + 3600 });
    if (c.ctx?.waitUntil) c.ctx.waitUntil(processMail(c)); return { ok: true, job_id: id, mode: 'resend' };
  });
  on('POST', '/api/manage/backups', async c => { await requireAdmin(c, true); fail(409, 'Nesta versão Cloudflare, use D1 Time Travel e exporte D1 e R2 pelo procedimento do guia. Nenhum backup foi criado por esta ação.'); });
  on('GET', '/api/manage/backups', async c => { await requireAdmin(c, true); return { mode: 'd1-time-travel-and-export', verified: false, notice: 'Use o procedimento de exportação e restauração do guia; Time Travel cobre o banco, não as mídias R2.' }; });
  on('POST', '/api/manage/integrations/storage', async c => {
    const u = await requireAdmin(c, true); await rate(c, 'storage-test:' + u.id, 3, 300); if (!c.env.MEDIA) fail(503, 'R2 não vinculado.');
    const key = '_diagnostics/' + uid(), value = token(32); let passed = false;
    try { await c.env.MEDIA.put(key, value, { httpMetadata: { contentType: 'text/plain' } }); const object = await c.env.MEDIA.get(key); passed = !!object && equal(await object.text(), value); } catch { fail(503, 'A verificação de armazenamento falhou.'); } finally { await c.env.MEDIA.delete(key); }
    if (!passed) fail(503, 'A leitura do armazenamento não corresponde à escrita.');
    await recordIntegration(c, 'storage', 'Escrita, leitura e remoção de objeto de diagnóstico concluídas.'); return { ok: true };
  });
  on('GET', '/api/manage/integrations', async c => { await requireAdmin(c, true); return { items: await query(c, 'SELECT name,origin,checked_at,detail FROM integration_checks WHERE origin=?', origin(c)) }; });
  on('GET', '/.well-known/security.txt', async c => {
    const address = c.env.SECURITY_EMAIL || c.env.SUPPORT_EMAIL; if (!validEmail(address)) fail(404, 'Contato indisponível.');
    return new Response(`Contact: mailto:${address}\nExpires: ${new Date(Date.now() + 30 * 86400000).toISOString()}\nPreferred-Languages: pt-BR, en\n`, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  });
}
