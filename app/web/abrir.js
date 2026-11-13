// Abertura do app: mostra a animação da nota e leva cada pessoa para a sua área.
// Nunca deixa a pessoa presa nesta tela: se o servidor demorar, segue para o login
// e, em último caso, mostra um botão "Entrar".
(() => {
  const calmo = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const minimo = calmo ? 300 : 2100; // tempo para a animação terminar
  const inicio = Date.now();
  let foi = false;

  const ir = (url) => {
    if (foi) return;
    foi = true;
    const tela = document.getElementById("abertura");
    if (tela && !calmo) tela.classList.add("sai-da-tela");
    setTimeout(() => location.replace(url), calmo ? 0 : 320);
  };

  // Pergunta ao servidor quem está entrando, com limite de tempo.
  const controle = "AbortController" in window ? new AbortController() : null;
  const limite = setTimeout(() => controle && controle.abort(), 8000);
  const destino = fetch("/auth/eu", { credentials: "same-origin", cache: "no-store", signal: controle ? controle.signal : undefined })
    .then((r) => (r.ok ? r.json() : null))
    .then((eu) => {
      if (!eu || eu.trocar_senha) return "/entrar";
      return { admin: "/admin", contador: "/escritorio", empresa: "/empresa" }[eu.papel] || "/entrar";
    })
    .catch(() => (navigator.onLine === false ? "/offline" : "/entrar"))
    .finally(() => clearTimeout(limite));

  destino.then((url) => {
    const resta = Math.max(0, minimo - (Date.now() - inicio));
    setTimeout(() => ir(url), resta);
  });

  // Rede de segurança: se nada aconteceu em 12 s, mostra o botão para entrar.
  setTimeout(() => {
    if (foi) return;
    const tela = document.getElementById("abertura");
    if (!tela || document.getElementById("entrar-manual")) return;
    const botao = document.createElement("a");
    botao.id = "entrar-manual";
    botao.href = "/entrar";
    botao.textContent = "Entrar";
    botao.className = "entrar-manual";
    tela.append(botao);
  }, 12000);
})();
