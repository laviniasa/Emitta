// App do cliente: início, nova nota, resultado e cancelamento.
(() => {
  const { api, el, dinheiro, numeroDigitado, dataHora, formatarDocumento, seloSituacao, avisar, icone, logoCarregando, sair, exigirLogin } = Emitta;
  const $tela = document.getElementById("tela");

  const estado = {
    empresa: null, // {id, razao_social, municipio_nome, aliquota_iss, prazo_cancelamento_dias}
    servicos: [],
    notas: [],
    documentos: [], // guias de imposto enviadas pelo contador
    ambiente: "simulacao",
    tela: "carregando",
    form: { codigo: null, documento: "", nome: "", valor: "", descricao: "" },
    nota: null, // nota em foco
    erro: null,
    motivo: "erro",
    textoMotivo: "",
  };

  function ir(tela) {
    estado.tela = tela;
    desenhar();
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------ movimento
  const calmo = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // Ordem das telas: avançar desliza da direita, voltar desliza da esquerda.
  const ORDEM = { carregando: 0, semAcesso: 1, inicio: 1, detalhe: 2, nova: 2, impostos: 2, cancelar: 3, enviando: 3, erro: 4, processando: 4, sucesso: 4, cancelada: 4 };
  let telaAnterior = null;

  function animarTroca() {
    const atual = estado.tela;
    if (atual === telaAnterior) return false;
    const dir = telaAnterior && (ORDEM[atual] ?? 0) < (ORDEM[telaAnterior] ?? 0) ? "volta" : "vai";
    telaAnterior = atual;
    if (calmo) return true;
    $tela.dataset.dir = dir;
    $tela.classList.remove("animando");
    void $tela.offsetWidth; // reinicia a animação
    $tela.classList.add("animando");
    return true;
  }

  // Valores do topo contam do zero até o número certo.
  function contarNumeros() {
    $tela.querySelectorAll("[data-contar]").forEach((n) => {
      const alvo = parseFloat(n.dataset.contar) || 0;
      const formato = n.dataset.formato === "dinheiro" ? dinheiro : (v) => String(Math.round(v));
      if (calmo || !alvo) { n.textContent = formato(alvo); return; }
      const t0 = performance.now();
      const passo = (t) => {
        const k = Math.min(1, (t - t0) / 900);
        n.textContent = formato(alvo * (1 - Math.pow(1 - k, 3)));
        if (k < 1) requestAnimationFrame(passo);
      };
      requestAnimationFrame(passo);
    });
  }

  // Confete nas cores do Emitta quando a nota é autorizada.
  function confete() {
    if (calmo) return;
    const cores = ["#C6F36B", "#0F2A24", "#2BB673", "#FFFFFF", "#B2E24B"];
    for (let i = 0; i < 46; i++) {
      const c = document.createElement("span");
      c.className = "confete";
      c.style.left = Math.random() * 100 + "vw";
      c.style.background = cores[i % cores.length];
      c.style.setProperty("--x", (Math.random() * 160 - 80) + "px");
      c.style.setProperty("--r", (Math.random() * 900 - 450) + "deg");
      c.style.setProperty("--t", (1.6 + Math.random() * 1.4) + "s");
      c.style.animationDelay = Math.random() * 0.35 + "s";
      if (i % 3 === 0) { c.style.width = "8px"; c.style.height = "8px"; c.style.borderRadius = "50%"; }
      document.body.appendChild(c);
      setTimeout(() => c.remove(), 3600);
    }
    if (navigator.vibrate) navigator.vibrate([25, 40, 60]);
  }

  // Cupom com visto, desenhado em SVG (mesma forma da logo).
  function cupomOk() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "17 10 66 78"); svg.setAttribute("aria-hidden", "true");
    const papel = document.createElementNS(ns, "path");
    papel.setAttribute("d", "M27 14 H73 Q79 14 79 20 V84 L71.75 78.5 L64.5 84 L57.25 78.5 L50 84 L42.75 78.5 L35.5 84 L28.25 78.5 L21 84 V20 Q21 14 27 14 Z");
    papel.setAttribute("fill", "#C6F36B");
    const visto = document.createElementNS(ns, "path");
    visto.setAttribute("d", "M35 47 L46 58 L66 36"); visto.setAttribute("class", "visto");
    for (const [k, v] of Object.entries({ fill: "none", stroke: "#0F2A24", "stroke-width": "8", "stroke-linecap": "round", "stroke-linejoin": "round" })) visto.setAttribute(k, v);
    svg.append(papel, visto);
    return el("span", { class: "cupom-ok", role: "img", "aria-label": "Nota autorizada" }, svg);
  }

  // ------------------------------------------------------------ dados

  async function entrar(id) {
    ir("carregando");
    try {
      const [empresa, servicos, notas] = await Promise.all([
        api("GET", `/app/${id}`),
        api("GET", `/app/${id}/servicos`),
        api("GET", `/app/${id}/notas`),
      ]);
      Object.assign(estado, { empresa, servicos, notas });
      estado.documentos = estado.eu.papel === "autonomo" ? [] : await api("GET", `/app/${id}/documentos`).catch(() => []);
      ir(new URLSearchParams(location.search).get("tela") === "impostos" ? "impostos" : "inicio");
      const rascunho = rascunhoDoPainel();
      if (rascunho && rascunho.cliente_id === empresa.id) ajudaAgir(rascunho.acao);
      if (new URLSearchParams(location.search).get("nova") === "1" && servicos.length) novaNota();
    } catch (erro) {
      estado.erroCarga = erro.message;
      ir("semAcesso");
    }
  }

  async function recarregarNotas() {
    estado.notas = await api("GET", `/app/${estado.empresa.id}/notas`);
  }


  // ------------------------------------------------------------ componentes

  function barra(titulo, voltarPara, sub) {
    return el("header", { class: "barra" },
      voltarPara
        ? el("button", { class: "voltar", type: "button", "aria-label": "Voltar", onclick: () => ir(voltarPara) }, icone("voltar", 22))
        : el("span", { style: "width:8px" }),
      el("div", { style: "flex:1;min-width:0" },
        sub && el("div", { class: "sub" }, sub),
        el("h1", {}, titulo)),
      seloAmbiente(),
    );
  }

  function seloAmbiente() {
    if (estado.ambiente === "producao") return null;
    return el("span", { class: "selo selo-amarelo" }, estado.ambiente === "simulacao" ? "Teste" : "Homologação");
  }

  function menu(atual) {
    const item = (id, rotulo, ic, acao) =>
      el("button", { type: "button", "aria-current": atual === id ? "page" : null, onclick: acao }, icone(ic, 22), rotulo);
    return el("nav", { class: "menu", "aria-label": "Menu" },
      item("inicio", "Início", "casa", () => ir("inicio")),
      item("nova", "Emitir", "mais", novaNota),
      estado.eu.papel !== "autonomo" && el("button", {
        type: "button", "aria-current": atual === "impostos" ? "page" : null, onclick: () => ir("impostos"),
      }, el("span", { class: "menu-icone" }, icone("documento", 22),
        guiasPendentes().length ? el("span", { class: "menu-bolinha", "aria-label": `${guiasPendentes().length} para pagar` }, String(guiasPendentes().length)) : null),
      "Impostos"),
      item("ajuda", "Ajuda", "brilho", () => ajuda.abrir()),
      estado.eu.papel === "contador"
        ? item("painel", "Voltar ao painel", "voltar", () => { location.href = "/escritorio"; })
        : estado.eu.papel === "autonomo"
        ? item("ajustes", "Ajustes", "engrenagem", () => { location.href = "/escritorio"; })
        : item("sair", "Sair", "sair", () => { if (window.confirm("Sair do Emitta neste aparelho?")) sair(); }),
    );
  }

  function itemNota(n) {
    return el("button", { class: "nota-item", type: "button", onclick: () => { estado.nota = n; ir("detalhe"); } },
      el("span", { class: "esq" },
        el("span", { class: "nome" }, n.tomador.nome),
        el("span", { class: "det" }, `Nº ${String(n.numero_dps).padStart(6, "0")} · ${dataHora(n.emitida_em)}`)),
      el("span", { class: "dir" },
        el("strong", {}, dinheiro(n.valor)),
        seloSituacao(n.situacao)),
    );
  }

  // Passo a passo para quem configura sozinho (MEI): some quando a primeira nota sai.
  function passoAPasso() {
    if (estado.eu.papel !== "autonomo") return null;
    const passos = [
      { nome: "Enviar o certificado digital", feito: !!estado.empresa.tem_certificado, href: "/escritorio?aba=certificado" },
      { nome: "Escolher os seus serviços", feito: estado.servicos.length > 0, href: "/escritorio?aba=servicos" },
      { nome: "Emitir a primeira nota", feito: estado.notas.length > 0, acao: novaNota },
    ];
    if (passos.every((p) => p.feito)) return null;
    const proximo = passos.findIndex((p) => !p.feito);
    return el("section", { class: "card passo-a-passo" },
      el("strong", {}, "Seu passo a passo"),
      el("ol", {}, ...passos.map((p, i) => {
        const conteudo = [
          el("span", { class: "pp-num", "aria-hidden": "true" }, p.feito ? "✓" : String(i + 1)),
          el("span", { class: "pp-nome" }, p.nome, el("span", { class: "visualmente-oculto" }, p.feito ? " (feito)" : " (pendente)")),
          i === proximo && el("span", { class: "pp-ir" }, "Fazer agora", icone("seta", 16)),
        ];
        const classe = "pp" + (p.feito ? " feito" : "") + (i === proximo ? " atual" : "");
        return el("li", {}, p.acao
          ? el("button", { type: "button", class: classe, onclick: p.acao }, ...conteudo)
          : el("a", { class: classe, href: p.href }, ...conteudo));
      })));
  }

  // ------------------------------------------------------------ guias de imposto
  const guiasPendentes = () => estado.documentos.filter((d) => d.situacao !== "pago");
  const dataCurta = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().slice(0, 2).join("/") : "");

  function prazoGuia(d) {
    if (d.situacao === "pago") return { texto: `Paga em ${new Date(d.pago_em).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}`, classe: "ok" };
    if (!d.vencimento) return { texto: "Sem vencimento informado", classe: "" };
    const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
    const [a, m, dia] = d.vencimento.split("-").map(Number);
    const dias = Math.round((new Date(a, m - 1, dia) - hoje) / 86400000);
    if (dias < 0) return { texto: `Venceu em ${dataCurta(d.vencimento)}`, classe: "atrasada" };
    if (dias === 0) return { texto: "Vence hoje", classe: "urgente" };
    if (dias <= 3) return { texto: `Vence em ${dias} dia${dias > 1 ? "s" : ""} (${dataCurta(d.vencimento)})`, classe: "urgente" };
    return { texto: `Vence em ${dataCurta(d.vencimento)}`, classe: "" };
  }

  async function marcarPago(d, pago) {
    try {
      const novo = await api("POST", `/app/${estado.empresa.id}/documentos/${d.id}/pago`, { pago });
      estado.documentos = estado.documentos.map((x) => (x.id === d.id ? novo : x));
      if (pago) avisar("Pronto! Seu contador já vê que esta guia foi paga.");
      desenhar();
    } catch (erro) { avisar(erro.message); }
  }

  function cartaoGuia(d) {
    const prazo = prazoGuia(d);
    const nome = (d.arquivo_nome || "guia.pdf").replace(/[^\w.\- ]/g, "");
    return el("article", { class: "cartao-guia" + (d.situacao === "pago" ? " paga" : "") },
      el("div", { class: "cg-topo" },
        el("span", { class: "cg-tipo" }, d.tipo_nome),
        el("span", { class: "cg-prazo " + prazo.classe }, prazo.texto)),
      el("strong", { class: "cg-titulo" }, d.titulo),
      d.valor && el("span", { class: "cg-valor" }, `R$ ${d.valor}`),
      el("div", { class: "cg-acoes" },
        el("a", { class: "botao" + (d.situacao === "pago" ? " botao-secundario" : ""), href: d.arquivo, download: "", target: "_blank", rel: "noopener",
          onclick: (e) => { d.visto_em = d.visto_em || new Date().toISOString(); baixarArquivo(e, d.arquivo, nome.endsWith(".pdf") ? nome : nome + ".pdf", "application/pdf"); } },
          icone("download", 18), "Baixar guia"),
        d.situacao === "pago"
          ? el("button", { class: "botao-link", type: "button", onclick: () => marcarPago(d, false) }, "Desmarcar")
          : el("button", { class: "botao botao-secundario", type: "button", onclick: () => marcarPago(d, true) }, icone("certo", 18), "Já paguei")));
  }

  function avisoGuias() {
    const pend = guiasPendentes();
    if (!pend.length) return null;
    const primeira = pend.slice().sort((a, b) => String(a.vencimento || "9").localeCompare(String(b.vencimento || "9")))[0];
    const prazo = prazoGuia(primeira);
    return el("button", { type: "button", class: "aviso-guia " + prazo.classe, onclick: () => ir("impostos") },
      icone("documento", 22),
      el("span", { class: "ag-texto" },
        el("strong", {}, pend.length === 1 ? "Você tem 1 imposto para pagar" : `Você tem ${pend.length} impostos para pagar`),
        el("span", {}, [primeira.titulo, primeira.valor && `R$ ${primeira.valor}`, prazo.texto].filter(Boolean).join(" · "))),
      icone("seta", 18));
  }

  function nomeServico(codigo) {
    const s = estado.servicos.find((x) => x.codigo === codigo);
    return s ? s.apelido : codigo;
  }

  // ------------------------------------------------------------ telas

  const TELAS = {
    carregando: () => [
      el("div", { class: "conteudo", style: "display:grid;place-items:center" }, logoCarregando("Abrindo suas notas...")),
    ],

    semAcesso: () => [
      el("div", { class: "heroi" }, el("span", { class: "ola" }, "Emitta"), el("h1", {}, "Não foi possível abrir")),
      el("main", { class: "conteudo" },
        el("div", { class: "aviso aviso-erro" }, estado.erroCarga || "Empresa não encontrada."),
        el("button", { class: "botao botao-secundario", type: "button", onclick: sair }, "Sair e entrar com outra conta")),
    ],

    inicio: () => {
      const agora = new Date();
      const doMes = estado.notas.filter((n) => {
        const d = new Date(n.emitida_em);
        return n.situacao === "autorizada" && d.getMonth() === agora.getMonth() && d.getFullYear() === agora.getFullYear();
      });
      const total = doMes.reduce((s, n) => s + parseFloat(n.valor), 0);
      const mes = agora.toLocaleDateString("pt-BR", { month: "long" });
      return [
        el("header", { class: "heroi" },
          el("div", { style: "display:flex;justify-content:space-between;align-items:center;gap:12px" },
            el("div", {}, el("div", { class: "ola" }, "Olá,"), el("h1", {}, estado.empresa.razao_social)),
            seloAmbiente()),
          el("div", { class: "resumo" },
            el("div", {}, el("span", { class: "rot" }, `Faturado em ${mes}`), el("span", { class: "num", "data-contar": String(total), "data-formato": "dinheiro" }, dinheiro(total))),
            el("div", {}, el("span", { class: "rot" }, "Notas no mês"), el("span", { class: "num", "data-contar": String(doMes.length) }, String(doMes.length))))),
        el("main", { class: "conteudo" },
          estado.eu.papel === "contador" && el("div", { class: "aviso aviso-alerta" },
            icone("olho"), "Você está vendo o app como a empresa vê. As notas emitidas aqui ficam no nome dela."),
          passoAPasso(),
          avisoGuias(),
          estado.servicos.length
            ? el("button", { class: "botao botao-grande", type: "button", style: "min-height:60px;font-size:17px", onclick: novaNota },
              icone("mais", 22), "Nova nota")
            : estado.eu.papel === "autonomo"
            ? null
            : el("div", { class: "aviso aviso-alerta" }, icone("cadeado"),
              "Nenhum serviço liberado ainda. Peça ao seu contador para liberar os serviços da sua empresa."),
          estado.eu.papel === "autonomo" && el("div", { class: "atalhos" },
            el("a", { class: "atalho", href: "/escritorio?aba=servicos" }, icone("documento", 20), "Meus serviços"),
            el("a", { class: "atalho", href: "/escritorio?aba=certificado" }, icone("escudo", 20), "Certificado"),
            el("a", { class: "atalho", href: "/escritorio?aba=dados" }, icone("engrenagem", 20), "Dados")),
          el("h2", { style: "font-size:15px;margin-top:8px" }, "Últimas notas"),
          ...(estado.notas.length
            ? estado.notas.slice(0, 20).map(itemNota)
            : [el("div", { class: "card vazio" }, "Você ainda não emitiu nenhuma nota.")]),
        ),
        menu("inicio"),
      ];
    },

    impostos: () => {
      const pend = guiasPendentes().sort((a, b) => String(a.vencimento || "9").localeCompare(String(b.vencimento || "9")));
      const pagas = estado.documentos.filter((d) => d.situacao === "pago");
      return [
        barra("Impostos", "inicio", estado.empresa.razao_social),
        el("main", { class: "conteudo" },
          estado.documentos.length
            ? [
              el("p", { class: "sub", style: "margin:0" }, "Guias enviadas pelo seu contador. Baixe, pague no banco e toque em \"Já paguei\"."),
              el("h2", { style: "font-size:15px;margin-top:4px" }, "Para pagar"),
              ...(pend.length ? pend.map(cartaoGuia) : [el("div", { class: "card vazio" }, "Tudo pago por aqui!")]),
              pagas.length > 0 && el("h2", { style: "font-size:15px;margin-top:8px" }, "Pagas"),
              ...pagas.map(cartaoGuia),
            ]
            : el("div", { class: "card vazio" }, "Quando o seu contador enviar uma guia de imposto, ela aparece aqui.")),
        menu("impostos"),
      ];
    },

    nova: () => {
      const f = estado.form;
      const $totais = el("div", { class: "totais" });
      function atualizarTotais() {
        const v = numeroDigitado(f.valor);
        const i = v * parseFloat(estado.empresa.aliquota_iss) / 100;
        $totais.replaceChildren(
          el("div", { class: "linha", style: "color:var(--texto-2)" },
            el("span", {}, `ISS ${estado.empresa.aliquota_iss.replace(".", ",")}% (${estado.eu.papel === "autonomo" ? "dos seus ajustes" : "definido pelo contador"})`), el("span", {}, dinheiro(i))),
          el("div", { class: "linha total" }, el("span", {}, "Total da nota"), el("span", {}, dinheiro(v))));
      }
      atualizarTotais();

      const opcoes = estado.servicos.map((s) =>
        el("button", {
          class: "opcao", type: "button", role: "radio", "aria-checked": f.codigo === s.codigo ? "true" : "false",
          onclick: () => { f.codigo = s.codigo; desenhar(); },
        },
          el("span", { class: "bolinha" }),
          el("span", {}, el("span", { class: "opcao-titulo" }, s.apelido))));

      const entrada = (rotulo, chave, attrs = {}) =>
        el("label", { class: "campo" }, rotulo,
          el("input", { value: f[chave], ...attrs, oninput: (e) => { f[chave] = e.target.value; if (chave === "valor") atualizarTotais(); } }));

      // CNPJ do cliente: busca o nome na Receita e mostra a opção de retenção.
      const $dicaDoc = el("span", { class: "ajuda", "aria-live": "polite" });
      const $nome = el("input", { value: f.nome, autocomplete: "off", oninput: (e) => { f.nome = e.target.value; f.nomeAuto = false; } });
      const podeReter = () => limparDoc(f.documento).length === 14 && estado.empresa.opcao_simples !== "2";
      const $retencao = el("label", { class: "campo-check", hidden: !podeReter() },
        el("input", { type: "checkbox", checked: f.iss_retido, onchange: (e) => { f.iss_retido = e.target.checked; } }),
        el("span", {}, el("strong", { style: "display:block;font-size:14px;color:var(--texto)" }, "O cliente vai reter o ISS"),
          el("span", { class: "ajuda" }, "Marque só se o cliente (empresa) informou que retém o imposto. Na dúvida, pergunte ao seu contador.")));
      const $doc = el("input", {
        value: f.documento, inputmode: "text", autocapitalize: "characters", autocomplete: "off", placeholder: "Só números ou com pontos",
        oninput: (e) => {
          f.documento = e.target.value;
          $retencao.hidden = !podeReter();
          if (!podeReter()) f.iss_retido = false;
          const doc = limparDoc(f.documento);
          if (doc.length === 14) buscarNome(doc);
          else $dicaDoc.textContent = "";
        },
      });
      async function buscarNome(doc) {
        if (estado.ultimaConsulta === doc) return;
        estado.ultimaConsulta = doc;
        $dicaDoc.textContent = "Buscando o nome na Receita...";
        try {
          const r = await api("GET", `/consulta/cnpj/${doc}`, null, { semRedirecionar: true });
          if (limparDoc(f.documento) !== doc) return;
          if (!f.nome.trim() || f.nomeAuto) { f.nome = r.razao_social; f.nomeAuto = true; $nome.value = r.razao_social; }
          $dicaDoc.textContent = r.situacao && r.situacao !== "ATIVA"
            ? `Atenção: este CNPJ está ${r.situacao.toLowerCase()} na Receita.`
            : "Nome preenchido com os dados da Receita.";
        } catch (erro) {
          $dicaDoc.textContent = erro.status === 404 ? "CNPJ não encontrado na Receita. Confira os números." : "";
        }
      }
      const hoje = new Date();
      const hojeIso = new Date(hoje.getTime() - hoje.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

      const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });

      return [
        barra("Nova nota", "inicio", estado.empresa.razao_social),
        el("main", { class: "conteudo" },
          $erro,
          el("section", { class: "card secao" },
            el("div", { class: "secao-titulo" },
              el("h2", {}, "Qual serviço você prestou?"),
              el("span", { class: "selo selo-verde" }, icone("cadeado", 12), estado.eu.papel === "autonomo" ? "Seus serviços" : "Liberado pelo contador")),
            el("div", { role: "radiogroup", "aria-label": "Serviço", class: "secao" }, ...opcoes),
            el("p", { class: "ajuda-pequena" }, estado.eu.papel === "autonomo" ? el("a", { href: "/escritorio?aba=servicos" }, "Mudar meus serviços") : "Só aparecem os serviços que o seu contador liberou para a sua empresa.")),
          el("section", { class: "card secao" },
            el("h2", { style: "font-size:15px" }, "Para quem?"),
            el("div", { class: "campo" }, el("label", { class: "campo" }, "CNPJ ou CPF do cliente", $doc), $dicaDoc),
            el("label", { class: "campo" }, "Nome ou razão social", $nome),
            $retencao),
          el("section", { class: "card secao" },
            el("h2", { style: "font-size:15px" }, "Quanto e quando?"),
            entrada("Valor do serviço (R$)", "valor", { inputmode: "decimal", placeholder: "0,00", style: "font-size:18px;font-weight:600" }),
            el("div", { class: "campo" },
              el("label", { class: "campo" }, "Data do serviço",
                el("input", { type: "date", value: f.competencia, max: hojeIso, "aria-describedby": "ajuda-competencia",
                  onchange: (e) => { f.competencia = e.target.value; } })),
              el("span", { class: "ajuda", id: "ajuda-competencia" }, "Quando o serviço foi feito. Se foi no mês passado, mude aqui.")),
            entrada("Descrição do serviço", "descricao", { placeholder: "Ex.: Manutenção do computador de outubro" })),
        ),
        el("footer", { class: "rodape" },
          $totais,
          el("button", {
            class: "botao botao-grande", type: "button",
            onclick: () => {
              const falta = !f.codigo ? "Escolha o serviço que você prestou."
                : !limparDoc(f.documento) ? "Informe o CNPJ ou CPF do cliente."
                : !f.nome.trim() ? "Informe o nome do cliente."
                : numeroDigitado(f.valor) <= 0 ? "Informe o valor do serviço." : null;
              if (falta) { $erro.textContent = falta; $erro.hidden = false; $erro.scrollIntoView({ behavior: "smooth", block: "center" }); return; }
              emitir();
            },
          }, icone("enviar"), "Emitir nota")),
      ];
    },

    enviando: () => {
      const etapa = (rotulo, sub, tipo) => el("li", {},
        el("span", { class: "marca " + tipo }, tipo === "feita" ? icone("certo", 16, "#fff") : null),
        el("span", {}, el("strong", { style: "display:block;font-size:15px" }, rotulo), el("span", { class: "ajuda-pequena" }, sub)));
      return [
        barra("Transmitindo"),
        el("main", { class: "conteudo" },
          el("div", { class: "centro", style: "padding-top:32px" },
            el("div", { class: "impressora", role: "img", "aria-label": "Enviando" },
              el("div", { class: "fenda" }, el("div", { class: "papel" }, logoNoPapel(), el("span"), el("span"), el("span"))),
              el("div", { class: "corpo" })),
            el("p", { class: "grande", style: "font-size:18px" }, "Enviando para a prefeitura"),
            el("div", { class: "progresso-envio", "aria-hidden": "true" }, el("span")),
            el("p", { class: "ajuda-pequena", style: "font-size:14px" }, "Isso costuma levar poucos segundos. Não feche o app.")),
          el("ol", { class: "etapas card", id: "etapas-envio", "aria-live": "polite" },
            etapa("Dados conferidos", "Serviço liberado e documento válido", "agora"),
            etapa("Nota montada e assinada", "Com o certificado digital da empresa", "depois"),
            etapa("Enviando ao Emissor Nacional", "Conexão segura", "depois"),
            etapa("Aguardando autorização", "Resposta da prefeitura", "depois"))),
      ];
    },

    sucesso: () => [
      barra("Nota emitida"),
      el("main", { class: "conteudo" },
        el("div", { class: "centro" },
          cupomOk(),
          el("p", { class: "grande" }, "Nota autorizada"),
          estado.ambiente !== "producao" && el("p", { class: "ajuda-pequena", style: "color:var(--amarelo)" }, "Ambiente de teste, sem valor fiscal")),
        detalhesNota(estado.nota),
        botoesDownload(estado.nota)),
      el("footer", { class: "rodape" },
        el("button", { class: "botao botao-grande", type: "button", onclick: () => ir("inicio") }, "Voltar ao início"),
        el("button", { class: "botao botao-secundario", type: "button", onclick: novaNota }, "Emitir outra nota")),
    ],

    erro: () => [
      barra("Nota não emitida"),
      el("main", { class: "conteudo" },
        el("div", { class: "centro" },
          el("span", { class: "circulo balanca", style: "background:var(--vermelho-claro)" }, icone("alerta", 32, "#B42318")),
          el("p", { class: "grande" }, estado.erro.titulo),
          el("p", { class: "ajuda-pequena", style: "font-size:14px" }, "Nada foi emitido. Corrija e envie de novo.")),
        el("section", { class: "card secao", style: "border-color:#F4C7C3" },
          el("p", { style: "font-size:15px;font-weight:600" }, estado.erro.mensagem),
          ...(estado.erro.detalhes || []).map((d) => el("p", { class: "chave" }, d)))),
      el("footer", { class: "rodape" },
        el("button", { class: "botao botao-grande", type: "button", onclick: () => ir("nova") }, "Corrigir dados")),
    ],

    processando: () => [
      barra("Aguardando a prefeitura"),
      el("main", { class: "conteudo" },
        el("div", { class: "centro" },
          el("span", { class: "circulo balanca", style: "background:var(--amarelo-claro)" }, icone("relogio", 32, "#92400E")),
          el("p", { class: "grande" }, "A prefeitura ainda não respondeu"),
          el("p", { class: "ajuda-pequena", style: "font-size:14px" },
            "Pode ser instabilidade na internet ou no sistema do governo. Não emita a nota de novo: o Emitta confere sozinho se ela foi gerada, sem duplicar.")),
        detalhesNota(estado.nota)),
      el("footer", { class: "rodape" },
        el("button", { class: "botao botao-grande", type: "button", onclick: (e) => verificar(e.currentTarget) }, icone("trocar"), "Verificar agora"),
        el("button", { class: "botao botao-secundario", type: "button", onclick: () => ir("inicio") }, "Voltar ao início")),
    ],

    detalhe: () => {
      const n = estado.nota;
      const prazo = prazoRestante(n);
      return [
        barra(`Nota nº ${String(n.numero_dps).padStart(6, "0")}`, "inicio"),
        el("main", { class: "conteudo" },
          el("div", { style: "display:flex;justify-content:center" }, seloSituacao(n.situacao)),
          detalhesNota(n),
          (n.situacao === "autorizada" || n.situacao === "cancelada") && botoesDownload(n),
          n.situacao === "processando" && el("button", { class: "botao", type: "button", onclick: (e) => verificar(e.currentTarget) },
            icone("trocar"), "Verificar com a prefeitura"),
          n.situacao === "rejeitada" && n.mensagem && el("div", { class: "aviso aviso-erro" }, n.mensagem),
          n.situacao === "cancelada" && el("div", { class: "aviso aviso-info" },
            `Cancelada em ${dataHora(n.cancelada_em)}. Motivo: ${n.motivo_cancelamento}.`)),
        n.situacao === "autorizada" && el("footer", { class: "rodape" },
          prazo && el("p", { class: "ajuda-pequena", style: "text-align:center" }, prazo.texto),
          el("button", { class: "botao botao-texto-perigo", type: "button", onclick: () => { estado.motivo = "erro"; estado.textoMotivo = ""; ir("cancelar"); } },
            "Cancelar esta nota")),
      ];
    },

    cancelar: () => {
      const n = estado.nota;
      const prazo = prazoRestante(n);
      const motivos = [
        ["erro", "Emiti por engano", "Nota duplicada ou para o cliente errado"],
        ["nao_prestado", "O serviço não foi feito", "O cliente desistiu ou o serviço foi cancelado"],
        ["outro", "Outro motivo", "Você explica em uma frase"],
      ];
      const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
      const foraDoPrazo = prazo && prazo.vencido;
      return [
        barra("Cancelar nota", "detalhe"),
        el("main", { class: "conteudo" },
          el("section", { class: "card", style: "display:flex;justify-content:space-between;align-items:center;gap:12px" },
            el("span", {},
              el("strong", { style: "display:block" }, `Nota nº ${String(n.numero_dps).padStart(6, "0")}`),
              el("span", { class: "ajuda-pequena" }, `${n.tomador.nome} · ${dataHora(n.emitida_em)}`)),
            el("strong", {}, dinheiro(n.valor))),
          prazo && el("div", { class: foraDoPrazo ? "aviso aviso-alerta" : "aviso aviso-info" },
            icone("relogio"), foraDoPrazo
              ? "Já passou o prazo da sua prefeitura para cancelar direto. Será preciso pedir análise fiscal ao município; fale com o seu contador."
              : prazo.texto),
          $erro,
          !foraDoPrazo && el("section", { class: "card secao" },
            el("h2", { style: "font-size:15px" }, "Por que você quer cancelar?"),
            el("div", { role: "radiogroup", "aria-label": "Motivo", class: "secao" },
              ...motivos.map(([id, titulo, sub]) => el("button", {
                class: "opcao perigo", type: "button", role: "radio", "aria-checked": estado.motivo === id ? "true" : "false",
                onclick: () => { estado.motivo = id; desenhar(); },
              }, el("span", { class: "bolinha" }), el("span", {}, el("span", { class: "opcao-titulo" }, titulo), el("span", { class: "opcao-sub" }, sub))))),
            estado.motivo === "outro" && el("label", { class: "campo" }, "Explique em uma frase",
              el("textarea", { oninput: (e) => { estado.textoMotivo = e.target.value; } }, estado.textoMotivo))),
          !foraDoPrazo && el("button", { class: "card", type: "button", style: "display:flex;gap:10px;align-items:center;text-align:left;cursor:pointer", onclick: () => corrigir(n) },
            icone("trocar", 20, "#0E7C66"),
            el("span", {}, el("strong", { style: "display:block;font-size:14px" }, "Só errou um dado? Emita a nota corrigida"),
              el("span", { class: "ajuda-pequena" }, "Abre uma nota nova com os dados desta para você ajustar")))),
        !foraDoPrazo && el("footer", { class: "rodape" },
          el("button", {
            class: "botao botao-grande botao-perigo", type: "button",
            onclick: (e) => {
              if (estado.motivo === "outro" && estado.textoMotivo.trim().length < 15) {
                $erro.textContent = "Explique o motivo em uma frase (pelo menos 15 letras).";
                $erro.hidden = false;
                return;
              }
              cancelar(e.currentTarget);
            },
          }, "Cancelar nota"),
          el("p", { class: "ajuda-pequena", style: "text-align:center" }, "Não dá para desfazer. A nota cancelada aparece no painel do seu contador.")),
      ];
    },

    cancelada: () => [
      barra("Nota cancelada"),
      el("main", { class: "conteudo" },
        el("div", { class: "centro" },
          el("span", { class: "circulo carimbo", style: "background:var(--vermelho-claro)" }, icone("x", 30, "#B42318")),
          el("p", { class: "grande" }, "Nota cancelada"),
          el("p", { class: "ajuda-pequena", style: "font-size:14px" },
            `A prefeitura registrou o cancelamento da nota nº ${String(estado.nota.numero_dps).padStart(6, "0")}.`),
          el("p", { class: "ajuda-pequena", style: "font-size:14px" }, `Motivo: ${estado.nota.motivo_cancelamento}.`))),
      el("footer", { class: "rodape" },
        el("button", { class: "botao botao-grande", type: "button", onclick: () => ir("inicio") }, "Voltar ao início")),
    ],
  };

  function detalhesNota(n) {
    return el("section", { class: "card detalhes" },
      el("div", { class: "linha" }, el("span", {}, "Número"), el("strong", { style: "font-size:17px" }, String(n.numero_dps).padStart(6, "0"))),
      el("div", { class: "linha" }, el("span", {}, "Emitida em"), el("span", {}, dataHora(n.emitida_em))),
      el("div", { class: "linha" }, el("span", {}, "Cliente"), el("span", {}, n.tomador.nome)),
      el("div", { class: "linha" }, el("span", {}, n.tomador.tipo), el("span", {}, formatarDocumento(n.tomador.documento))),
      el("div", { class: "linha" }, el("span", {}, "Serviço"), el("span", {}, nomeServico(n.servico))),
      n.competencia && el("div", { class: "linha" }, el("span", {}, "Data do serviço"),
        el("span", {}, new Date(n.competencia + "T12:00:00").toLocaleDateString("pt-BR"))),
      el("div", { class: "linha" }, el("span", {}, n.iss_retido ? "ISS (retido pelo cliente)" : "ISS"), el("span", {}, dinheiro(n.iss))),
      el("div", { style: "height:1px;background:var(--borda)" }),
      el("div", { class: "linha", style: "font-size:17px;font-weight:700" }, el("span", { style: "color:var(--texto)" }, "Total"), el("span", {}, dinheiro(n.valor))),
      n.chave_acesso && el("div", { style: "display:flex;flex-direction:column;gap:4px" },
        el("span", { class: "ajuda-pequena" }, "Chave de acesso"), el("span", { class: "chave" }, n.chave_acesso)));
  }

  // No celular (principalmente iPhone), o link só abre o PDF na tela. Aqui
  // buscamos o arquivo e abrimos o "Compartilhar" do sistema, que tem
  // "Salvar em Arquivos", WhatsApp, e-mail... No computador, baixa normal.
  async function baixarArquivo(e, url, nome, tipo) {
    if (!navigator.canShare || !/iphone|ipad|ipod|android/i.test(navigator.userAgent)) return; // segue o link
    e.preventDefault();
    const botao = e.currentTarget;
    botao.classList.add("carregando");
    try {
      const resp = await fetch(url, { credentials: "same-origin" });
      if (!resp.ok) throw new Error();
      const arquivo = new File([await resp.blob()], nome, { type: tipo });
      if (navigator.canShare({ files: [arquivo] })) {
        await navigator.share({ files: [arquivo], title: nome });
      } else {
        location.href = url;
      }
    } catch (erro) {
      if (erro && erro.name === "AbortError") return; // a pessoa fechou o compartilhar
      location.href = url;
    } finally {
      botao.classList.remove("carregando");
    }
  }

  function botoesDownload(n) {
    const numero = String(n.numero || n.numero_dps || "").padStart(6, "0");
    return el("div", { style: "display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px" },
      el("a", { class: "botao botao-secundario", href: n.pdf, download: "", target: "_blank", rel: "noopener",
        onclick: (e) => baixarArquivo(e, n.pdf, `nota-${numero}.pdf`, "application/pdf") },
        icone("download", 18), "Baixar PDF"),
      el("a", { class: "botao botao-secundario", href: n.xml, download: "", target: "_blank", rel: "noopener",
        onclick: (e) => baixarArquivo(e, n.xml, `nota-${numero}.xml`, "application/xml") },
        icone("download", 18), "Baixar XML"));
  }

  function limparDoc(texto) {
    return String(texto || "").replace(/[^0-9A-Za-z]/g, "").toUpperCase();
  }

  function novaChaveEnvio() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
  }

  function hojeIsoLocal() {
    const d = new Date();
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  }

  function prazoRestante(n) {
    const dias = estado.empresa.prazo_cancelamento_dias;
    if (!dias) return null;
    const limite = new Date(new Date(n.emitida_em).getTime() + dias * 86400000);
    const vencido = Date.now() > limite.getTime();
    return { vencido, texto: `Dentro do prazo da sua prefeitura: dá para cancelar direto até ${limite.toLocaleDateString("pt-BR")}.` };
  }

  // ------------------------------------------------------------ assistente

  // A assistente monta rascunhos; aqui eles viram a tela de sempre, já preenchida,
  // para a pessoa conferir e confirmar.
  const ajuda = EmittaAssistente.montar({
    botao: false,
    clienteId: () => (estado.empresa ? estado.empresa.id : null),
    conta: () => (estado.eu ? estado.eu.id : null),
    sugestoes: ["Quero emitir uma nota", "Como cancelo uma nota?", "Como baixo o PDF?"],
    aoAgir: (acao) => ajudaAgir(acao),
  });

  function ajudaAgir(acao) {
      const d = acao.dados || {};
      if (acao.tipo === "nota") {
        if (!estado.servicos.some((s) => s.codigo === d.codigo)) { avisar("Esse serviço não está liberado."); return; }
        estado.form = {
          codigo: d.codigo, documento: formatarDocumento(d.documento), nome: d.nome, valor: d.valor, descricao: d.descricao,
          competencia: hojeIsoLocal(), iss_retido: false, chave_envio: novaChaveEnvio(),
        };
        avisar("Confira os dados e toque em Emitir nota.");
        ir("nova");
      } else if (acao.tipo === "cancelamento") {
        const n = estado.notas.find((x) => x.id === d.nota_id);
        if (!n) { avisar("Não achei essa nota. Atualize a tela."); return; }
        estado.nota = n;
        estado.motivo = d.motivo;
        estado.textoMotivo = d.texto_motivo || "";
        ir("cancelar");
      } else if (acao.tipo === "abrir" && d.tela === "nova") {
        novaNota();
      }
  }

  // Rascunho vindo do painel do contador (ele monta com a assistente e abre o app).
  function rascunhoDoPainel() {
    try {
      const r = JSON.parse(sessionStorage.getItem("emitta.rascunho") || "null");
      sessionStorage.removeItem("emitta.rascunho");
      return r;
    } catch { return null; }
  }

  // ------------------------------------------------------------ ações

  function novaNota() {
    if (!estado.servicos.length) {
      if (estado.eu.papel === "autonomo") { location.href = "/escritorio"; return; }
      avisar("Nenhum serviço liberado. Fale com o seu contador."); return;
    }
    estado.form = {
      codigo: estado.servicos.length === 1 ? estado.servicos[0].codigo : null, documento: "", nome: "", valor: "", descricao: "",
      competencia: hojeIsoLocal(), iss_retido: false, chave_envio: novaChaveEnvio(),
    };
    ir("nova");
  }

  function corrigir(n) {
    estado.form = {
      codigo: estado.servicos.some((s) => s.codigo === n.servico) ? n.servico : null,
      documento: formatarDocumento(n.tomador.documento), nome: n.tomador.nome,
      valor: String(n.valor).replace(".", ","), descricao: n.descricao,
      competencia: n.competencia || hojeIsoLocal(), iss_retido: !!n.iss_retido, chave_envio: novaChaveEnvio(),
    };
    avisar("Ajuste os dados e emita. Depois, cancele a nota antiga com o motivo \"Emiti por engano\".");
    ir("nova");
  }

  // As etapas acendem uma a uma enquanto a nota vai para o governo (a última espera a resposta).
  function logoNoPapel() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "30 28 40 40"); svg.setAttribute("class", "papel-logo"); svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = '<path pathLength="1" d="M35 46 H65 A15 15 0 1 0 60.6 56.6" fill="none" stroke="#0F2A24" stroke-width="8.5" stroke-linecap="round" stroke-linejoin="round"/>';
    return svg;
  }

  function avancarEtapas() {
    const marcar = (i, tipo) => {
      const m = document.querySelectorAll("#etapas-envio .marca")[i];
      if (!m) return;
      m.className = "marca " + tipo;
      m.replaceChildren(...(tipo === "feita" ? [icone("certo", 16, "#fff")] : []));
    };
    const passos = [[450, () => { marcar(0, "feita"); marcar(1, "agora"); }],
                    [1000, () => { marcar(1, "feita"); marcar(2, "agora"); }],
                    [1700, () => { marcar(2, "feita"); marcar(3, "agora"); }]];
    const timers = passos.map(([ms, f]) => setTimeout(() => { if (estado.tela === "enviando") f(); }, ms));
    return () => timers.forEach(clearTimeout);
  }

  async function emitir() {
    const f = estado.form;
    ir("enviando");
    const pararEtapas = avancarEtapas();
    const inicio = Date.now();
    try {
      const resposta = await api("POST", `/app/${estado.empresa.id}/notas`, {
        codigo_servico: f.codigo, tomador_documento: f.documento, tomador_nome: f.nome,
        valor: f.valor, descricao: f.descricao || null, competencia: f.competencia || null,
        iss_retido: !!f.iss_retido, chave_envio: f.chave_envio,
      });
      await esperarMinimo(inicio, 2100);
      pararEtapas();
      await recarregarNotas();
      if (resposta.processando) { estado.nota = resposta.nota; ir("processando"); return; }
      estado.nota = resposta;
      ir("sucesso");
    } catch (erro) {
      await esperarMinimo(inicio);
      const recusada = erro.status === 502;
      // Recusada: a tentativa ficou registrada; um novo envio precisa de chave nova.
      if (recusada) f.chave_envio = novaChaveEnvio();
      estado.erro = {
        titulo: recusada ? "A prefeitura recusou a nota" : "Confira os dados",
        mensagem: recusada ? "O Emissor Nacional não aceitou esta nota." : erro.message,
        detalhes: recusada && erro.dados && erro.dados.detail ? erro.dados.detail.detalhes : [],
      };
      if (recusada) await recarregarNotas().catch(() => {});
      ir("erro");
    }
  }

  async function verificar(botao) {
    botao.disabled = true;
    try {
      const r = await api("POST", `/app/${estado.empresa.id}/notas/${estado.nota.id}/verificar`);
      await recarregarNotas();
      if (r.processando) { avisar("A prefeitura ainda não confirmou. Tente de novo em alguns minutos."); botao.disabled = false; return; }
      estado.nota = r;
      ir("sucesso");
    } catch (erro) {
      botao.disabled = false;
      if (erro.status === 502) {
        await recarregarNotas().catch(() => {});
        estado.erro = { titulo: "A prefeitura recusou a nota", mensagem: "O Emissor Nacional não aceitou esta nota.",
          detalhes: erro.dados && erro.dados.detail ? erro.dados.detail.detalhes : [] };
        ir("erro");
      } else avisar(erro.message);
    }
  }

  async function cancelar(botao) {
    botao.disabled = true;
    try {
      const nota = await api("POST", `/app/${estado.empresa.id}/notas/${estado.nota.id}/cancelar`, {
        motivo: estado.motivo, texto: estado.motivo === "outro" ? estado.textoMotivo : null,
      });
      estado.nota = nota;
      await recarregarNotas();
      ir("cancelada");
    } catch (erro) {
      botao.disabled = false;
      avisar(erro.message);
    }
  }

  // Deixa a tela "Transmitindo" visível por um instante, para não piscar.
  function esperarMinimo(inicio, ms = 1200) {
    const resta = ms - (Date.now() - inicio);
    return resta > 0 ? new Promise((r) => setTimeout(r, resta)) : Promise.resolve();
  }

  function desenhar() {
    $tela.replaceChildren(...TELAS[estado.tela]().filter(Boolean));
    if (!animarTroca()) return; // mesma tela (ex.: escolheu um serviço): sem animação de entrada
    if (estado.tela === "inicio") contarNumeros();
    if (estado.tela === "sucesso") confete();
  }

  // ------------------------------------------------------------ início

  (async () => {
    desenhar();
    try {
      estado.ambiente = (await api("GET", "/status")).ambiente;
    } catch {}
    estado.eu = await exigirLogin();
    // A empresa só abre a própria conta. O contador pode abrir qualquer uma
    // pelo botão "Ver como o cliente vê" do painel.
    const propria = estado.eu.papel === "empresa" || estado.eu.papel === "autonomo";
    const id = propria ? estado.eu.cliente_id : parseInt(new URLSearchParams(location.search).get("empresa"), 10);
    if (!id) { location.href = "/escritorio"; return; }
    await entrar(id);
  })();
})();
