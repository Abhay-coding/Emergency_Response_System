const workerUrl = new URL(self.location.href);
const scope = new URL(self.registration.scope);
const assets = new URL(workerUrl.searchParams.get('assets') === 'static' ? 'static/' : './', scope);
const shell = new URL(assets.href === scope.href ? 'medical.html' : './', scope);
const release = workerUrl.searchParams.get('release') || '';
const cacheName = `campus-medical-shell-v3-${scope.pathname}-${release}`;
const files = ['medical.css', 'config.js', 'offline.js', 'medical.js'].map(file => new URL(file, assets));
for (const file of files) {
  if (file.pathname.endsWith('/offline.js')) continue;
  file.search = release;
}
const cachedFiles = new Set([shell.href, ...files.map(file => file.href)]);
importScripts(new URL('offline.js', assets));

self.addEventListener('install', event => {
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll([...cachedFiles])).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith(`campus-medical-shell-v3-${scope.pathname}-`) && name !== cacheName) {
        await caches.delete(name);
      }
    }
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const {request} = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  const isAppNavigation = request.mode === 'navigate' && url.origin === scope.origin &&
    [scope.pathname, shell.pathname].includes(url.pathname);
  if (!isAppNavigation && !cachedFiles.has(url.href)) return;
  event.respondWith((async () => {
    try {
      return await fetch(request);
    } catch {
      return (await (await caches.open(cacheName)).match(isAppNavigation ? shell : request)) ||
        new Response('Offline', {status: 503});
    }
  })());
});

self.addEventListener('sync', event => {
  if (event.tag !== 'sync-alerts') return;
  event.waitUntil((async () => {
    const pending = await OfflineStorage.getPendingAlerts();
    const results = await Promise.allSettled(pending.map(OfflineStorage.deliverAlert));
    for (const client of await self.clients.matchAll({type: 'window'})) {
      client.postMessage({type: 'ALERT_SYNCED'});
    }
    if (results.some(result => result.status === 'rejected')) throw Error('Some demo alerts still need delivery');
  })());
});
