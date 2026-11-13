// App instalável: registra o service worker e oferece "Instalar o app".
(() => {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    });
  }

  const instalado = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  const botoes = () => document.querySelectorAll("[data-instalar]");
  if (instalado) return;

  // Android e computador (Chrome/Edge): o navegador avisa que dá para instalar.
  let pedido = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    pedido = e;
    botoes().forEach((b) => { b.hidden = false; });
  });
  document.addEventListener("click", async (e) => {
    const botao = e.target.closest("[data-instalar]");
    if (!botao) return;
    if (pedido) {
      pedido.prompt();
      await pedido.userChoice.catch(() => {});
      pedido = null;
      botoes().forEach((b) => { b.hidden = true; });
    } else {
      const dica = document.querySelector("[data-dica-iphone]");
      if (dica) dica.hidden = !dica.hidden;
    }
  });
  window.addEventListener("appinstalled", () => botoes().forEach((b) => { b.hidden = true; }));

  // iPhone (Safari): não tem botão automático, então mostramos o passo a passo.
  const iphone = /iphone|ipad|ipod/i.test(navigator.userAgent);
  if (iphone) {
    const mostrar = () => botoes().forEach((b) => { b.hidden = false; });
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mostrar); else mostrar();
  }
})();
