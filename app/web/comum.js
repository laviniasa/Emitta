// Funções compartilhadas entre o painel do contador e o app do cliente.

const Emitta = (() => {
  async function api(metodo, caminho, corpo, opcoes = {}) {
    let resp;
    try {
      resp = await fetch(caminho, {
        method: metodo,
        credentials: "same-origin",
        headers: {
          "X-Emitta": "1", // proteção contra envio forjado por outros sites (CSRF)
          ...(corpo ? { "Content-Type": "application/json" } : {}),
        },
        body: corpo ? JSON.stringify(corpo) : undefined,
      });
    } catch {
      throw new Error("Sem conexão com o servidor. Verifique a internet e tente de novo.");
    }
    const dados = await resp.json().catch(() => null);
    if (!opcoes.semRedirecionar) {
      if (resp.status === 401 && !caminho.startsWith("/auth/")) return irParaEntrar();
      const d = dados && dados.detail;
      if (resp.status === 403 && d && d.codigo === "trocar_senha") return irParaEntrar();
    }
    if (!resp.ok) {
      const erro = new Error(mensagemDeErro(dados, resp.status));
      erro.status = resp.status;
      erro.dados = dados;
      throw erro;
    }
    return dados;
  }

  function irParaEntrar() {
    const volta = location.pathname + location.search;
    location.href = "/entrar?volta=" + encodeURIComponent(volta);
    return new Promise(() => {}); // a página vai mudar; nada mais roda
  }

  async function sair() {
    try { await api("POST", "/auth/sair", null, { semRedirecionar: true }); } catch {}
    location.href = "/entrar";
  }

  // Confere quem está logado; se ninguém, manda para a tela de entrar.
  async function exigirLogin(papel) {
    let eu;
    try {
      eu = await api("GET", "/auth/eu", null, { semRedirecionar: true });
    } catch (erro) {
      if (erro.status === 401) return irParaEntrar();
      throw erro;
    }
    if (eu.trocar_senha) return irParaEntrar();
    if (papel && eu.papel !== papel) {
      location.href = { admin: "/admin", contador: "/escritorio" }[eu.papel] || "/empresa";
      return new Promise(() => {});
    }
    return eu;
  }

  function mensagemDeErro(dados, status) {
    const d = dados && dados.detail;
    if (typeof d === "string") return d;
    if (d && d.mensagem) return d.mensagem;
    if (Array.isArray(d) && d.length) {
      const campo = (d[0].loc || []).slice(-1)[0];
      return `Confira o campo "${campo}": ${d[0].msg}`;
    }
    if (status >= 500) return "O servidor teve um problema. Tente de novo em instantes.";
    return "Não foi possível concluir. Confira os dados e tente de novo.";
  }

  // Monta elementos com segurança (sem innerHTML com dados do usuário).
  // Limpa e-mails colados como link ("mailto:...") assim que a pessoa sai do campo.
  document.addEventListener("change", (e) => {
    const campo = e.target;
    if (campo instanceof HTMLInputElement && campo.type === "email") {
      campo.value = campo.value.trim().replace(/^mailto:/i, "").split("?")[0];
    }
  });

  function el(tag, atributos = {}, ...filhos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(atributos)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (v === true) e.setAttribute(k, "");
      else e.setAttribute(k, v);
    }
    for (const f of filhos.flat()) {
      if (f === null || f === undefined || f === false) continue;
      e.append(f instanceof Node ? f : document.createTextNode(String(f)));
    }
    return e;
  }

  function dinheiro(texto) {
    const n = typeof texto === "number" ? texto : parseFloat(texto);
    return (isNaN(n) ? 0 : n).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function numeroDigitado(texto) {
    let t = String(texto || "").replace(/[R$\s]/g, "");
    if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
    const n = parseFloat(t);
    return isNaN(n) ? 0 : n;
  }

  function dataHora(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString("pt-BR") + ", " + d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  }

  function formatarDocumento(doc) {
    const d = String(doc || "").replace(/[^0-9A-Za-z]/g, "").toUpperCase();
    if (d.length === 14) return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
    if (d.length === 11 && /^\d+$/.test(d)) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
    return doc;
  }

  const SITUACAO = {
    autorizada: ["Autorizada", "selo selo-verde"],
    cancelada: ["Cancelada", "selo selo-vermelho"],
    rejeitada: ["Recusada", "selo selo-cinza"],
    processando: ["Aguardando prefeitura", "selo selo-amarelo"],
  };
  function seloSituacao(situacao) {
    const [texto, classe] = SITUACAO[situacao] || [situacao, "selo selo-cinza"];
    return el("span", { class: classe }, texto);
  }

  let timerToast;
  function avisar(texto) {
    let t = document.querySelector(".toast");
    if (!t) {
      t = el("div", { class: "toast", role: "status" });
      document.body.append(t);
    }
    t.textContent = texto;
    t.hidden = false;
    clearTimeout(timerToast);
    timerToast = setTimeout(() => { t.hidden = true; }, 3200);
  }

  const ICONES = {
    voltar: "M15 18l-6-6 6-6",
    mais: "M12 5v14M5 12h14",
    enviar: "M22 2 11 13M22 2 15 22l-4-9-9-4 20-7z",
    certo: "M5 12l5 5L20 7",
    x: "M6 6l12 12M18 6 6 18",
    alerta: "M12 8v5M12 16.5v.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
    cadeado: "M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0v4",
    casa: "M3 11l9-7 9 7M5 10v10h14V10",
    relogio: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
    trocar: "M4 4v6h6M20 20v-6h-6M20 10A8 8 0 0 0 6 6L4 10M4 14a8 8 0 0 0 14 4l2-4",
    sair: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
    escudo: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z",
    chave: "M15 7a4 4 0 1 1-3.9 5H3v3h3v3h3v-3h2.1A4 4 0 0 1 15 7z",
    olho: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
    usuario: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
    download: "M12 4v12M7 11l5 5 5-5M5 20h14",
    documento: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6",
  };
  // Logo imprimindo em loop (tela de carregamento). SVG fixo, sem dados de fora.
  function logoCarregando(texto = "Carregando...") {
    const caixa = el("div", { class: "logo-carregando", role: "status" });
    caixa.innerHTML = '<div class="fenda"><svg viewBox="17 10 66 78" aria-hidden="true">'
      + '<path d="M27 14 H73 Q79 14 79 20 V84 L71.75 78.5 L64.5 84 L57.25 78.5 L50 84 L42.75 78.5 L35.5 84 L28.25 78.5 L21 84 V20 Q21 14 27 14 Z" fill="#C6F36B"/>'
      + '<path class="logo-e" pathLength="1" d="M35 46 H65 A15 15 0 1 0 60.6 56.6" fill="none" stroke="#0F2A24" stroke-width="8.5" stroke-linecap="round" stroke-linejoin="round"/>'
      + "</svg></div>";
    caixa.append(el("span", {}, texto));
    return caixa;
  }

  function icone(nome, tamanho = 20, cor = "currentColor") {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", tamanho);
    svg.setAttribute("height", tamanho);
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", cor);
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", ICONES[nome]);
    svg.append(p);
    return svg;
  }

  function guardar(chave, valor) {
    try { valor === null ? localStorage.removeItem(chave) : localStorage.setItem(chave, valor); } catch {}
  }
  function ler(chave) {
    try { return localStorage.getItem(chave); } catch { return null; }
  }

  return { api, el, dinheiro, numeroDigitado, dataHora, formatarDocumento, seloSituacao, avisar, icone, logoCarregando, guardar, ler, sair, exigirLogin };
})();
