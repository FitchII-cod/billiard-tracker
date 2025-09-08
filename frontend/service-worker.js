const CACHE_NAME = 'billiard-tracker-v1';
const urlsToCache = [
  '/',
  '/manifest.json',
  '/index.html'
];

// Installation du Service Worker
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Cache ouvert');
        return cache.addAll(urlsToCache);
      })
  );
});

// Activation et nettoyage des anciens caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('Suppression ancien cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Stratégie de cache : Network First avec fallback sur cache
self.addEventListener('fetch', event => {
  // Pour les requêtes API, toujours essayer le réseau d'abord
  if (event.request.url.includes('/api/') || event.request.url.includes(':8000')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          // Si la requête réussit, mettre en cache et retourner
          if (response && response.status === 200) {
            const responseToCache = response.clone();
            caches.open(CACHE_NAME)
              .then(cache => {
                cache.put(event.request, responseToCache);
              });
          }
          return response;
        })
        .catch(() => {
          // Si le réseau échoue, essayer le cache
          return caches.match(event.request);
        })
    );
  } else {
    // Pour les ressources statiques, cache first
    event.respondWith(
      caches.match(event.request)
        .then(response => {
          if (response) {
            return response;
          }
          return fetch(event.request);
        })
    );
  }
});

// Gestion de la file d'attente offline pour les matchs
let offlineQueue = [];

self.addEventListener('sync', event => {
  if (event.tag === 'sync-matches') {
    event.waitUntil(syncOfflineMatches());
  }
});

async function syncOfflineMatches() {
  // Récupérer la file d'attente depuis IndexedDB
  const db = await openDB();
  const tx = db.transaction('offline_matches', 'readonly');
  const store = tx.objectStore('offline_matches');
  const matches = await store.getAll();

  for (const match of matches) {
    try {
      const response = await fetch('/api/matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(match)
      });

      if (response.ok) {
        // Supprimer de la file d'attente
        const deleteTx = db.transaction('offline_matches', 'readwrite');
        const deleteStore = deleteTx.objectStore('offline_matches');
        await deleteStore.delete(match.id);
      }
    } catch (error) {
      console.error('Erreur sync match:', error);
    }
  }
}

// Helper pour IndexedDB
function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('BilliardTracker', 1);
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    
    request.onupgradeneeded = event => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains('offline_matches')) {
        db.createObjectStore('offline_matches', { keyPath: 'id', autoIncrement: true });
      }
    };
  });
}