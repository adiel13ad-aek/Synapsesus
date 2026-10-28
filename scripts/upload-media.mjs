#!/usr/bin/env node
// Explicit user-run uploader. Without --upload it validates only; no network write.
import { readFile, realpath, lstat } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
const argv=process.argv.slice(2);
const option=(name)=>{const at=argv.indexOf(name);return at<0 ? null : argv[at+1];};
const dir=await realpath(option('--directory') || 'migration-output');
const bucket=option('--bucket');
if(!bucket || !/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(bucket)) throw new Error('Informe --bucket NOME-DO-BUCKET-PRIVADO.');
const manifest=JSON.parse(await readFile(resolve(dir,'manifest.json'),'utf8'));
if(manifest.format!=='synapse-cloudflare-migration-v1' || !Array.isArray(manifest.media)) throw new Error('Manifesto inválido.');
const checked=[];
for(const item of manifest.media) {
  if(!/^[a-f0-9]{32}\.(jpg|jpeg|png|webp|mp4)$/.test(item.key)) throw new Error('Chave de mídia inválida.');
  const source=resolve(dir,item.file);
  if(!source.startsWith(dir+sep) || (await lstat(source)).isSymbolicLink()) throw new Error('Caminho de mídia inseguro.');
  const path=await realpath(source);
  if(!path.startsWith(dir+sep)) throw new Error('Mídia fora da pasta de migração.');
  const bytes=await readFile(path);
  if(bytes.length!==item.bytes || createHash('sha256').update(bytes).digest('hex')!==item.sha256) throw new Error('Mídia alterada ou incompleta.');
  checked.push({...item,path});
}
console.log(`${checked.length} mídias conferidas; destino R2: ${bucket}.`);
if(!argv.includes('--upload')) {
  console.log('Somente validação. Adicione --upload para enviar os arquivos ao bucket privado.');
} else {
  for(let index=0;index<checked.length;index++) {
    const item=checked[index];
    const result=spawnSync(process.execPath,['node_modules/wrangler/bin/wrangler.js','r2','object','put',bucket+'/'+item.key,
      '--remote','--file',item.path,'--content-type',item.content_type,'--cache-control','private, no-store'],{stdio:'inherit'});
    if(result.status!==0) throw new Error(`Envio interrompido na mídia ${index+1}/${checked.length}; corrija e execute novamente. Objetos existentes com as mesmas chaves serão substituídos pelos mesmos bytes verificados.`);
    console.log(`Enviadas ${index+1}/${checked.length}.`);
  }
}
