// Service worker do Emitta: deixa o app instalável e abre rápido.
// Segurança: só guarda arquivos visuais (estilos, scripts, ícones) e as telas
// de abertura e "sem internet". Nunca guarda notas, logins nem dados de empresas.
const VERSAO = "emitta-v13";
const ESSENCIAIS = [
  "/abrir",
  "/offline",
  "/static/estilo.css?v=12",
  "/static/abrir.js?v=13",
  "/static/pwa.js?v=12",
  "/static/icone.svg",
  "/static/icones/icone-192.png",
  "/static/icones/icone-512.png",
];
const PRIVADO = ["/auth", "/app/", "/contador", "/admin", "/consulta", "/catalogo", "/docs", "/openapi"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSAO).then((c) => c.addAll(ESSENCIAIS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== VERSAO).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (PRIVADO.some((p) => url.pathname.startsWith(p))) return; // dados: sempre direto do servidor

  // Páginas: sempre a versão nova do servidor; sem internet, a tela de aviso.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req).catch(async () => {
        if (url.pathname === "/abrir") return (await caches.match("/abrir")) || caches.match("/offline");
        return caches.match("/offline");
      }),
    );
    return;
  }

  // Arquivos visuais: usa o guardado na hora e atualiza em segundo plano.
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(
      caches.open(VERSAO).then(async (c) => {
        const guardado = await c.match(req);
        const novo = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => guardado);
        return guardado || novo;
      }),
    );
  }
});
