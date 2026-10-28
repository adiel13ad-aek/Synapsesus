import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import jpeg from 'jpeg-js';
import pngjs from 'pngjs';
import {persistImage,removeMedia} from '../src/core.js';

// Real SQLite schema and real image decoders; the R2 transport is an in-memory
// substitute with controllable network failures, not an external-service test.
function fixture() {
  const db=new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../migrations/0001_initial.sql',import.meta.url),'utf8'));
  for(const id of ['alice','bob'])db.prepare("INSERT INTO actors(id,handle,name,kind,created_at) VALUES(?,?,?,'human',?)").run(id,id,id,new Date().toISOString());
  const objects=new Map();let putCalls=0,deleteCalls=0,putFailure='',deleteFailure=false;
  const DB={prepare(sql){return {bind(...args){return {
    async all(){return {results:db.prepare(sql).all(...args)};},
    async first(){return db.prepare(sql).get(...args)||null;},
    async run(){const r=db.prepare(sql).run(...args);return {success:true,meta:{changes:Number(r.changes)}};},
  };}};},async batch(statements){db.exec('BEGIN IMMEDIATE');try{const values=[];for(const s of statements)values.push(await s.run());db.exec('COMMIT');return values;}catch(e){db.exec('ROLLBACK');throw e;}}};
  const MEDIA={async put(key,value,metadata){putCalls++;if(putFailure==='before')throw Error('R2 unavailable before write');objects.set(key,{bytes:Buffer.from(value),metadata});if(putFailure==='after')throw Error('Network response lost after write');},async delete(key){deleteCalls++;if(deleteFailure)throw Error('R2 delete temporarily unavailable');objects.delete(key);}};
  const c={env:{DB,MEDIA,APP_ENV:'development'},url:new URL('http://localhost'),user:{id:'alice'}};
  return {c,db,objects,close:()=>db.close(),putCalls:()=>putCalls,deleteCalls:()=>deleteCalls,setPutFailure:x=>putFailure=x,setDeleteFailure:x=>deleteFailure=x,count:()=>db.prepare('SELECT COUNT(*) n FROM media_assets').get().n,queued:()=>db.prepare('SELECT COUNT(*) n FROM media_cleanup').get().n};
}
const pixels=Buffer.from([255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255]);
const jpg=(extra={})=>jpeg.encode({width:2,height:2,data:pixels,...extra},90).data;
const png=()=>pngjs.PNG.sync.write({width:2,height:2,data:pixels},{colorType:6,bitDepth:8});
const uri=(bytes,kind='jpeg')=>`data:image/${kind};base64,${Buffer.from(bytes).toString('base64')}`;
const status=(promise,expected)=>assert.rejects(promise,e=>e.status===expected);

test('JPEG upload decodes/re-encodes pixels and removes EXIF and comment metadata',async t=>{
  const f=fixture();t.after(f.close);
  const secret='PRIVATE-GPS-LOCATION-DO-NOT-PUBLISH';
  const input=jpg({exifBuffer:Buffer.from('Exif\0\0'+secret),comments:[secret]});
  assert.ok(input.includes(Buffer.from(secret)),'fixture contains the privacy-sensitive metadata');
  const path=await persistImage(f.c,uri(input),'alice');
  assert.match(path,/^\/media\/[a-f0-9]{32}\.jpg$/);
  const saved=f.objects.get(path.slice(7)),decoded=jpeg.decode(saved.bytes);
  assert.equal(decoded.width,2);assert.equal(decoded.height,2);
  assert.equal(saved.bytes.includes(Buffer.from(secret)),false);
  assert.equal(decoded.exifBuffer,undefined);assert.equal(decoded.comments,undefined);
  assert.equal(saved.metadata.httpMetadata.contentType,'image/jpeg');
  assert.equal(saved.metadata.customMetadata.ownerId,'alice');
  const row=f.db.prepare('SELECT * FROM media_assets WHERE path=?').get(path);
  assert.equal(row.owner_id,'alice');assert.equal(row.post_id,null);assert.equal(row.bytes,saved.bytes.length);
});

test('PNG upload becomes a bounded JPEG and composites transparent pixels',async t=>{
  const f=fixture();t.after(f.close);
  const rgba=Buffer.alloc(16); // Fully transparent pixels should become white.
  const input=pngjs.PNG.sync.write({width:2,height:2,data:rgba});
  const path=await persistImage(f.c,uri(input,'png'),'alice');
  const output=f.objects.get(path.slice(7)).bytes,image=jpeg.decode(output);
  assert.equal(output[0],0xff);assert.equal(output[1],0xd8);
  assert.ok(image.data[0]>245&&image.data[1]>245&&image.data[2]>245);
});

