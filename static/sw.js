self.addEventListener('install', (e) => {
    console.log('[Service Worker] Install');
});

self.addEventListener('fetch', (e) => {
    // 가장 기본적인 패스스루(Pass-through) 설정
    e.respondWith(fetch(e.request).catch(() => console.log('Offline mode')));
});