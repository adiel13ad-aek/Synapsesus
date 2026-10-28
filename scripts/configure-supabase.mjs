import {readFileSync, writeFileSync, renameSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';

export const supabaseSettings = Object.freeze({
  AUTH_PROVIDER: 'supabase',
  SUPABASE_URL: 'https://fjsdjlqktrkyuxbenzup.supabase.co',
  SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_xMiWXSwmKl16CeGTadY8iQ_wAqbl7zx'
});

// This changes the existing deployment configuration. Never replace a user's
// resource IDs with the placeholders in a release archive.
export function mergeSupabaseConfig(config) {
  if (!config || Array.isArray(config) || typeof config !== 'object') {
    throw new Error('A configuração precisa ser um objeto JSON.');
  }
  if (config.vars !== undefined && (!config.vars || Array.isArray(config.vars) || typeof config.vars !== 'object')) {
    throw new Error('O campo vars precisa ser um objeto JSON.');
  }
  const result = structuredClone(config);
  result.vars = {...result.vars, ...supabaseSettings};
  if (result.name === 'synapse-discovery') result.name = 'synapsesus';
  if (!result.vars.PUBLIC_ORIGIN || result.vars.PUBLIC_ORIGIN === 'https://configure.invalid') {
    result.vars.PUBLIC_ORIGIN = 'https://synapsesus.adielrodriguesdemorais793.workers.dev';
  }
  // The Free plan rejects configurable CPU limits. Preserve every other limit.
  if (result.limits && typeof result.limits === 'object' && !Array.isArray(result.limits)) {
    delete result.limits.cpu_ms;
    if (Object.keys(result.limits).length === 0) delete result.limits;
  }
  return result;
}

export function configureSupabase(path = 'wrangler.jsonc') {
  const target = resolve(path);
  const source = readFileSync(target, 'utf8');
  let config;
  try { config = JSON.parse(source.replace(/^\uFEFF/, '')); }
  catch {
    throw new Error('Não alterei o arquivo: esta ferramenta aceita JSON sem comentários nem vírgulas finais. Faça esses ajustes no wrangler.jsonc ou adicione manualmente as três variáveis de docs/SUPABASE.md.');
  }
  const next = JSON.stringify(mergeSupabaseConfig(config), null, 2) + '\n';
  if (next === source) return {changed:false, target};
  const suffix = randomUUID();
  const backup = target + '.before-supabase-' + suffix + '.bak';
  const temporary = target + '.supabase-' + suffix + '.tmp';
  writeFileSync(backup, source, {flag:'wx', mode:0o600});
  writeFileSync(temporary, next, {flag:'wx', mode:0o600});
  renameSync(temporary, target);
  return {changed:true, target, backup};
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    if (process.argv.length > 3) throw new Error('Uso: node scripts/configure-supabase.mjs [caminho-do-wrangler.jsonc]');
    const result = configureSupabase(process.argv[2]);
    console.log(result.changed ? 'Configuração Supabase adicionada ao arquivo existente.' : 'Configuração Supabase já aplicada.');
    if (result.backup) console.log('Cópia anterior: ' + result.backup);
    console.log('D1, R2 e demais variáveis foram preservados. Nenhum recurso remoto foi alterado.');
    console.log('Agora configure SUPABASE_SECRET_KEY como secret no Worker. Consulte docs/SUPABASE.md.');
  } catch (error) {
    console.error('ERRO: ' + error.message);
    process.exitCode = 1;
  }
}
