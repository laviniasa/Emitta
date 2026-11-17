// Assistente do Emitta: botão "Ajuda" + conversa. Ela só monta rascunhos;
// quem emite ou cancela é a pessoa, conferindo na tela de sempre.
window.EmittaAssistente = (() => {
  const { api, el, icone, formatarDocumento } = Emitta;

  function montar({ clienteId = () => null, aoAgir = () => {}, sugestoes = [], botao = true } = {}) {
    let mensagens = [];
    try { mensagens = JSON.parse(sessionStorage.getItem("emitta.assistente") || "[]"); } catch { mensagens = []; }
    let aberto = false;
    let pensando = false;

    const guardar = () => { try { sessionStorage.setItem("emitta.assistente", JSON.stringify(mensagens.slice(-20))); } catch {} };

    const $lista = el("div", { class: "assist-lista", "aria-live": "polite" });
    const $campo = el("textarea", {
      class: "assist-campo", rows: 1, maxlength: 1000, placeholder: "Escreva sua dúvida…", "aria-label": "Mensagem para a assistente",
      onkeydown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(); } },
      oninput: (e) => { e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px"; },
    });
    const $enviar = el("button", { class: "assist-enviar", type: "button", "aria-label": "Enviar", onclick: () => enviar() }, icone("enviar", 20));
    const $painel = el("section", { class: "assist-painel", role: "dialog", "aria-label": "Assistente do Emitta", hidden: true },
      el("header", { class: "assist-topo" },
        el("span", { class: "assist-avatar", "aria-hidden": "true" }, icone("brilho", 18)),
        el("div", {}, el("strong", {}, "Assistente Emitta"), el("span", { class: "assist-sub" }, "Eu preparo, você confere e confirma")),
        el("button", { class: "assist-x", type: "button", "aria-label": "Fechar ajuda", onclick: () => alternar(false) }, icone("fechar", 20))),
      $lista,
      el("div", { class: "assist-rodape" }, $campo, $enviar));
    const $botao = el("button", { class: "assist-botao", type: "button", "aria-label": "Abrir ajuda", onclick: () => alternar() },
      icone("brilho", 20), el("span", {}, "Ajuda"));
    document.body.append($painel);
    if (botao) document.body.append($botao);

    function alternar(forcar) {
      aberto = forcar ?? !aberto;
      $painel.hidden = !aberto;
      $botao.classList.toggle("oculto", aberto);
      document.body.classList.toggle("assist-aberto", aberto);
      if (aberto) { desenhar(); setTimeout(() => $campo.focus(), 50); }
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

    function desenhar() {
      const itens = [];
      if (!mensagens.length) {
        itens.push(el("div", { class: "assist-msg dela" },
          "Oi! Posso te ajudar a emitir ou cancelar uma nota, tirar dúvidas e muito mais. É só me dizer, por exemplo:"));
        itens.push(el("div", { class: "assist-sugestoes" }, ...sugestoes.map((s) => el("button", {
          type: "button", class: "assist-sugestao", onclick: () => enviar(s),
        }, s))));
      }
      for (const m of mensagens) {
        itens.push(el("div", { class: "assist-msg " + (m.de === "pessoa" ? "minha" : "dela") }, m.texto));
        for (const a of m.acoes || []) { const c = cartao(a); if (c) itens.push(c); }
      }
      if (pensando) itens.push(el("div", { class: "assist-msg dela pensando", "aria-label": "Pensando" }, el("span"), el("span"), el("span")));
      $lista.replaceChildren(...itens);
      $lista.scrollTop = $lista.scrollHeight;
    }

    async function enviar(texto) {
      texto = (texto ?? $campo.value).trim();
      if (!texto || pensando) return;
      $campo.value = "";
      $campo.style.height = "auto";
      mensagens.push({ de: "pessoa", texto });
      pensando = true;
      desenhar();
      try {
        const r = await api("POST", "/assistente", {
          mensagens: mensagens.slice(-14).map(({ de, texto: t }) => ({ de, texto: t })),
          cliente_id: clienteId(),
        });
        mensagens.push({ de: "assistente", texto: r.resposta, acoes: r.acoes || [] });
      } catch (erro) {
        mensagens.push({ de: "assistente", texto: erro.message || "Não consegui responder agora. Tente de novo." });
      }
      pensando = false;
      guardar();
      desenhar();
    }

    return { abrir: () => alternar(true), limpar: () => { mensagens = []; guardar(); desenhar(); } };
  }

  return { montar };
})();
