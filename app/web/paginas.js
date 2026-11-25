// Páginas de apoio (ajuda, termos, privacidade): canais de suporte e índice que acompanha a leitura.
(function () {
  "use strict";

  const ICONE_ZAP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';
  const ICONE_EMAIL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>';

  function link(href, texto, classe, icone) {
    const a = document.createElement("a");
    a.href = href;
    a.className = classe;
    if (href.startsWith("http")) { a.target = "_blank"; a.rel = "noopener"; }
    if (icone) a.insertAdjacentHTML("afterbegin", icone); // ícone fixo, sem dado de fora
    a.append(document.createTextNode(texto));
    return a;
  }

  async function canais() {
    try {
      const r = await fetch("/suporte", { headers: { Accept: "application/json" } });
      return r.ok ? await r.json() : {};
    } catch (_) { return {}; }
  }

  canais().then((c) => {
    const zap = c.whatsapp ? `https://wa.me/${c.whatsapp}?text=${encodeURIComponent("Olá! Tenho uma dúvida sobre o EmitHub.")}` : null;
    const email = c.email ? `mailto:${c.email}` : null;

    // Termos e privacidade: "fale com a gente ..."
    document.querySelectorAll("[data-contato]").forEach((alvo) => {
      if (!zap && !email) return;
      alvo.replaceChildren(document.createTextNode("pelo "));
      if (zap) alvo.append(link(zap, "WhatsApp", ""));
      if (zap && email) alvo.append(document.createTextNode(" ou pelo e-mail "));
      if (email) alvo.append(link(email, c.email, ""));
    });

    // Central de ajuda: caixa "Ainda com dúvida?"
    const botoes = document.getElementById("contato-botoes");
    const texto = document.getElementById("contato-texto");
    if (botoes) {
      if (zap) botoes.append(link(zap, "Chamar no WhatsApp", "botao-pilula cheio", ICONE_ZAP));
      if (email) botoes.append(link(email, "Mandar e-mail", "botao-pilula", ICONE_EMAIL));
      if (!zap && !email && texto) {
        texto.textContent = "Empresa ou MEI: fale com o seu contador. Dentro do EmitHub, a assistente do botão Ajuda também responde na hora.";
      }
    }
  });

  // Índice dos documentos: marca a seção que está sendo lida.
  const links = [...document.querySelectorAll(".doc-indice a")];
  if (links[0]) links[0].classList.add("atual");
  if (links.length && "IntersectionObserver" in window) {
    const porId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
    const visiveis = new Set();
    const obs = new IntersectionObserver((itens) => {
      itens.forEach((i) => (i.isIntersecting ? visiveis.add(i.target.id) : visiveis.delete(i.target.id)));
      const primeiro = [...porId.keys()].find((id) => visiveis.has(id));
      if (primeiro) links.forEach((a) => a.classList.toggle("atual", a === porId.get(primeiro)));
    }, { rootMargin: "-90px 0px -55% 0px" });
    porId.forEach((_, id) => { const s = document.getElementById(id); if (s) obs.observe(s); });
  }
})();
