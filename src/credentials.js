import {fail, hashPassword, passwordOK, uid} from './core.js';

// Supabase owns password hashing. D1 stores only an immutable provider identity
// and a random revision used by the application's compare-and-swap updates.
const markerPattern = /^supabase\$([a-z0-9]{20})\$([a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12})\$([a-f0-9]{32})$/;
const unavailable = () => fail(503, 'A autenticação não respondeu. Tente novamente em instantes.');
export const isExternal = stored => typeof stored === 'string' && stored.startsWith('supabase$');
export function usingSupabase(c) {
  const mode = c.env.AUTH_PROVIDER || 'local';
  if (!['local', 'supabase'].includes(mode)) fail(503, 'Provedor de autenticação inválido.');
  return mode === 'supabase';
}
function config(c) {
  const match = /^https:\/\/([a-z0-9]{20})\.supabase\.co\/?$/.exec(String(c.env.SUPABASE_URL || ''));
  if (!match) fail(503, 'Configure SUPABASE_URL com o endereço HTTPS do projeto.');
  const publishable = String(c.env.SUPABASE_PUBLISHABLE_KEY || '');
  const secret = String(c.env.SUPABASE_SECRET_KEY || '');
  if (!/^sb_publishable_[A-Za-z0-9_-]{16,256}$/.test(publishable)) fail(503, 'Configure SUPABASE_PUBLISHABLE_KEY.');
  if (!/^sb_secret_[A-Za-z0-9_-]{16,256}$/.test(secret)) fail(503, 'Configure SUPABASE_SECRET_KEY como segredo privado do Worker.');
  return {ref:match[1], origin:`https://${match[1]}.supabase.co`, publishable, secret};
}
function identity(c, stored) {
  const match = markerPattern.exec(stored || '');
  const cfg = config(c);
  if (!match || match[1] !== cfg.ref) fail(503, 'A conta não pertence ao projeto de autenticação configurado.');
  return {...cfg, id:match[2]};
}
function marker(ref, id) { return `supabase$${ref}$${id}$${uid()}`; }
export function newExternalCredential(c) {
  const cfg = config(c);
  return marker(cfg.ref, crypto.randomUUID());
}
function newPassword(value) {
  if (typeof value !== 'string' || value.length < 10 || value.length > 128) fail(422, 'A senha deve ter de 10 a 128 caracteres.');
  // Supabase's bcrypt has a byte limit; never silently truncate a password.
  if (new TextEncoder().encode(value).length > 72) fail(422, 'Use uma senha de até 72 bytes; letras acentuadas e emojis ocupam mais de um byte.');
  return value;
}
async function request(cfg, path, {method='POST', body, admin=true, bearer}={}) {
  let response, data;
  try {
    const headers = {'Content-Type':'application/json', apikey:admin ? cfg.secret : cfg.publishable};
    if (bearer) headers.Authorization = `Bearer ${bearer}`;
    response = await fetch(cfg.origin + '/auth/v1' + path, {
      method, headers, ...(body === undefined ? {} : {body:JSON.stringify(body)}),
      redirect:'manual', signal:AbortSignal.timeout(10000)
    });
    const raw = await response.text();
    if (raw.length > 65536) return unavailable();
    data = raw ? JSON.parse(raw) : {};
    if (!data || typeof data !== 'object' || Array.isArray(data)) return unavailable();
  } catch { return unavailable(); }
  // Never propagate provider bodies: they can contain credentials, email or JWTs.
  return {ok:response.ok, status:response.status, data, code:data.error_code || data.code || ''};
}
function matches(data, id, address) {
  return data?.id === id && typeof data.email === 'string' && data.email.toLowerCase() === address.toLowerCase();
}
function mutationFailure(result) {
  if (result.status === 422 && ['weak_password','validation_failed'].includes(result.code)) fail(422, 'A senha não atende à política do provedor de autenticação.');
  if (['email_exists','user_already_exists'].includes(result.code)) fail(409, 'Este e-mail já está cadastrado no provedor. Nenhuma conta foi vinculada automaticamente.');
  return unavailable();
}
export async function createCredential(c, address, password, preparedMarker) {
  if (!usingSupabase(c)) return hashPassword(password);
  const stored = preparedMarker || newExternalCredential(c);
  const cfg = identity(c, stored);
  const result = await request(cfg, '/admin/users', {body:{id:cfg.id, email:address, password:newPassword(password), email_confirm:false}});
  if (!result.ok) return mutationFailure(result);
  if (!matches(result.data, cfg.id, address) || result.data.email_confirmed_at) return unavailable();
  return stored;
}
export async function confirmCredential(c, user) {
  if (!isExternal(user?.password_hash)) return;
  if (!user.email_verified) fail(403, 'Confirme seu e-mail antes de continuar.');
  const cfg = identity(c, user.password_hash);
  // Fetch before changing confirmation, so an externally changed email is never
  // marked verified using proof collected for the old local email address.
  const current = await request(cfg, '/admin/users/' + cfg.id, {method:'GET'});
  if (!current.ok || !matches(current.data, cfg.id, user.email)) return unavailable();
  if (current.data.email_confirmed_at) return;
  const result = await request(cfg, '/admin/users/' + cfg.id, {method:'PUT', body:{email:user.email, email_confirm:true}});
  if (!result.ok || !matches(result.data, cfg.id, user.email) || !result.data.email_confirmed_at) return unavailable();
}
export async function checkCredential(c, user, password) {
  const externalMode = usingSupabase(c);
  if (!externalMode && !isExternal(user?.password_hash)) return passwordOK(password, user?.password_hash || null);
  if (!user || typeof password !== 'string' || password.length < 1 || password.length > 128) return false;
  if (!isExternal(user.password_hash)) fail(503, 'Esta conta antiga precisa migrar a senha. Use a recuperação por e-mail.');
  if (!externalMode) fail(503, 'Reative o provedor Supabase para acessar esta conta.');
  if (new TextEncoder().encode(password).length > 72) return false;
  const cfg = identity(c, user.password_hash);
  const grant = () => request(cfg, '/token?grant_type=password', {admin:false, body:{email:user.email,password}});
  let result = await grant();
  if (!result.ok && result.code === 'email_not_confirmed' && user.email_verified) {
    await confirmCredential(c, user);
    result = await grant();
  }
  if (!result.ok) {
    if (['invalid_credentials','email_not_confirmed','user_banned'].includes(result.code)) return false;
    return unavailable();
  }
  const remote = result.data.user;
  return matches(remote, cfg.id, user.email) && !!remote.email_confirmed_at && typeof result.data.access_token === 'string' && result.data.access_token.length > 0;
}
export async function replaceCredential(c, user, password) {
  if (!usingSupabase(c) && !isExternal(user?.password_hash)) return hashPassword(password);
  if (!isExternal(user?.password_hash)) fail(503, 'Migração da conta necessária antes de trocar a senha.');
  const cfg = identity(c, user.password_hash);
  const current = await request(cfg, '/admin/users/' + cfg.id, {method:'GET'});
  if (!current.ok || !matches(current.data, cfg.id, user.email)) return unavailable();
  const result = await request(cfg, '/admin/users/' + cfg.id, {method:'PUT', body:{password:newPassword(password)}});
  if (!result.ok) return mutationFailure(result);
  if (!matches(result.data, cfg.id, user.email)) return unavailable();
  return marker(cfg.ref, cfg.id);
}
export async function deleteExternal(c, stored) {
  if (!isExternal(stored)) return;
  const cfg = identity(c, stored);
  const result = await request(cfg, '/admin/users/' + cfg.id, {method:'DELETE', body:{should_soft_delete:false}});
  if (!result.ok && result.status !== 404) return unavailable();
}