test('malformed, repeated, interlaced and oversized PNG headers are rejected before decoding or storage',async t=>{
  const f=fixture();t.after(f.close);const original=png(),bad=[];
  bad.push(Buffer.concat([original.subarray(0,33),original.subarray(8,33),original.subarray(33)]));
  const interlaced=Buffer.from(original);interlaced[28]=1;bad.push(interlaced);
  const oversized=Buffer.from(original);oversized.writeUInt32BE(100000,16);bad.push(oversized);
  const highDepth=Buffer.from(original);highDepth[24]=16;bad.push(highDepth);
  const hugeChunk=Buffer.from(original);hugeChunk.writeUInt32BE(0xffffffff,33);bad.push(hugeChunk);
  bad.push(Buffer.concat([original,Buffer.from('trailing data')]));
  const read=pngjs.PNG.sync.read;let decoded=0;pngjs.PNG.sync.read=(...a)=>{decoded++;return read(...a);};
  try{for(const input of bad)await status(persistImage(f.c,uri(input,'png'),'alice'),422);}finally{pngjs.PNG.sync.read=read;}
  assert.equal(decoded,0);assert.equal(f.putCalls(),0);assert.equal(f.count(),0);
});

test('invalid formats, corrupt bytes and oversize input never reach R2',async t=>{
  const f=fixture();t.after(f.close);
  await status(persistImage(f.c,'data:image/svg+xml;base64,'+Buffer.from('<svg/>').toString('base64'),'alice'),422);
  await status(persistImage(f.c,uri(Buffer.from('not an image')),'alice'),422);
  await status(persistImage(f.c,uri(png()),'alice'),422); // PNG bytes labelled as JPEG.
  await status(persistImage(f.c,uri(Buffer.alloc(3*1024*1024+1)),'alice'),413);
  f.db.exec('UPDATE site_settings SET uploads_enabled=0');
  await status(persistImage(f.c,uri(jpg()),'alice'),503);
  assert.equal(f.putCalls(),0);assert.equal(f.count(),0);
});

test('per-user media quota reserves atomically across concurrent uploads',async t=>{
  const f=fixture();t.after(f.close);const input=uri(jpg());
  const path=await persistImage(f.c,input,'alice'),size=f.objects.get(path.slice(7)).bytes.length;
  await removeMedia(f.c,path);f.c.env.USER_MEDIA_LIMIT_BYTES=String(size);
  const values=await Promise.allSettled([persistImage(f.c,input,'alice'),persistImage(f.c,input,'alice')]);
  assert.equal(values.filter(r=>r.status==='fulfilled').length,1);
  assert.equal(values.find(r=>r.status==='rejected').reason.status,413);
  assert.equal(f.count(),1);assert.equal(f.objects.size,1);
  await persistImage(f.c,input,'bob'); // A different owner has an independent quota.
  assert.equal(f.count(),2);
});

test('site-wide quota rejects a different user before R2 allocation',async t=>{
  const f=fixture();t.after(f.close);const input=uri(jpg()),path=await persistImage(f.c,input,'alice');
  f.c.env.SITE_MEDIA_LIMIT_BYTES=String(f.objects.get(path.slice(7)).bytes.length);
  const calls=f.putCalls();await status(persistImage(f.c,input,'bob'),413);
  assert.equal(f.count(),1);assert.equal(f.putCalls(),calls);assert.equal(f.objects.size,1);
});

test('R2 upload failure compensates the reserved database row',async t=>{
  const f=fixture();t.after(f.close);f.setPutFailure('before');
  await assert.rejects(persistImage(f.c,uri(jpg()),'alice'),/R2 unavailable/);
  assert.equal(f.count(),0);assert.equal(f.objects.size,0);
});

test('an ambiguous R2 upload failure removes or queues the possibly written object',async t=>{
  const f=fixture();t.after(f.close);f.setPutFailure('after');f.setDeleteFailure(true);
  await assert.rejects(persistImage(f.c,uri(jpg()),'alice'));
  assert.ok(f.objects.size===0||f.queued()===1,'An object written before a lost response must remain tracked for cleanup');
  if(f.objects.size){
    const row=f.db.prepare('SELECT path FROM media_cleanup').get();f.setDeleteFailure(false);
    await removeMedia(f.c,row.path);
  }
  assert.equal(f.objects.size,0);assert.equal(f.count(),0);assert.equal(f.queued(),0);
});

test('R2 deletion failure remains durably queued and can be retried',async t=>{
  const f=fixture();t.after(f.close);const path=await persistImage(f.c,uri(jpg()),'alice');
  f.setDeleteFailure(true);await assert.rejects(removeMedia(f.c,path),/delete temporarily/);
  assert.equal(f.queued(),1);assert.equal(f.count(),1);assert.equal(f.objects.size,1);
  f.setDeleteFailure(false);await removeMedia(f.c,path);
  assert.equal(f.queued(),0);assert.equal(f.count(),0);assert.equal(f.objects.size,0);
  const calls=f.deleteCalls();await removeMedia(f.c,'/media/../../other-file');assert.equal(f.deleteCalls(),calls);
});
