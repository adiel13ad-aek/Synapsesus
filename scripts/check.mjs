import { readFile, readdir, access } from 'node:fs/promises';
import { resolve, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const errors = [];
const production = process.argv.includes('--production');
const check = (condition, error) => { if (!condition) errors.push(error); };
const config = JSON.parse(await readFile(resolve(root,'wrangler.jsonc'),'utf8'));
check(config.main === 'src/index.js', 'main deve apontar para src/index.js.');
check(config.assets?.directory === './web', 'Somente web/ pode ser publicada como arquivos estáticos.');
check(config.assets?.run_worker_first === true, 'Autorização do Worker deve executar antes dos arquivos estáticos.');
check(config.vars?.APP_ENV === 'production', 'wrangler.jsonc deve usar APP_ENV=production.');
check(config.vars?.AGE_ENFORCED === '1', 'Produção exige aferição etária.');
check(config.vars?.MINOR_ACCOUNTS_ENABLED === '0', 'Contas de menores ainda não são habilitadas nesta migração.');
check(config.d1_databases?.[0]?.binding === 'DB', 'Binding D1 DB ausente.');
check(config.r2_buckets?.[0]?.binding === 'MEDIA', 'Binding R2 MEDIA ausente.');
check(config.preview_urls === false, 'Desative URLs de prévia que poderiam apontar aos dados de produção.');
const secretNames = ['SETUP_TOKEN','ADMIN_ENCRYPTION_KEY','RESEND_API_KEY','TURNSTILE_SECRET_KEY','CLOUDFLARE_API_TOKEN'];
for (const key of secretNames) check(!(key in (config.vars || {})), `${key} deve ser um secret, não uma variável no repositório.`);
async function walk(dir) {
  const items = [];
  for (const ent of await readdir(dir,{withFileTypes:true})) {
    const path = resolve(dir,ent.name);
    if(ent.isSymbolicLink()) { errors.push(`Link simbólico não permitido: ${relative(root,path)}`); continue; }
    if(ent.isDirectory()) items.push(...await walk(path)); else items.push(path);
  }
  return items;
}
for (const dir of ['src','scripts']) {
  for (const file of await walk(resolve(root,dir))) {
    if (!/\.(mjs|js)$/.test(file)) continue;
    const result = spawnSync(process.execPath,['--check',file],{encoding:'utf8'});
    check(result.status === 0, `Sintaxe inválida: ${relative(root,file)}\n${result.stderr || ''}`);
  }
}
for (const file of await walk(resolve(root,'web'))) {
  check(!/(^|[/\\])(\.env|\.dev\.vars|data|backups|\.git)([/\\]|$)|\.(db|sqlite|pem|key)$/i.test(file), `Arquivo privado dentro de web/: ${relative(root,file)}`);
  if(/\.(js|html|css)$/.test(file)) {
    const contents=await readFile(file,'utf8');
    check(!/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/.test(contents),`Chave privada em ${relative(root,file)}`);
  }
}
for (const path of ['src/index.js','src/core.js','migrations/0001_initial.sql','package-lock.json']) {
  try { await access(resolve(root,path)); } catch { errors.push(`Arquivo necessário ausente: ${path}`); }
}
if(production) {
  const id=config.d1_databases?.[0]?.database_id || '';
  check(/^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(id) && !/^0{8}-/.test(id),'Configure o UUID real do D1 com scripts/setup.mjs.');
  try {
    const url=new URL(config.vars.PUBLIC_ORIGIN);
    check(url.protocol === 'https:' && url.pathname === '/' && !url.search && !url.hash && !url.username && !url.password && !url.hostname.endsWith('.invalid') && !['localhost','127.0.0.1','[::1]'].includes(url.hostname),'PUBLIC_ORIGIN deve ser a origem HTTPS pública real, sem caminho.');
  } catch { errors.push('PUBLIC_ORIGIN inválida.'); }
}
if(errors.length) {
  console.error(errors.map(e=>'ERRO: '+e).join('\n'));
  process.exitCode=1;
} else console.log(`Configuração e sintaxe verificadas${production ? ' para implantação' : ''}. Isso não executa teste público nem valida secrets remotos.`);
