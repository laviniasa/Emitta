// Assistente do Emitta: botão "Ajuda" + conversa. Ela só monta rascunhos;
// quem emite ou cancela é a pessoa, conferindo na tela de sempre.
window.EmittaAssistente = (() => {
  const { api, el, icone, formatarDocumento, suporte } = Emitta;

  function montar({ clienteId = () => null, conta = () => null, aoAgir = () => {}, sugestoes = [], botao = true } = {}) {
    // A conversa é guardada por conta e por empresa: quem entra com outra conta
    // (ou abre outra empresa) começa uma conversa nova e nunca vê a de outra pessoa.
    let mensagens = [];
    let chaveAtual = null;
    let aberto = false;
    let pensando = false;

    const chave = () => `emitta.assistente.${conta() || "anon"}.${clienteId() || 0}`;
    function carregar() {
      const k = chave();
      if (k === chaveAtual) return;
      chaveAtual = k;
      try { mensagens = JSON.parse(sessionStorage.getItem(k) || "[]"); } catch { mensagens = []; }
    }
    const guardar = () => { try { sessionStorage.setItem(chaveAtual, JSON.stringify(mensagens.slice(-20))); } catch {} };

    const $lista = el("div", { class: "assist-lista", "aria-live": "polite" });
    const $campo = el("textarea", {
      class: "assist-campo", rows: 1, maxlength: 1000, placeholder: "Escreva sua dúvida…", "aria-label": "Mensagem para a assistente",
      onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); } },
      oninput: (e) => { e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px"; },
    });
    const $enviar = el("button", { class: "assist-enviar", type: "button", "aria-label": "Enviar", onclick: () => enviar() }, icone("enviar", 20));
    const $painel = el("section", { class: "assist-painel", role: "dialog", "aria-label": "Assistente do Emitta", hidden: true },
      el("header", { class: "assist-topo" },
        el("span", { class: "assist-avatar", "aria-hidden": "true" }, icone("balao", 18)),
        el("div", {}, el("strong", {}, "Assistente Emitta"), el("span", { class: "assist-sub" }, "Eu preparo, você confere e confirma")),
        el("button", { class: "assist-x", type: "button", "aria-label": "Fechar ajuda", onclick: () => alternar(false) }, icone("fechar", 20))),
      $lista,
      el("div", { class: "assist-rodape" }, $campo, $enviar));
    // Atalhos para quem prefere ler as respostas prontas ou falar com uma pessoa.
    const $atalhos = el("div", { class: "assist-atalhos" },
      el("a", { class: "assist-atalho", href: "/ajuda", target: "_blank", rel: "noopener" }, icone("livro", 16), "Central de ajuda"));
    suporte().then((c) => {
      const destino = c.whatsapp || c.email;
      if (destino) $atalhos.append(el("a", { class: "assist-atalho", href: destino, target: "_blank", rel: "noopener" },
        icone("balao", 16), c.whatsapp ? "Falar com uma pessoa" : "Mandar e-mail ao suporte"));
    });
    const $botao = el("button", { class: "assist-botao", type: "button", "aria-label": "Abrir ajuda", onclick: () => alternar() },
      icone("balao", 20), el("span", {}, "Ajuda"));
    document.body.append($painel);
    if (botao) document.body.append($botao);

    function alternar(forcar) {
      aberto = forcar ?? !aberto;
      $painel.hidden = !aberto;
      $botao.classList.toggle("oculto", aberto);
      document.body.classList.toggle("assist-aberto", aberto);
      if (aberto) { carregar(); desenhar(); setTimeout(() => $campo.focus(), 50); }
    }

    function cartao(acao) {
      const d = acao.dados || {};
      if (acao.tipo === "nota") {
        return el("div", { class: "assist-cartao" },
          el("strong", {}, "Rascunho da nota"),
          el("dl", {},
            el("dt", {}, "Serviço"), el("dd", {}, d.servico),
            el("dt", {}, "Cliente"), el("dd", {}, `${d.nome} · ${d.tipo_documento} ${formatarDocumento(d.documento)}`),
            el("dt", {}, "Valor"), el("dd", {}, `R$ ${d.valor}`),
            el("dt", {}, "Descrição"), el("dd", {}, d.descricao)),
          el("button", { class: "botao", type: "button", onclick: () => { alternar(false); aoAgir(acao); } }, "Conferir e emitir"),
          el("span", { class: "assist-nota" }, "Nada foi emitido ainda. Você confere tudo na próxima tela."));
      }
      if (acao.tipo === "cancelamento") {
        const motivo = { erro: "Erro na emissão", nao_prestado: "Serviço não prestado", outro: d.texto_motivo || "Outro" }[d.motivo];
        return el("div", { class: "assist-cartao perigo" },
          el("strong", {}, `Cancelar a nota nº ${d.numero}`),
          el("dl", {},
            el("dt", {}, "Cliente"), el("dd", {}, d.cliente),
            el("dt", {}, "Valor"), el("dd", {}, `R$ ${d.valor}`),
            el("dt", {}, "Motivo"), el("dd", {}, motivo)),
          el("button", { class: "botao botao-perigo", type: "button", onclick: () => { alternar(false); aoAgir(acao); } }, "Conferir e cancelar"),
          el("span", { class: "assist-nota" }, "Nada foi cancelado ainda. Você confirma na próxima tela."));
      }
      if (acao.tipo === "abrir") {
        return el("button", { class: "botao botao-secundario", type: "button", onclick: () => { alternar(false); aoAgir(acao); } }, d.rotulo || "Abrir");
      }
      return null;
    }

    // Texto da assistente: **negrito** vira negrito; quebras de linha são mantidas (CSS); nada de HTML.
    function formatar(texto) {
      const partes = String(texto || "").replace(/^#+\s*/gm, "").replace(/^\s*[*-]\s+/gm, "• ").split(/\*\*(.+?)\*\*/g);
      return partes.map((p, i) => (i % 2 ? el("strong", {}, p) : p.replace(/(^|\s)\*(\S)/g, "$1$2")));
    }

    function desenhar() {
      const itens = [];
      if (!mensagens.length) {
        itens.push(el("div", { class: "assist-msg dela" },
          "Oi! Posso te ajudar a emitir ou cancelar uma nota, tirar dúvidas e muito mais. É só me dizer, por exemplo:"));
        itens.push(el("div", { class: "assist-sugestoes" }, ...sugestoes.map((s) => el("button", {
          type: "button", class: "assist-sugestao", onclick: () => enviar(s),
        }, s))));
        itens.push($atalhos);
      }
      for (const m of mensagens) {
        itens.push(el("div", { class: "assist-msg " + (m.de === "pessoa" ? "minha" : "dela") }, ...(m.de === "pessoa" ? [m.texto] : formatar(m.texto))));
        for (const a of m.acoes || []) { const c = cartao(a); if (c) itens.push(c); }
      }
      if (pensando) itens.push(el("div", { class: "assist-msg dela pensando", "aria-label": "Pensando" }, el("span"), el("span"), el("span")));
      $lista.replaceChildren(...itens);
      $lista.scrollTop = $lista.scrollHeight;
    }

    async function enviar(texto) {
      texto = (texto ?? $campo.value).trim();
      if (!texto || pensando) return;
      carregar();
      $campo.value = "";
      $campo.style.height = "auto";
      mensagens.push({ de: "pessoa", texto });
      pensando = true;
      desenhar();
      try {
        const corpo = {
          mensagens: mensagens.slice(-14).map(({ de, texto: t }) => ({ de, texto: t })),
          cliente_id: clienteId(),
        };
        let r;
        try { r = await api("POST", "/assistente", corpo); }
        catch (e) {
          if (e.status) throw e; // erro de verdade do servidor: não repete
          await new Promise((ok) => setTimeout(ok, 2500)); // sem conexão: o servidor pode estar acordando
          r = await api("POST", "/assistente", corpo);
        }
        mensagens.push({ de: "assistente", texto: r.resposta, acoes: r.acoes || [] });
      } catch (erro) {
        mensagens.push({ de: "assistente", texto: erro.status ? (erro.message || "Não consegui responder agora. Tente de novo.") : "Não consegui falar com o Emitta agora. Confira a internet e tente de novo em alguns segundos." });
      }
      pensando = false;
      guardar();
      desenhar();
    }

    return { abrir: () => alternar(true), limpar: () => { mensagens = []; guardar(); desenhar(); } };
  }

  return { montar };
})();
