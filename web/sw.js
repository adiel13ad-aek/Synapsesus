'use strict';
const CACHE='synapse-ui-v03';
const ASSETS=['/','/index.html','/style.css','/app.js','/demo-adapter.js','/icon.svg','/icon-192.png','/icon-512.png','/manifest.webmanifest'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));self.skipWaiting();});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('synapse-')&&k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 // Never cache sessions, search results, messages, account data or uploaded media.
 if(event.request.method!=='GET'||url.origin!==self.location.origin||!ASSETS.includes(url.pathname))return;
 event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(event.request,copy));}return response;}).catch(()=>caches.match(event.request)));
});
