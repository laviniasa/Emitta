// Abertura do app: mostra a animação da nota e leva cada pessoa para a sua área.
(() => {
  const calmo = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const minimo = calmo ? 300 : 2100; // tempo para a animação terminar
  const inicio = Date.now();

  const destino = fetch("/auth/eu", { credentials: "same-origin", cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((eu) => {
      if (!eu || eu.trocar_senha) return "/entrar";
      return { admin: "/admin", contador: "/escritorio", empresa: "/empresa" }[eu.papel] || "/entrar";
    })
    .catch(() => (navigator.onLine === false ? "/offline" : "/entrar"));

  destino.then((url) => {
    const resta = Math.max(0, minimo - (Date.now() - inicio));
    setTimeout(() => {
      const tela = document.getElementById("abertura");
      if (tela && !calmo) tela.classList.add("sai-da-tela");
      setTimeout(() => location.replace(url), calmo ? 0 : 320);
    }, resta);
  });
})();
