// Painel do contador: empresas, serviços liberados e notas.
(() => {
  const { api, el, zonaArquivo, dinheiro, dataHora, formatarDocumento, seloSituacao, avisar, icone, guardar, ler, sair, exigirLogin } = Emitta;

  const estado = {
    clientes: [],
    selecionado: null, // id
    servicos: [], // catálogo com "liberado" e "apelido"
    notas: [],
    documentos: [],
    resumo: null, // números do mês do escritório (topo do painel)
    alterado: false,
    acessos: [],
    acessoCriado: null, // {email, senha_provisoria} mostrado uma única vez
    modo: "carregando", // carregando | cliente | nova | vazio | seguranca
    busca: "",
    buscaServico: "",
    prefeitura: {},
    rtcOpcoes: {}, // opções de IBS/CBS (Anexo VIII) por código de serviço
    aba: null, // servicos | notas | certificado | acesso | dados
    vistaServicos: "liberados", // liberados | todos
    eu: null,
    segredo2fa: null,
  };

  const $lista = document.getElementById("lista-clientes");
  const $principal = document.getElementById("principal");
  const $busca = document.getElementById("busca-cliente");
  const $btnNova = document.getElementById("btn-nova-empresa");
  $btnNova.append(icone("mais", 18), "Nova empresa");

  $btnNova.addEventListener("click", () => {
    if (!confirmarSaida()) return;
    estado.modo = "nova";
    estado.selecionado = null;
    desenharLista();
    desenharPrincipal();
    mostrarPrincipalNoCelular();
  });

  // No celular a lista fica em cima: rola até o conteúdo para a pessoa ver o que abriu.
  function mostrarPrincipalNoCelular() {
    if (window.innerWidth < 860) $principal.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  $busca.addEventListener("input", () => {
    estado.busca = $busca.value.trim().toLowerCase();
    desenharLista();
  });
  window.addEventListener("beforeunload", (e) => {
    if (estado.alterado) e.preventDefault();
  });

  function confirmarSaida() {
    return !estado.alterado || window.confirm("Há alterações nos serviços que não foram salvas. Sair mesmo assim?");
  }

  // ------------------------------------------------------------ assistente

  // No painel, o contador pode pedir ajuda e até montar uma nota de uma empresa:
  // o rascunho abre no app da empresa para ele conferir e emitir.
  EmittaAssistente.montar({
    clienteId: () => (estado.modo === "cliente" ? estado.selecionado : null),
    conta: () => (estado.eu ? estado.eu.id : null),
    sugestoes: ["Qual código uso para cabeleireiro?", "Como libero um serviço?", "Como envio o certificado?"],
    aoAgir: (acao) => {
      const id = estado.selecionado;
      if (!id) return;
      if (acao.tipo === "abrir") { location.href = `/empresa?empresa=${id}&nova=1`; return; }
      try { sessionStorage.setItem("emitta.rascunho", JSON.stringify({ cliente_id: id, acao })); } catch {}
      location.href = `/empresa?empresa=${id}`;
    },
  });

  // ------------------------------------------------------------ dados

  async function carregarClientes() {
    estado.clientes = await api("GET", "/contador/clientes");
  }

  async function abrirCliente(id) {
    if (!confirmarSaida()) return;
    estado.selecionado = id;
    estado.modo = "carregando";
    estado.alterado = false;
    estado.aba = null;
    estado.buscaServico = "";
    estado.vistaServicos = null;
    estado.sugeridos = null;
    guardar("emitta.painel.cliente", String(id));
    desenharLista();
    desenharPrincipal();
    try {
      const [servicos, notas, acessos, documentos] = await Promise.all([
        api("GET", `/contador/clientes/${id}/servicos`),
        api("GET", `/contador/clientes/${id}/notas`),
        api("GET", `/contador/clientes/${id}/acessos`),
        autonomo() ? [] : api("GET", `/contador/clientes/${id}/documentos`),
      ]);
      estado.documentos = documentos;
      carregarResumo(true);
      estado.servicos = servicos.map((s) => ({ ...s, apelido: s.apelido || s.descricao }));
      estado.notas = notas;
      estado.acessos = acessos;
      estado.acessoCriado = null;
      estado.modo = "cliente";
    } catch (erro) {
      avisar(erro.message);
      estado.modo = "vazio";
    }
    desenharPrincipal();
  }

  async function salvarServicos(botao) {
    const servicos = estado.servicos
      .filter((s) => s.liberado)
      .map((s) => ({ codigo: s.codigo, apelido: (s.apelido || "").trim() || s.descricao,
        codigo_municipal: (s.codigo_municipal || "").trim() || null,
        nbs: s.nbs || null, cind_op: s.cind_op || null, cclass_trib: s.cclass_trib || null }));
    botao.disabled = true;
    try {
      await api("PUT", `/contador/clientes/${estado.selecionado}/servicos`, { servicos });
      estado.alterado = false;
      await carregarClientes();
      desenharLista();
      desenharPrincipal();
      avisar("Serviços salvos. O app do cliente já mostra a nova lista.");
    } catch (erro) {
      avisar(erro.message);
      botao.disabled = false;
    }
  }

  // ------------------------------------------------------------ lista lateral

  function desenharLista() {
    $lista.replaceChildren();
    // A busca só aparece quando já existem empresas (antes confundia com o cadastro).
    $busca.closest(".card").hidden = estado.clientes.length === 0;
    // Sem empresas, o convite fica só no centro da tela ("Cadastrar empresa"): um botão só.
    const vazio = estado.clientes.length === 0 && !autonomo();
    $btnNova.closest(".lateral").hidden = vazio;
    const filtrados = estado.clientes.filter((c) => {
      if (!estado.busca) return true;
      const busca = estado.busca.replace(/\D/g, "");
      return c.razao_social.toLowerCase().includes(estado.busca) || (busca && c.cnpj.includes(busca));
    });
    if (!estado.clientes.length) {
      $lista.append(el("p", { class: "vazio" }, "Nenhuma empresa cadastrada ainda."));
      return;
    }
    if (!filtrados.length) {
      $lista.append(el("p", { class: "vazio" }, "Nenhuma empresa encontrada."));
      return;
    }
    if (!autonomo()) {
      $lista.append(el("button", {
        class: "item-cliente item-todas", type: "button", "aria-current": estado.modo === "notas" ? "true" : "false",
        onclick: () => abrirNotasEscritorio(),
      }, el("span", { class: "nome" }, icone("documento", 16), "Notas do escritório"),
        el("span", { class: "info" }, "Todas as empresas, com filtros e download")));
    }
    for (const c of filtrados) {
      const qtd = c.servicos_liberados;
      const selos = [];
      if (c.guias_vencidas) selos.push(el("span", { class: "selo-mini vermelho" }, c.guias_vencidas > 1 ? `${c.guias_vencidas} guias vencidas` : "Guia vencida"));
      if (!c.certificado) selos.push(el("span", { class: "selo-mini amarelo" }, "Sem certificado"));
      else if (!qtd) selos.push(el("span", { class: "selo-mini amarelo" }, "Sem serviços"));
      else if (!c.guias_vencidas) selos.push(el("span", { class: "selo-mini verde" }, "Pronta"));
      $lista.append(
        el("button", {
          class: "item-cliente", type: "button",
          "aria-current": c.id === estado.selecionado ? "true" : "false",
          onclick: () => abrirCliente(c.id).then(mostrarPrincipalNoCelular),
        },
          el("span", { class: "nome" }, c.razao_social),
          el("span", { class: "info" },
            `${c.municipio_nome} · ${qtd === 0 ? "nenhum serviço liberado" : qtd === 1 ? "1 serviço" : qtd + " serviços"}`),
          el("span", { class: "selos-cliente" }, ...selos),
        ),
      );
    }
  }

  // ------------------------------------------------------------ área principal

  // ------------------------------------------------------------ resumo do escritório
  // Cartões de números no topo (inspirados no KPI Tile do 21st.dev, no visual do Emitta):
  // valor que sobe contando, variação contra o mês anterior e minigráfico dos últimos 14 dias.
  const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  const calmo = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const reais = (c) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const reaisCurto = (c) => (c >= 1000000 ? "R$ " + (c / 100000).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) + " mil" : reais(c));
  let resumoPedido = null;
  let resumoAnimado = false; // anima só na primeira vez que os números aparecem

  async function carregarResumo(forcar = false) {
    if (autonomo() || !estado.clientes.length) return;
    if (resumoPedido && !forcar) return resumoPedido;
    resumoPedido = api("GET", "/contador/resumo").then((r) => {
      const mudou = JSON.stringify(r) !== JSON.stringify(estado.resumo);
      estado.resumo = r;
      if (mudou) { resumoAnimado = false; desenharPrincipal(); }
    }).catch(() => {});
    return resumoPedido;
  }

  function contar($n, alvo, formato) {
    if (calmo || !alvo) { $n.textContent = formato(alvo); return; }
    const t0 = performance.now();
    const passo = (t) => {
      const k = Math.min(1, (t - t0) / 900);
      $n.textContent = formato(alvo * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(passo);
    };
    requestAnimationFrame(passo);
  }

  function minigrafico(valores, rotulos, formato, $legenda, legendaPadrao) {
    const W = 100, H = 36, P = 3;
    const max = Math.max(...valores, 1);
    const passo = (W - P * 2) / Math.max(valores.length - 1, 1);
    const pts = valores.map((v, i) => [P + i * passo, H - P - (v / max) * (H - P * 2)]);
    const linha = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
    const area = `${linha} L${pts[pts.length - 1][0]} ${H} L${P} ${H} Z`;
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("aria-hidden", "true");
    const id = "g" + Math.random().toString(36).slice(2, 8);
    svg.innerHTML = `<defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#C6F36B" stop-opacity=".35"/><stop offset="1" stop-color="#C6F36B" stop-opacity="0"/></linearGradient></defs>`
      + `<path d="${area}" fill="url(#${id})" class="kpi-area"/>`
      + `<path d="${linha}" fill="none" stroke="#C6F36B" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" class="kpi-linha"/>`;
    const $ponto = el("span", { class: "kpi-ponto", hidden: true });
    const caixa = el("div", { class: "kpi-grafico" }, svg, $ponto);
    const mostrar = (i) => {
      if (i === null) { $ponto.hidden = true; $legenda.textContent = legendaPadrao; return; }
      const [x, y] = pts[i];
      $ponto.hidden = false; $ponto.style.left = `${x}%`; $ponto.style.top = `${(y / H) * 100}%`;
      $legenda.textContent = `${rotulos[i]} · ${formato(valores[i])}`;
    };
    caixa.addEventListener("pointermove", (e) => {
      const b = caixa.getBoundingClientRect();
      const i = Math.round((((e.clientX - b.left) / b.width) * W - P) / passo);
      mostrar(Math.min(Math.max(i, 0), valores.length - 1));
    });
    caixa.addEventListener("pointerleave", () => mostrar(null));
    return caixa;
  }

  function variacao(atual, anterior) {
    if (!atual && !anterior) return null;
    if (!anterior) return el("span", { class: "kpi-pilula boa" }, "novo");
    const pct = ((atual - anterior) / anterior) * 100;
    const sobe = pct >= 0;
    return el("span", { class: "kpi-pilula " + (sobe ? "boa" : "ruim"), "aria-label": `${sobe ? "Subiu" : "Caiu"} ${Math.abs(pct).toFixed(0)}%` },
      el("span", { class: "kpi-seta" + (sobe ? "" : " desce"), "aria-hidden": "true" }, "↗"), `${Math.abs(pct).toFixed(0)}%`);
  }

  function cartaoKpi({ rotulo, valor, formato, delta, legenda, grafico, barra }) {
    const $valor = el("span", { class: "kpi-valor" }, formato(0));
    const $legenda = el("span", { class: "kpi-legenda" }, legenda);
    const corpo = [
      el("span", { class: "kpi-rotulo" }, rotulo),
      el("div", { class: "kpi-linha-valor" }, $valor, delta || null),
      $legenda,
    ];
    if (grafico) corpo.push(minigrafico(grafico.valores, grafico.rotulos, grafico.formato, $legenda, legenda));
    if (barra) corpo.push(el("div", { class: "kpi-barra", role: "img", "aria-label": barra.texto },
      el("span", { style: `width:${Math.round(barra.parte * 100)}%` + (barra.alerta ? ";background:#F59E8B" : "") })));
    const cartao = el("article", { class: "kpi" }, ...corpo);
    if (resumoAnimado) $valor.textContent = formato(valor);
    else requestAnimationFrame(() => contar($valor, valor, formato));
    return cartao;
  }

  function faixaResumo() {
    const r = estado.resumo;
    if (autonomo() || !estado.clientes.length) return null;
    if (!r) { carregarResumo(); return el("section", { class: "resumo-escritorio carregando-resumo", "aria-busy": "true" }, el("div", { class: "kpi-esqueleto" })); }
    const mesAnt = MESES[(r.mes + 10) % 12];
    const rotulos = r.serie.map((d) => d.dia.slice(8, 10) + "/" + d.dia.slice(5, 7));
    const inteiro = (v) => String(Math.round(v));
    const comparar = `vs. mesmo período de ${mesAnt}`;
    const primeira = !resumoAnimado;
    requestAnimationFrame(() => { resumoAnimado = true; });
    return el("section", { class: "resumo-escritorio" + (primeira ? " entrando" : ""), "aria-label": "Resumo do escritório" },
      el("header", { class: "resumo-topo" },
        el("h2", {}, `Seu escritório em ${MESES[r.mes - 1]}`),
        el("button", { type: "button", class: "resumo-link", onclick: () => abrirNotasEscritorio() }, "Ver todas as notas", icone("seta", 14)),
        el("button", { type: "button", class: "resumo-atualizar", "aria-label": "Atualizar números", onclick: () => carregarResumo(true) }, icone("trocar", 16))),
      el("div", { class: "resumo-grade" },
        cartaoKpi({ rotulo: "Notas emitidas", valor: r.notas.total, formato: inteiro, delta: variacao(r.notas.total, r.notas.anterior),
          legenda: comparar, grafico: { valores: r.serie.map((d) => d.notas), rotulos, formato: (v) => `${v} nota${v === 1 ? "" : "s"}` } }),
        cartaoKpi({ rotulo: "Valor emitido", valor: r.valor.total_centavos, formato: reaisCurto, delta: variacao(r.valor.total_centavos, r.valor.anterior_centavos),
          legenda: comparar, grafico: { valores: r.serie.map((d) => d.valor_centavos), rotulos, formato: reais } }),
        cartaoKpi({ rotulo: "Guias para pagar", valor: r.guias.pendentes, formato: inteiro,
          delta: r.guias.vencidas ? el("span", { class: "kpi-pilula ruim" }, `${r.guias.vencidas} vencida${r.guias.vencidas > 1 ? "s" : ""}`) : null,
          legenda: r.guias.enviadas ? `${r.guias.enviadas - r.guias.pendentes} de ${r.guias.enviadas} já pagas` : "Nenhuma guia enviada ainda",
          barra: { parte: r.guias.enviadas ? (r.guias.enviadas - r.guias.pendentes) / r.guias.enviadas : 0, alerta: r.guias.vencidas > 0, texto: "Guias pagas" } }),
        cartaoKpi({ rotulo: "Empresas prontas", valor: r.empresas.prontas, formato: (v) => `${Math.round(v)} de ${r.empresas.total}`,
          legenda: r.empresas.sem_certificado ? `${r.empresas.sem_certificado} sem certificado` : "Todas com certificado",
          barra: { parte: r.empresas.total ? r.empresas.prontas / r.empresas.total : 0, texto: "Empresas prontas para emitir" } }),
      ));
  }

  // ------------------------------------------------------------ notas do escritório (todas as empresas)
  const mesAtual = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

  async function abrirNotasEscritorio() {
    if (!confirmarSaida()) return;
    estado.modo = "notas";
    estado.selecionado = null;
    estado.filtroNotas = estado.filtroNotas || { mes: mesAtual(), cliente_id: "", situacao: "", busca: "" };
    desenharLista();
    await carregarNotasEscritorio();
    mostrarPrincipalNoCelular();
  }

  async function carregarNotasEscritorio() {
    const f = estado.filtroNotas;
    estado.notasEscritorio = null;
    desenharPrincipal();
    const q = new URLSearchParams();
    if (f.mes) q.set("mes", f.mes);
    if (f.cliente_id) q.set("cliente_id", f.cliente_id);
    if (f.situacao) q.set("situacao", f.situacao);
    try { estado.notasEscritorio = await api("GET", "/contador/notas?" + q.toString()); }
    catch (erro) { estado.notasEscritorio = []; avisar(erro.message); }
    desenharPrincipal();
  }

  function telaNotasEscritorio() {
    const f = estado.filtroNotas;
    const termo = semAcento(f.busca || "");
    const todas = estado.notasEscritorio;
    const notas = (todas || []).filter((n) => !termo || semAcento(n.tomador.nome + " " + n.empresa).includes(termo) || n.tomador.documento.includes(termo.replace(/\D/g, "") || "#"));
    const autorizadas = notas.filter((n) => n.situacao === "autorizada");
    const total = autorizadas.reduce((t, n) => t + Math.round(parseFloat(n.valor) * 100), 0);
    const mudar = (campo) => (e) => { f[campo] = e.target.value; carregarNotasEscritorio(); };
    const $busca = el("input", { type: "search", placeholder: "Cliente, CPF/CNPJ ou empresa", value: f.busca || "", "aria-label": "Buscar nas notas",
      oninput: (e) => { f.busca = e.target.value; const pos = e.target.selectionStart; desenharPrincipal(); const novo = $principal.querySelector(".filtro-busca input"); if (novo) { novo.focus(); novo.setSelectionRange(pos, pos); } } });
    const chip = (valor, rotulo) => el("button", {
      type: "button", class: "chip-filtro", "aria-pressed": f.situacao === valor ? "true" : "false",
      onclick: () => { f.situacao = valor; carregarNotasEscritorio(); },
    }, rotulo);
    const baixar = (tipo) => {
      const q = new URLSearchParams({ tipo });
      if (f.mes) q.set("mes", f.mes);
      if (f.cliente_id) q.set("cliente_id", f.cliente_id);
      return "/contador/notas/arquivos.zip?" + q.toString();
    };
    const mesNome = f.mes ? `${MESES[parseInt(f.mes.slice(5, 7), 10) - 1]} de ${f.mes.slice(0, 4)}` : "todos os meses";
    return [
      el("section", { class: "card notas-escritorio" },
        el("div", { class: "ne-topo" },
          el("div", {},
            el("h1", { style: "font-size:22px" }, "Notas do escritório"),
            el("p", { class: "sub" }, todas === null ? "Carregando…"
              : `${notas.length} nota${notas.length === 1 ? "" : "s"} em ${mesNome} · ${reais(total)} autorizados`)),
          el("div", { class: "ne-baixar" },
            el("a", { class: "botao", href: baixar("ambos"), download: "" }, icone("download", 18), "Baixar PDFs e XMLs"),
            el("a", { class: "botao-link", href: baixar("xml"), download: "" }, "Só XMLs (.zip)"))),
        el("div", { class: "ne-filtros" },
          el("label", { class: "campo" }, "Mês", el("input", { type: "month", value: f.mes || "", onchange: mudar("mes") })),
          el("label", { class: "campo" }, "Empresa",
            el("select", { onchange: mudar("cliente_id") },
              el("option", { value: "" }, "Todas as empresas"),
              ...estado.clientes.map((c) => el("option", { value: String(c.id), selected: String(c.id) === String(f.cliente_id) }, c.razao_social)))),
          el("label", { class: "campo filtro-busca" }, "Buscar", $busca)),
        el("div", { class: "ne-chips", role: "group", "aria-label": "Situação" },
          chip("", "Todas"), chip("autorizada", "Autorizadas"), chip("cancelada", "Canceladas"), chip("rejeitada", "Recusadas")),
        todas === null
          ? el("div", { class: "carregando", role: "img", "aria-label": "Carregando", style: "margin:24px auto" })
          : notas.length
          ? el("div", { class: "tabela-caixa" }, el("table", { class: "tabela-notas" },
            el("thead", {}, el("tr", {},
              el("th", {}, "Nº"), el("th", {}, "Data"), el("th", {}, "Empresa"), el("th", {}, "Cliente"),
              el("th", { style: "text-align:right" }, "Valor"), el("th", {}, "Situação"), el("th", {}, "Arquivos"))),
            el("tbody", {}, ...notas.map((n) => el("tr", {},
              el("td", { class: "num" }, String(n.numero_dps).padStart(6, "0")),
              el("td", {}, dataHora(n.emitida_em)),
              el("td", {}, el("button", { type: "button", class: "botao-link", onclick: () => abrirCliente(n.cliente_id) }, n.empresa)),
              el("td", {}, n.tomador.nome),
              el("td", { class: "valor" }, dinheiro(n.valor)),
              el("td", {}, seloSituacao(n.situacao)),
              el("td", { style: "white-space:nowrap" },
                n.situacao === "autorizada" || n.situacao === "cancelada"
                  ? [el("a", { href: n.pdf, download: "", target: "_blank", rel: "noopener" }, "PDF"), " · ",
                    el("a", { href: n.xml, download: "", target: "_blank", rel: "noopener" }, "XML")]
                  : "—"))))))
          : el("div", { class: "vazio-ilustrado" },
            el("span", { class: "cupom-vazio", "aria-hidden": "true" }),
            el("strong", {}, "Nenhuma nota aqui"),
            el("span", {}, f.busca ? "Tente buscar de outro jeito ou limpe a busca." : "Mude o mês ou a empresa para ver outras notas."))),
    ];
  }

  function desenharPrincipal() {
    $principal.replaceChildren();
    if (estado.modo === "carregando") {
      $principal.append(el("div", { class: "card", style: "display:grid;place-items:center;padding:48px" },
        el("div", { class: "carregando", role: "img", "aria-label": "Carregando" })));
    } else if (estado.modo === "nova") {
      $principal.append(formularioNovaEmpresa());
    } else if (estado.modo === "cliente") {
      $principal.append(...[faixaResumo(), ...telaCliente()].filter(Boolean));
    } else if (estado.modo === "notas") {
      $principal.append(...[faixaResumo(), ...telaNotasEscritorio()].filter(Boolean));
    } else if (estado.modo === "seguranca") {
      $principal.append(...telaSeguranca());
    } else {
      const resumo = faixaResumo();
      if (resumo) $principal.append(resumo);
      $principal.append(el("div", { class: "card", style: "padding:40px 24px;text-align:center;display:flex;flex-direction:column;gap:12px;align-items:center" },
        el("h1", { style: "font-size:22px" }, "Bem-vindo ao Emitta"),
        el("p", { class: "sub2", style: "max-width:460px" },
          estado.clientes.length
            ? "Escolha uma empresa ao lado para liberar os serviços que ela pode emitir."
            : "Cadastre a primeira empresa para começar. Depois, libere os serviços que ela pode emitir."),
        !estado.clientes.length && el("button", { class: "botao", type: "button", onclick: () => $btnNova.click() },
          icone("mais", 18), "Cadastrar empresa"),
      ));
    }
  }

  // ------------------------------------------------------------ busca de serviços

  const semAcento = (t) => String(t || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const codigoBonito = (c) => (c && c.length === 6 ? `${c.slice(0, 2)}.${c.slice(2, 4)}.${c.slice(4)}` : c);
  function buscarServicos(lista, termo) {
    const digitos = termo.replace(/\D/g, "");
    const soCodigo = /^[\d.\s]+$/.test(termo);
    if (soCodigo && digitos) return lista.filter((s) => s.codigo.startsWith(digitos));
    const palavras = semAcento(termo).split(/\s+/).filter((p) => p.length > 1);
    if (!palavras.length) return [];
    // Compara pelo começo das palavras ("unha" não acha "testemunhagem").
    const texto = (s) => s._busca || (s._busca = " " + semAcento(`${s.descricao} ${s.item_descricao || ""} ${(s.palavras || []).join(" ")}`).replace(/[^a-z0-9]+/g, " "));
    const casa = (ps) => lista.filter((s) => ps.every((p) => texto(s).includes(" " + p)));
    let achados = casa(palavras);
    // "cabelo" acha "cabeleireiros", "contador" acha "contabilidade": tenta pelo começo da palavra
    if (!achados.length) achados = casa(palavras.map((p) => (p.length > 5 ? p.slice(0, p.length - 2) : p.length > 4 ? p.slice(0, 4) : p)));
    const termoTodo = semAcento(termo).trim();
    const nota = (s) => ((s.palavras || []).some((w) => semAcento(w) === termoTodo) ? 0
      : semAcento(s.descricao).startsWith(palavras[0]) ? 1
      : (" " + semAcento(s.descricao).replace(/[^a-z0-9]+/g, " ")).includes(" " + palavras[0]) ? 2 : 3);
    return achados.sort((a, b) => nota(a) - nota(b) || a.codigo.localeCompare(b.codigo));
  }

  const autonomo = () => estado.eu && estado.eu.papel === "autonomo";

  const ABAS = [
    { id: "servicos", nome: "Serviços" },
    { id: "notas", nome: "Notas" },
    { id: "impostos", nome: "Impostos" },
    { id: "certificado", nome: "Certificado" },
    { id: "acesso", nome: "Acesso ao app" },
    { id: "dados", nome: "Dados da empresa" },
  ];

  function irParaAba(aba) {
    estado.aba = aba;
    desenharPrincipal();
  }

  function telaCliente() {
    const c = estado.clientes.find((x) => x.id === estado.selecionado);
    const liberados = estado.servicos.filter((s) => s.liberado);
    if (!estado.aba) {
      const pedida = new URLSearchParams(location.search).get("aba");
      estado.aba = ABAS.some((a) => a.id === pedida) ? pedida : "servicos";
    }

    const cabecalho = el("section", { class: "card cabecalho-cliente" },
      el("div", {},
        el("h1", {}, c.razao_social),
        el("p", { class: "sub" }, `CNPJ ${formatarDocumento(c.cnpj)} · ${c.municipio_nome}`)),
      autonomo()
        ? el("a", { class: "botao", href: "/empresa" }, icone("mais", 18), "Emitir notas")
        : el("a", { class: "botao botao-secundario", href: `/empresa?empresa=${c.id}` }, "Ver como o cliente vê"),
    );

    // Passo a passo da empresa nova: some quando as três etapas estão prontas.
    const etapas = [
      { aba: "certificado", nome: "Certificado", feito: !!c.certificado },
      { aba: "servicos", nome: "Serviços", feito: c.servicos_liberados > 0 },
      autonomo() ? null : { aba: "acesso", nome: "Acesso ao app", feito: estado.acessos.length > 0 },
    ].filter(Boolean);
    const faltam = etapas.filter((e) => !e.feito).length;
    const passos = faltam > 0 && el("section", { class: "card passos" },
      el("div", { class: "passos-titulo" },
        el("strong", {}, "Deixe a empresa pronta para emitir"),
        el("span", { class: "sub2" }, faltam === 1 ? "Falta 1 etapa" : `Faltam ${faltam} etapas`)),
      el("ol", { class: "passos-lista" }, ...etapas.map((e, i) => el("li", {},
        el("button", {
          type: "button", class: "passo" + (e.feito ? " feito" : "") + (estado.aba === e.aba ? " atual" : ""),
          onclick: () => irParaAba(e.aba),
        },
          el("span", { class: "passo-num", "aria-hidden": "true" }, e.feito ? "✓" : String(i + 1)),
          el("span", {}, e.nome, el("span", { class: "visualmente-oculto" }, e.feito ? " (feito)" : " (pendente)")))))));

    const abas = el("div", { class: "abas-empresa", role: "tablist", "aria-label": "Seções da empresa" },
      ...ABAS.filter((a) => !(autonomo() && (a.id === "acesso" || a.id === "impostos"))).map((a) => el("button", {
        type: "button", role: "tab", class: "aba-empresa", id: `aba-${a.id}`,
        "aria-selected": estado.aba === a.id ? "true" : "false",
        onclick: () => { if (a.id !== estado.aba) irParaAba(a.id); },
      }, a.nome,
        a.id === "servicos" && el("span", { class: "aba-qtd" }, String(liberados.length)),
        a.id === "notas" && estado.notas.length > 0 && el("span", { class: "aba-qtd" }, String(estado.notas.length)),
        a.id === "impostos" && estado.documentos.length > 0 && el("span", { class: "aba-qtd" }, String(estado.documentos.length)))));

    let conteudo;
    if (autonomo() && (estado.aba === "acesso" || estado.aba === "impostos")) estado.aba = "servicos";
    if (estado.aba === "notas") conteudo = [secaoNotas()];
    else if (estado.aba === "impostos") conteudo = secaoImpostos(c);
    else if (estado.aba === "certificado") conteudo = [secaoCertificado(c)];
    else if (estado.aba === "acesso") conteudo = [secaoAcessos(c)];
    else if (estado.aba === "dados") conteudo = [secaoDados(c)];
    else conteudo = abaServicos(c, liberados);

    const voltar = autonomo() && el("a", { class: "voltar-app", href: "/empresa" }, icone("voltar", 18), "Voltar ao início do app");
    return [voltar || null, cabecalho, passos || null, abas,
      el("div", { role: "tabpanel", "aria-labelledby": `aba-${estado.aba}`, class: "painel-aba" }, ...conteudo),
    ].filter(Boolean);
  }

  // ------------------------------------------------------------ aba Serviços

  function abaServicos(c, liberados) {
    // Confere sozinho na prefeitura se ela aceita o serviço e já guarda o complemento
    // de 3 números que algumas pedem. A pessoa só vê o resultado, em linguagem simples.
    const conferir = async (s) => {
      const chave = `${c.id}:${s.codigo}`;
      estado.prefeitura[chave] = { carregando: true };
      try {
        const r = await api("GET", `/contador/clientes/${c.id}/servicos/${s.codigo}/prefeitura`);
        estado.prefeitura[chave] = r;
        const cods = r.codigos_municipais || [];
        if (cods.length && !cods.includes(s.codigo_municipal || "")) { s.codigo_municipal = cods[0]; marcarAlterado(); }
      } catch (erro) {
        estado.prefeitura[chave] = { erro: erro.message, status: erro.status };
      }
      desenharPrincipal();
    };

    const cartaoServico = (s) => {
      const chave = `${c.id}:${s.codigo}`;
      if (!estado.prefeitura[chave]) setTimeout(() => conferir(s), 0);
      const conferido = estado.prefeitura[chave] || { carregando: true };
      const apelido = el("input", {
        class: "apelido", value: s.apelido, "aria-label": `Nome que o cliente vê para ${s.descricao}`,
        oninput: (e) => { s.apelido = e.target.value; marcarAlterado(); atualizarPrevia(); },
      });
      const cidade = c.municipio_nome ? `de ${c.municipio_nome}` : "";
      let situacao;
      if (conferido.carregando) {
        situacao = el("span", { class: "resultado-pref neutro" }, `Conferindo com a prefeitura ${cidade}…`);
      } else if (conferido.administrado === true) {
        situacao = el("span", { class: "resultado-pref ok" }, "✓ Pronto para emitir");
      } else if (conferido.administrado === false) {
        situacao = el("span", { class: "resultado-pref nao" }, conferido.conveniado === false
          ? `✗ A prefeitura ${cidade} ainda não usa a nota nacional.`
          : `✗ A prefeitura ${cidade} não aceita este serviço. Tire da lista e escolha um parecido.`);
      } else if (conferido.status === 422 && !c.certificado) {
        situacao = el("span", { class: "resultado-pref neutro" }, "Para conferir com a prefeitura, envie o certificado digital. ",
          el("button", { type: "button", class: "botao-link", onclick: () => { estado.aba = "certificado"; desenharPrincipal(); } }, "Enviar agora"));
      } else {
        situacao = el("span", { class: "resultado-pref neutro" }, "Não deu para conferir agora. ",
          el("button", { type: "button", class: "botao-link", onclick: () => conferir(s) }, "Tentar de novo"));
      }
      // Reforma Tributária: NBS e classificação do IBS/CBS (sugestão do Anexo VIII, o contador pode trocar)
      const $rtc = el("div", { class: "rtc" });
      const desenharRtc = () => {
        const op = estado.rtcOpcoes[s.codigo];
        if (!op) { $rtc.replaceChildren(el("span", { class: "ajuda-pequena" }, "Carregando opções da Reforma Tributária…")); return; }
        if (!op.nbs.length) { $rtc.replaceChildren(el("span", { class: "ajuda-pequena" }, "Este serviço não tem IBS/CBS na tabela oficial.")); return; }
        if (!s.nbs) Object.assign(s, { nbs: op.sugerido.nbs, cind_op: op.sugerido.cind_op, cclass_trib: op.sugerido.cclass_trib });
        const fmt = (n) => `${n[0]}.${n.slice(1, 5)}.${n.slice(5, 7)}.${n.slice(7)}`;
        $rtc.replaceChildren(
          el("strong", { class: "rtc-titulo" }, "IBS e CBS (Reforma Tributária)"),
          el("label", { class: "campo" }, "NBS (classificação do serviço)",
            el("select", { onchange: (e) => { const n = op.nbs.find((x) => x.codigo === e.target.value); s.nbs = n.codigo; s.cind_op = n.cind_op; marcarAlterado(); desenharRtc(); } },
              ...op.nbs.map((n) => el("option", { value: n.codigo, selected: n.codigo === s.nbs }, `${fmt(n.codigo)} · ${n.descricao}`)))),
          el("label", { class: "campo" }, "Classificação tributária (cClassTrib)",
            el("select", { onchange: (e) => { s.cclass_trib = e.target.value; marcarAlterado(); } },
              ...op.cclass.map((c) => el("option", { value: c.codigo, selected: c.codigo === s.cclass_trib }, `${c.codigo} · ${c.nome}`)))),
          el("span", { class: "ajuda-pequena" }, `Indicador da operação (cIndOp): ${s.cind_op || "—"} · CST ${(s.cclass_trib || "").slice(0, 3) || "—"}. Preenchido pela tabela oficial (Anexo VIII); confira se combina com o serviço.`));
      };
      if (estado.rtcOpcoes[s.codigo]) desenharRtc();
      else $rtc.replaceChildren(el("span", { class: "ajuda-pequena" }, s.nbs ? `IBS/CBS: NBS ${s.nbs} · cClassTrib ${s.cclass_trib}` : "IBS/CBS: preenchido automaticamente ao salvar."));
      const avancado = el("details", { class: "mais-opcoes", ontoggle: async (e) => {
        if (!e.target.open || estado.rtcOpcoes[s.codigo]) return;
        desenharRtc();
        try { estado.rtcOpcoes[s.codigo] = await api("GET", `/catalogo/${s.codigo}/ibscbs`); } catch { estado.rtcOpcoes[s.codigo] = { nbs: [], cclass: [] }; }
        desenharRtc();
      } },
        el("summary", {}, "Ajuste avançado"),
        el("div", { class: "mais-opcoes-corpo" },
          $rtc,
          el("label", { class: "cod-mun" }, "Código municipal",
            el("input", {
              value: s.codigo_municipal || "", inputmode: "numeric", maxlength: 3, placeholder: "automático",
              oninput: (e) => { s.codigo_municipal = e.target.value.replace(/\D/g, "").slice(0, 3); e.target.value = s.codigo_municipal; marcarAlterado(); },
            })),
          el("span", { class: "ajuda-pequena" }, "O Emitta preenche sozinho com o que a prefeitura pede. Só mude se a prefeitura ou o contador mandar.")));
      return el("article", { class: "cartao-servico" },
        el("div", { class: "cartao-topo" },
          el("div", { class: "textos" },
            apelido,
            el("span", { class: "oficial" }, `${codigoBonito(s.codigo)} · ${s.descricao}`)),
          el("button", {
            type: "button", class: "botao-icone", "aria-label": `Tirar ${s.apelido || s.descricao} da lista`, title: "Tirar da lista",
            onclick: () => { s.liberado = false; marcarAlterado(); desenharPrincipal(); },
          }, icone("fechar", 18))),
        el("div", { class: "cartao-acoes" }, situacao),
        avancado);
    };

    if (!estado.vistaServicos) estado.vistaServicos = liberados.length ? "liberados" : "todos";
    const todos = estado.vistaServicos === "todos";
    const chave = el("div", { class: "chave-vista", role: "tablist", "aria-label": "Quais serviços mostrar" },
      el("button", { type: "button", role: "tab", "aria-selected": todos ? "false" : "true", id: "vista-liberados",
        onclick: () => { estado.vistaServicos = "liberados"; desenharPrincipal(); } },
        "Liberados ", el("span", { class: "aba-qtd" }, String(liberados.length))),
      el("button", { type: "button", role: "tab", "aria-selected": todos ? "true" : "false",
        onclick: () => { estado.vistaServicos = "todos"; desenharPrincipal(); } },
        "Todos os serviços ", el("span", { class: "aba-qtd" }, String(estado.servicos.length))));
    const lista = el("section", { class: "card col-servicos" },
      el("div", {},
        el("h2", { class: "titulo" }, "Serviços que a empresa pode emitir"),
        el("p", { class: "sub2", style: "margin-top:4px" }, todos
          ? "Lista nacional completa. Toque em \"Liberar\" nos serviços que esta empresa presta."
          : "Só os liberados aparecem no app do cliente. Toque no nome para trocar pelo nome que ele entende.")),
      chave,
      ...(todos ? catalogoServicos()
        : liberados.length ? liberados.map(cartaoServico)
        : [el("div", { class: "vazio-servicos" },
          el("p", {}, "Nenhum serviço liberado ainda."),
          el("p", { class: "sub2" }, "Abra \"Todos os serviços\": o Emitta já sugere os que combinam com a atividade (CNAE) da empresa."),
          el("button", { class: "botao", type: "button", style: "align-self:center;margin-top:8px",
            onclick: () => { estado.vistaServicos = "todos"; desenharPrincipal(); } }, "Ver serviços sugeridos"))]),
    );

    const previa = el("section", { class: "card previa", id: "previa" });
    function atualizarPrevia() {
      previa.replaceChildren(
        el("h2", {}, "O cliente vai ver no app"),
        ...(liberados.length
          ? liberados.map((s) => el("div", { class: "linha" }, icone("certo", 16, "#0E7C66"), (s.apelido || "").trim() || s.descricao))
          : [el("p", { style: "color:var(--vermelho);font-size:14px" }, "Nenhum serviço liberado: o cliente não consegue emitir.")]),
      );
    }
    atualizarPrevia();

    const botaoSalvar = el("button", {
      class: "botao botao-grande", type: "button", disabled: !estado.alterado, id: "botao-salvar-servicos",
      onclick: (e) => salvarServicos(e.currentTarget),
    }, estado.alterado ? "Salvar e enviar para o app" : "Tudo salvo");

    return [el("div", { class: "colunas" }, lista, el("div", { class: "col-lado" }, previa, botaoSalvar))];
  }

  function marcarAlterado() {
    estado.alterado = true;
    const b = document.getElementById("botao-salvar-servicos");
    if (b) { b.disabled = false; b.textContent = "Salvar e enviar para o app"; }
  }

  // Lista nacional completa dentro da aba Serviços: busca + áreas, com "Liberar" em cada um.
  function catalogoServicos() {
    const atualizarContagem = () => {
      const n = estado.servicos.filter((s) => s.liberado).length;
      const q = document.querySelector("#vista-liberados .aba-qtd");
      if (q) q.textContent = String(n);
      const q2 = document.querySelector("#aba-servicos .aba-qtd");
      if (q2) q2.textContent = String(n);
    };
    const linha = (s) => {
      const botao = el("button", {
        type: "button", class: s.liberado ? "botao-mini escolhido" : "botao-mini",
        "aria-pressed": s.liberado ? "true" : "false",
        onclick: () => {
          s.liberado = !s.liberado;
          if (s.liberado && !s.apelido) s.apelido = s.descricao;
          marcarAlterado();
          botao.className = s.liberado ? "botao-mini escolhido" : "botao-mini";
          botao.setAttribute("aria-pressed", s.liberado ? "true" : "false");
          botao.textContent = s.liberado ? "✓ Liberado" : "Liberar";
          linhaEl.classList.toggle("ligada", s.liberado);
          atualizarContagem();
        },
      }, s.liberado ? "✓ Liberado" : "Liberar");
      const linhaEl = el("div", { class: "linha-catalogo" + (s.liberado ? " ligada" : "") },
        el("span", { class: "textos" }, el("span", { class: "nome-servico" }, s.descricao), el("span", { class: "oficial" }, codigoBonito(s.codigo))),
        botao);
      return linhaEl;
    };
    const $resultados = el("div", { class: "resultados-servicos", "aria-live": "polite" });
    const desenhar = () => {
      const termo = estado.buscaServico.trim();
      if (!termo) {
        const areas = new Map();
        for (const s of estado.servicos) {
          const chave = s.item || s.codigo.slice(0, 2);
          if (!areas.has(chave)) areas.set(chave, { nome: s.item_descricao || `Item ${chave}`, lista: [] });
          areas.get(chave).lista.push(s);
        }
        $resultados.replaceChildren(
          el("p", { class: "sub2" }, `Ou navegue pelas ${areas.size} áreas da lista nacional:`),
          ...[...areas.entries()].map(([chave, a]) => {
            const qtdLib = a.lista.filter((s) => s.liberado).length;
            const caixa = el("details", { class: "area" },
              el("summary", {}, el("span", { class: "area-cod" }, chave), el("span", { class: "area-nome" }, a.nome),
                qtdLib ? el("span", { class: "area-qtd area-lib" }, `${qtdLib} liberado${qtdLib > 1 ? "s" : ""}`) : null,
                el("span", { class: "area-qtd" }, String(a.lista.length))));
            caixa.addEventListener("toggle", () => { if (caixa.open && caixa.children.length === 1) caixa.append(...a.lista.map(linha)); });
            return caixa;
          }));
        return;
      }
      const achados = buscarServicos(estado.servicos, termo);
      const LIMITE = 40;
      $resultados.replaceChildren(
        achados.length
          ? el("p", { class: "sub2" }, achados.length === 1 ? "1 serviço encontrado" : `${achados.length} serviços encontrados${achados.length > LIMITE ? ` (mostrando ${LIMITE})` : ""}`)
          : el("p", { class: "vazio" }, `Nada encontrado para "${termo}". Tente outra palavra ou o código (ex.: 17.19).`),
        ...achados.slice(0, LIMITE).map(linha));
    };
    const $busca = el("input", {
      type: "search", class: "busca-servico", value: estado.buscaServico,
      placeholder: "Buscar: ex. cabelo, contabilidade, 17.19", "aria-label": "Buscar serviço na lista nacional", autocomplete: "off",
      oninput: (e) => { estado.buscaServico = e.target.value; desenhar(); },
    });
    desenhar();
    return [blocoSugeridos(linha), el("div", { class: "busca-servico-campo" }, icone("busca", 18), $busca), $resultados];
  }

  // Serviços que combinam com as atividades (CNAE) da empresa na Receita.
  function blocoSugeridos(linha) {
    const caixa = el("section", { class: "sugeridos", "aria-live": "polite" });
    const id = estado.selecionado;
    const cnaeBonito = (c) => c.replace(/^(\d{2})(\d{2})(\d)(\d{2})$/, "$1.$2-$3-$4");
    const desenhar = () => {
      const r = estado.sugeridos;
      if (!r) { caixa.replaceChildren(el("p", { class: "sub2" }, "Buscando as atividades (CNAE) da empresa na Receita...")); return; }
      // cada serviço aparece uma vez só, no primeiro CNAE que o sugere (o principal vem antes)
      const mostrados = new Set();
      const comServico = (r.cnaes || []).map((c) => ({ ...c, servicos: c.servicos.filter((cod) => !mostrados.has(cod) && mostrados.add(cod)) }))
        .filter((c) => c.servicos.length);
      if (r.erro || !comServico.length) {
        caixa.replaceChildren(el("p", { class: "sub2" }, r.erro
          ? "Não deu para ver as atividades da empresa na Receita agora. Use a busca abaixo."
          : "As atividades (CNAE) desta empresa não têm serviço na tabela. Use a busca abaixo."));
        return;
      }
      const porCodigo = new Map(estado.servicos.map((s) => [s.codigo, s]));
      caixa.replaceChildren(
        el("div", { class: "sugeridos-topo" },
          el("h3", {}, "Sugeridos pela atividade da empresa"),
          el("p", { class: "sub2" }, "Pelos CNAEs do cartão CNPJ e pela tabela CNAE x Item da Lista de Serviços. Confira e libere os que ela realmente presta.")),
        ...comServico.map((c, i) => el("div", { class: "sugerido-cnae" },
          el("p", { class: "cnae-nome" }, el("span", { class: "cnae-cod" }, cnaeBonito(c.codigo)), " ", c.descricao,
            r.cnaes[0] && r.cnaes[0].codigo === c.codigo ? el("span", { class: "selo-mini" }, "principal") : null),
          ...c.servicos.map((cod) => porCodigo.get(cod)).filter(Boolean).map(linha))));
    };
    if (!estado.sugeridos) {
      api("GET", `/contador/clientes/${id}/servicos/sugeridos`)
        .then((r) => { if (estado.selecionado === id) { estado.sugeridos = r; desenhar(); } })
        .catch(() => { if (estado.selecionado === id) { estado.sugeridos = { cnaes: [], erro: "indisponível" }; desenhar(); } });
    }
    desenhar();
    return caixa;
  }

  // ------------------------------------------------------------ abas Notas e Dados

  function secaoNotas() {
    return el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:12px" },
      el("h2", { class: "titulo" }, "Notas desta empresa"),
      estado.notas.length
        ? el("div", { class: "tabela-caixa" },
          el("table", {},
            el("thead", {}, el("tr", {},
              el("th", {}, "Nº"), el("th", {}, "Data"), el("th", {}, "Cliente"),
              el("th", {}, "Situação"), el("th", { style: "text-align:right" }, "Valor"), el("th", {}, "Arquivos"))),
            el("tbody", {}, estado.notas.map((n) => el("tr", {},
              el("td", {}, String(n.numero_dps).padStart(6, "0")),
              el("td", {}, dataHora(n.emitida_em)),
              el("td", {}, n.tomador.nome,
                n.situacao === "cancelada" && n.motivo_cancelamento
                  ? el("div", { class: "sub2", style: "font-size:12px" }, "Cancelada: " + n.motivo_cancelamento) : null,
                n.situacao === "rejeitada" && n.mensagem
                  ? el("div", { class: "sub2", style: "font-size:12px" }, n.mensagem) : null),
              el("td", {}, seloSituacao(n.situacao)),
              el("td", { class: "valor" }, dinheiro(n.valor)),
              el("td", { style: "white-space:nowrap" },
                n.situacao === "autorizada" || n.situacao === "cancelada"
                  ? [el("a", { href: n.pdf, download: "", target: "_blank", rel: "noopener" }, "PDF"), " · ",
                    el("a", { href: n.xml, download: "", target: "_blank", rel: "noopener" }, "XML")]
                  : "—"),
            )))))
        : el("p", { class: "vazio" }, "Esta empresa ainda não emitiu notas."));
  }

  // ------------------------------------------------------------ aba Impostos (guias para a empresa)

  const dataCurta = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "");
  const quando = (iso) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" }) : "");

  function seloDocumento(d) {
    if (d.situacao === "pago") return el("span", { class: "selo selo-verde" }, `Pago · ${quando(d.pago_em)}`);
    if (d.situacao === "vencido") return el("span", { class: "selo selo-vermelho" }, "Vencido");
    if (d.visto_em) return el("span", { class: "selo selo-amarelo" }, `Visto · ${quando(d.visto_em)}`);
    return el("span", { class: "selo selo-cinza" }, "Ainda não abriu");
  }

  function secaoImpostos(c) {
    const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
    const hoje = new Date();
    const mesPassado = new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1);
    const competencia = `${mesPassado.getFullYear()}-${String(mesPassado.getMonth() + 1).padStart(2, "0")}`;
    const form = el("form", { class: "form-guia", novalidate: true },
      el("label", { class: "campo" }, "Tipo de guia",
        el("select", { name: "tipo" },
          ...[["darf", "DARF"], ["das", "DAS (Simples / MEI)"], ["iss", "Guia do ISS"], ["inss", "INSS / GPS"], ["fgts", "FGTS"], ["outro", "Outro documento"]]
            .map(([v, t]) => el("option", { value: v }, t)))),
      el("label", { class: "campo" }, "Mês de referência",
        el("input", { type: "month", name: "competencia", value: competencia })),
      el("label", { class: "campo" }, "Valor (R$)",
        el("input", { name: "valor", inputmode: "decimal", placeholder: "350,00", autocomplete: "off" })),
      el("label", { class: "campo" }, "Vencimento",
        el("input", { type: "date", name: "vencimento" })),
      el("div", { class: "campo campo-largo" }, "Arquivo da guia",
        zonaArquivo({ accept: "application/pdf,.pdf", extensoes: ["pdf"], maxBytes: 5 * 1024 * 1024,
          titulo: "Arraste o PDF da guia aqui", tipo: "PDF" })),
      el("button", { class: "botao campo-largo", type: "submit" }, icone("enviar", 18), "Enviar para a empresa"));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = (n) => form.querySelector(`[name=${n}]`).value.trim();
      const arquivo = form.querySelector("[name=arquivo]").files[0];
      const erro = (t) => { $erro.textContent = t; $erro.hidden = false; };
      if (!arquivo) return erro("Escolha o PDF da guia.");
      if (arquivo.size > 5 * 1024 * 1024) return erro("O PDF passa de 5 MB. Envie um arquivo menor.");
      if (!/\.pdf$/i.test(arquivo.name) && arquivo.type !== "application/pdf") return erro("Envie o arquivo em PDF.");
      const botao = form.querySelector("button[type=submit]");
      botao.disabled = true;
      $erro.hidden = true;
      try {
        const base64 = await new Promise((ok, falha) => {
          const leitor = new FileReader();
          leitor.onload = () => ok(String(leitor.result).split(",")[1] || "");
          leitor.onerror = () => falha(new Error("Não consegui ler o arquivo."));
          leitor.readAsDataURL(arquivo);
        });
        const doc = await api("POST", `/contador/clientes/${c.id}/documentos`, {
          tipo: v("tipo"), competencia: v("competencia") || null, valor: v("valor") || null,
          vencimento: v("vencimento") || null, arquivo_nome: arquivo.name, arquivo_base64: base64,
        });
        estado.documentos = [doc, ...estado.documentos];
        carregarResumo(true);
        avisar("Guia enviada. A empresa já vê no app, em Impostos.");
        desenharPrincipal();
      } catch (falha) {
        erro(falha.message);
        botao.disabled = false;
      }
    });

    const apagar = async (d) => {
      if (!confirm(`Apagar "${d.titulo}"? A empresa deixa de ver esta guia.`)) return;
      try {
        await api("DELETE", `/contador/clientes/${c.id}/documentos/${d.id}`);
        estado.documentos = estado.documentos.filter((x) => x.id !== d.id);
        desenharPrincipal();
      } catch (falha) { avisar(falha.message); }
    };

    const semAcesso = !estado.acessos.length && el("div", { class: "aviso aviso-alerta" },
      el("span", {}, "Esta empresa ainda não tem acesso ao app. Crie o acesso para ela ver as guias. ",
        el("button", { type: "button", class: "botao-link", onclick: () => irParaAba("acesso") }, "Criar acesso")));

    const lista = estado.documentos.length
      ? el("ul", { class: "lista-guias" }, ...estado.documentos.map((d) => el("li", { class: "guia" },
        el("div", { class: "guia-textos" },
          el("strong", {}, d.titulo),
          el("span", { class: "sub2" }, [d.valor && `R$ ${d.valor}`, d.vencimento && `vence ${dataCurta(d.vencimento)}`].filter(Boolean).join(" · ") || d.arquivo_nome)),
        seloDocumento(d),
        el("div", { class: "guia-acoes" },
          el("a", { class: "botao-mini", href: d.arquivo, target: "_blank", rel: "noopener" }, "PDF"),
          el("button", { type: "button", class: "botao-mini botao-texto-perigo", onclick: () => apagar(d) }, "Apagar")))))
      : el("p", { class: "vazio" }, "Nenhuma guia enviada ainda.");

    return [
      el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:14px" },
        el("div", {},
          el("h2", { class: "titulo" }, "Enviar guia para a empresa"),
          el("p", { class: "sub" }, "A empresa recebe no app, em Impostos, baixa e marca quando pagar. Você acompanha tudo aqui.")),
        semAcesso || null, form, $erro),
      el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:12px" },
        el("h2", { class: "titulo" }, "Guias enviadas"), lista),
    ].filter(Boolean);
  }

  function secaoDados(c) {
    const regime = { "1": "Fora do Simples", "2": "MEI", "3": "Simples Nacional (ME/EPP)" }[c.opcao_simples] || "—";
    const linha = (rotulo, valor) => el("div", { class: "linha" }, el("span", {}, rotulo), el("strong", {}, valor));
    return el("section", { class: "card regras", style: "max-width:640px" },
      el("h2", { class: "titulo" }, "Dados da empresa"),
      linha("Razão social", c.razao_social),
      linha("CNPJ", formatarDocumento(c.cnpj)),
      linha("Município", `${c.municipio_nome} (IBGE ${c.municipio_ibge})`),
      linha("Regime", regime),
      linha("Alíquota de ISS", `${String(c.aliquota_iss).replace(".", ",")}%`),
      c.opcao_simples === "3" && linha("Tributos aproximados do Simples", c.p_tot_trib_sn ? `${String(c.p_tot_trib_sn).replace(".", ",")}%` : "Não informado"),
      linha("Prazo para cancelar", c.prazo_cancelamento_dias ? `${c.prazo_cancelamento_dias} dias (informado por você)` : "Definido pela prefeitura"));
  }

  function formularioNovaEmpresa() {
    const campo = (rotulo, nome, attrs = {}, ajuda) => {
      const id = `ajuda-${nome}`;
      const input = el("input", { name: nome, ...attrs, "aria-describedby": ajuda ? id : null });
      return el("div", { class: "campo" },
        el("label", { class: "campo" }, rotulo, input),
        ajuda && el("span", { class: "ajuda", id }, ajuda));
    };
    const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
    const $dicaCnpj = el("div", { class: "aviso aviso-info", "aria-live": "polite", hidden: true });

    const form = el("form", { class: "card", style: "padding:24px;display:flex;flex-direction:column;gap:18px", novalidate: true },
      el("div", {},
        el("h1", { style: "font-size:22px" }, autonomo() ? "Cadastre a sua empresa" : "Nova empresa"),
        el("p", { class: "sub2", style: "margin-top:4px" }, autonomo()
          ? "Digite o seu CNPJ: o Emitta busca os dados na Receita. Depois você envia o certificado e escolhe os seus serviços. Dúvidas? Toque em Ajuda."
          : "Depois de cadastrar, você escolhe os serviços que ela pode emitir.")),
      $erro,
      $dicaCnpj,
      el("div", { class: "form-grade" },
        campo("CNPJ", "cnpj", { required: true, inputmode: "text", autocapitalize: "characters", placeholder: "00.000.000/0000-00", autocomplete: "off" },
          "Digite o CNPJ e o Emitta busca os dados na Receita."),
        campo("Razão social", "razao_social", { required: true }),
        campo("Município", "municipio_nome", { required: true, placeholder: "Ex.: São Paulo" }),
        campo("Código IBGE do município", "municipio_ibge", { required: true, inputmode: "numeric", maxlength: "7", placeholder: "7 dígitos" },
          "Ex.: São Paulo é 3550308"),
        el("div", { class: "campo" }, el("label", { class: "campo" }, "Regime",
          el("select", { name: "opcao_simples" },
            el("option", { value: "3" }, "Simples Nacional (ME/EPP)"),
            el("option", { value: "2" }, "MEI"),
            el("option", { value: "1" }, "Fora do Simples")))),
        campo("Alíquota de ISS (%)", "aliquota_iss", { required: true, inputmode: "decimal", placeholder: "Ex.: 3" }, "Entre 2% e 5%."),
        campo("Tributos aproximados do Simples (%)", "p_tot_trib_sn", { inputmode: "decimal", placeholder: "Ex.: 6,00" },
          "Obrigatório para ME/EPP ao emitir de verdade (alíquota efetiva do Simples)."),
        campo("Prazo para cancelar (dias)", "prazo_cancelamento_dias", { inputmode: "numeric", placeholder: "Opcional" },
          "Deixe em branco se não souber"),
      ),
      el("div", { class: "acoes" },
        !autonomo() && el("button", { class: "botao botao-secundario", type: "button", onclick: () => { estado.modo = estado.selecionado ? "cliente" : "vazio"; desenharPrincipal(); } }, "Cancelar"),
        el("button", { class: "botao", type: "submit" }, "Cadastrar empresa")),
    );

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(form));
      const faltando = ["cnpj", "razao_social", "municipio_nome", "municipio_ibge", "aliquota_iss"].filter((k) => !String(d[k] || "").trim());
      if (faltando.length) {
        $erro.textContent = "Preencha todos os campos obrigatórios.";
        $erro.hidden = false;
        form.querySelector(`[name=${faltando[0]}]`).focus();
        return;
      }
      const corpo = {
        cnpj: d.cnpj,
        razao_social: d.razao_social,
        municipio_nome: d.municipio_nome,
        municipio_ibge: String(d.municipio_ibge).replace(/\D/g, ""),
        aliquota_iss: String(d.aliquota_iss).replace(",", "."),
        prazo_cancelamento_dias: d.prazo_cancelamento_dias ? parseInt(d.prazo_cancelamento_dias, 10) : null,
        opcao_simples: d.opcao_simples || "3",
        p_tot_trib_sn: d.p_tot_trib_sn ? String(d.p_tot_trib_sn).replace(",", ".") : null,
      };
      const botao = form.querySelector("[type=submit]");
      botao.disabled = true;
      try {
        const novo = await api("POST", "/contador/clientes", corpo);
        await carregarClientes();
        avisar(autonomo() ? "Empresa cadastrada! Agora envie o certificado e escolha os seus serviços." : "Empresa cadastrada. Agora libere os serviços.");
        await abrirCliente(novo.id);
      } catch (erro) {
        $erro.textContent = erro.message;
        $erro.hidden = false;
        botao.disabled = false;
      }
    });
    // Busca os dados públicos da empresa assim que o CNPJ está completo.
    const $cnpj = form.querySelector("[name=cnpj]");
    let ultimo = "";
    $cnpj.addEventListener("input", async () => {
      const doc = $cnpj.value.replace(/[^0-9A-Za-z]/g, "").toUpperCase();
      if (doc.length !== 14 || doc === ultimo) return;
      ultimo = doc;
      $dicaCnpj.hidden = false;
      $dicaCnpj.textContent = "Buscando os dados da empresa na Receita...";
      try {
        const r = await api("GET", `/consulta/cnpj/${doc}`);
        const preencher = (nome, valor) => { const c = form.querySelector(`[name=${nome}]`); if (valor && !c.value.trim()) c.value = valor; };
        preencher("razao_social", r.razao_social);
        preencher("municipio_nome", r.municipio);
        preencher("municipio_ibge", r.codigo_municipio_ibge);
        if (r.regime) form.querySelector("[name=opcao_simples]").value = r.regime;
        const regime = { "1": "fora do Simples", "2": "MEI", "3": "Simples Nacional" }[r.regime] || "regime não informado";
        $dicaCnpj.textContent = `Dados da Receita: ${r.razao_social} · ${r.municipio}/${r.uf} · ${regime}` +
          (r.cnae_principal && r.cnae_principal.descricao ? ` · Atividade: ${r.cnae_principal.descricao}` : "") +
          (r.situacao && r.situacao !== "ATIVA" ? ` · ATENÇÃO: situação ${r.situacao}` : "") + ". Confira antes de salvar.";
      } catch (erro) {
        $dicaCnpj.textContent = erro.status === 404 ? "CNPJ não encontrado na Receita. Preencha os dados manualmente."
          : "Não foi possível consultar a Receita agora. Preencha os dados manualmente.";
      }
    });
    setTimeout(() => $cnpj.focus(), 0);
    return form;
  }

  // ------------------------------------------------------------ certificado digital

  function secaoCertificado(c) {
    const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
    const cert = c.certificado;
    let corpo;
    if (cert) {
      const validade = new Date(cert.validade);
      const dias = Math.ceil((validade - Date.now()) / 86400000);
      corpo = [
        el("div", { class: dias <= 30 ? "aviso aviso-alerta" : "aviso aviso-info" }, icone("escudo"),
          el("span", {}, el("strong", { style: "display:block" }, cert.titular || "Certificado A1"),
            `Válido até ${validade.toLocaleDateString("pt-BR")}` + (dias <= 30 ? ` — vence em ${dias} dia(s). Providencie a renovação.` : "."))),
        el("div", {}, el("button", {
          class: "botao botao-texto-perigo", type: "button",
          onclick: async () => {
            if (!window.confirm("Remover o certificado desta empresa? Ela não conseguirá emitir até enviar outro.")) return;
            try { await api("DELETE", `/contador/clientes/${c.id}/certificado`); await carregarClientes(); desenharPrincipal(); }
            catch (erro) { avisar(erro.message); }
          },
        }, "Remover certificado")),
      ];
    } else {
      const form = el("form", { class: "form-grade", novalidate: true },
        el("div", { class: "campo campo-largo" }, "Arquivo do certificado (.pfx ou .p12)",
          zonaArquivo({ accept: ".pfx,.p12,application/x-pkcs12", extensoes: ["pfx", "p12"], maxBytes: 50 * 1024,
            titulo: "Arraste o certificado A1 aqui", tipo: "certificado", dica: "Arquivo .pfx ou .p12 · fica guardado cifrado" })),
        el("label", { class: "campo" }, "Senha do certificado",
          el("input", { type: "password", name: "senha", autocomplete: "off", required: true })),
        el("div", { style: "display:flex;align-items:flex-end" }, el("button", { class: "botao", type: "submit", style: "width:100%" }, "Enviar certificado")));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const arquivo = form.querySelector("[name=arquivo]").files[0];
        const senha = form.querySelector("[name=senha]").value;
        if (!arquivo || !senha) { $erro.textContent = "Escolha o arquivo e digite a senha."; $erro.hidden = false; return; }
        if (arquivo.size > 50 * 1024) { $erro.textContent = "Arquivo grande demais para um certificado A1."; $erro.hidden = false; return; }
        const botao = form.querySelector("button");
        botao.disabled = true;
        $erro.hidden = true;
        try {
          const bytes = new Uint8Array(await arquivo.arrayBuffer());
          let binario = "";
          bytes.forEach((b) => { binario += String.fromCharCode(b); });
          await api("POST", `/contador/clientes/${c.id}/certificado`, { arquivo_base64: btoa(binario), senha });
          await carregarClientes();
          estado.prefeitura = {}; // agora dá para conferir os serviços na prefeitura
          avisar("Certificado conferido e guardado com segurança.");
          desenharPrincipal();
        } catch (erro) {
          $erro.textContent = erro.message;
          $erro.hidden = false;
          botao.disabled = false;
        }
      });
      corpo = [
        el("div", { class: "aviso aviso-alerta" }, icone("alerta"),
          "Sem certificado, esta empresa só emite no modo de teste. Para emitir no governo, envie o certificado A1 (e-CNPJ) dela."),
        form,
      ];
    }
    return el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:14px" },
      el("div", {},
        el("h2", { class: "titulo" }, "Certificado digital"),
        el("p", { class: "sub2", style: "margin-top:4px" },
          "Usado para assinar as notas. O arquivo e a senha ficam guardados criptografados e nunca aparecem de novo.")),
      $erro, ...corpo);
  }

  // ------------------------------------------------------------ acesso da empresa

  function secaoAcessos(c) {
    const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
    const form = el("form", { class: "form-grade", novalidate: true },
      el("label", { class: "campo" }, "Nome de quem vai usar", el("input", { name: "nome", autocomplete: "off", required: true })),
      el("label", { class: "campo" }, "E-mail", el("input", { name: "email", type: "email", autocomplete: "off", required: true })),
      el("div", { style: "display:flex;align-items:flex-end" }, el("button", { class: "botao", type: "submit", style: "width:100%" }, "Criar acesso")),
    );
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(form));
      if (!d.nome.trim() || !d.email.trim()) { $erro.textContent = "Preencha o nome e o e-mail."; $erro.hidden = false; return; }
      await gerarAcesso(c.id, d.nome, d.email, form.querySelector("button"), $erro);
    });

    const lista = estado.acessos.map((a) => el("div", { class: "linha-acesso" },
      el("span", {}, el("strong", { style: "display:block" }, a.nome), el("span", { class: "sub2", style: "font-size:13px" }, a.email)),
      el("span", { style: "display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end" },
        a.aguardando_primeiro_acesso ? el("span", { class: "selo selo-amarelo" }, "Aguardando 1º acesso") : el("span", { class: "selo selo-verde" }, "Ativo"),
        el("button", {
          class: "botao botao-texto", type: "button",
          onclick: (ev) => {
            if (window.confirm(`Gerar uma nova senha provisória para ${a.email}? A senha atual deixa de funcionar.`)) {
              gerarAcesso(c.id, a.nome, a.email, ev.currentTarget, $erro);
            }
          },
        }, "Redefinir senha"))));

    return el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:14px" },
      el("div", {},
        el("h2", { class: "titulo" }, "Acesso da empresa ao app"),
        el("p", { class: "sub2", style: "margin-top:4px" },
          "Crie o login de quem vai emitir as notas. A empresa só enxerga os próprios dados.")),
      estado.acessoCriado && el("div", { class: "aviso aviso-info", style: "flex-direction:column;align-items:stretch;gap:10px" },
        el("strong", {}, `Acesso pronto para ${estado.acessoCriado.email}`),
        el("span", {}, "Senha provisória (aparece só agora; no primeiro acesso a pessoa cria a própria senha):"),
        el("div", { class: "senha-gerada" }, estado.acessoCriado.senha_provisoria),
        el("button", {
          class: "botao botao-secundario", type: "button",
          onclick: async () => {
            const texto = `Seu acesso ao Emitta:\n${location.origin}/entrar\nE-mail: ${estado.acessoCriado.email}\nSenha provisória: ${estado.acessoCriado.senha_provisoria}`;
            try { await navigator.clipboard.writeText(texto); avisar("Copiado. Envie para a empresa por um canal privado."); }
            catch { avisar("Não foi possível copiar. Selecione a senha e copie manualmente."); }
          },
        }, "Copiar instruções para enviar")),
      $erro,
      lista.length ? el("div", {}, ...lista) : null,
      form,
    );
  }

  async function gerarAcesso(clienteId, nome, email, botao, $erro) {
    botao.disabled = true;
    $erro.hidden = true;
    try {
      const r = await api("POST", `/contador/clientes/${clienteId}/acessos`, { nome, email });
      estado.acessos = await api("GET", `/contador/clientes/${clienteId}/acessos`);
      estado.acessoCriado = r;
      desenharPrincipal();
    } catch (erro) {
      $erro.textContent = erro.message;
      $erro.hidden = false;
      botao.disabled = false;
    }
  }

  // ------------------------------------------------------------ segurança da conta

  function abrirSeguranca() {
    if (!confirmarSaida()) return;
    estado.modo = "seguranca";
    estado.selecionado = null;
    estado.segredo2fa = null;
    desenharLista();
    desenharPrincipal();
    mostrarPrincipalNoCelular();
  }

  function formSimples(campos, textoBotao, enviar, classeBotao = "botao") {
    const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
    const botao = el("button", { class: classeBotao, type: "submit" }, textoBotao);
    const form = el("form", { novalidate: true, style: "display:flex;flex-direction:column;gap:12px;max-width:420px" }, $erro, ...campos, botao);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      $erro.hidden = true;
      botao.disabled = true;
      try {
        await enviar(Object.fromEntries(new FormData(form)), form);
      } catch (erro) {
        $erro.textContent = erro.message;
        $erro.hidden = false;
        botao.disabled = false;
      }
    });
    return form;
  }

  const entradaSenha = (rotulo, nome, ac) =>
    el("label", { class: "campo" }, rotulo, el("input", { type: "password", name: nome, autocomplete: ac, required: true }));

  function telaSeguranca() {
    const eu = estado.eu;
    const troca = formSimples(
      [entradaSenha("Senha atual", "atual", "current-password"), entradaSenha("Nova senha", "nova", "new-password"),
        el("span", { class: "ajuda-pequena sub2", style: "font-size:12px" }, "Mínimo de 10 caracteres. Ao trocar, as outras sessões abertas são encerradas."),
        entradaSenha("Repita a nova senha", "repetir", "new-password")],
      "Trocar senha",
      async (d, form) => {
        if (d.nova !== d.repetir) throw new Error("As duas senhas não são iguais.");
        await api("POST", "/auth/senha", { atual: d.atual, nova: d.nova });
        form.reset();
        form.querySelector("button").disabled = false;
        avisar("Senha trocada. As outras sessões foram encerradas.");
      },
    );

    let blocoDoisFatores;
    if (eu.dois_fatores) {
      blocoDoisFatores = [
        el("div", { class: "aviso aviso-info" }, icone("escudo"), "Ativa. Ao entrar, além da senha, é pedido o código do aplicativo autenticador."),
        el("details", {}, el("summary", { style: "cursor:pointer;font-size:14px;color:var(--texto-2)" }, "Desativar a verificação em duas etapas"),
          formSimples([entradaSenha("Confirme com a sua senha", "senha", "current-password")], "Desativar", async (d) => {
            estado.eu = await api("POST", "/auth/2fa/desativar", { senha: d.senha });
            avisar("Verificação em duas etapas desativada.");
            desenharPrincipal();
          }, "botao botao-perigo")),
      ];
    } else if (estado.segredo2fa) {
      const grupos = estado.segredo2fa.segredo.match(/.{1,4}/g).join(" ");
      blocoDoisFatores = [
        el("ol", { class: "passos-2fa" },
          el("li", {}, "Instale no celular um aplicativo autenticador: Google Authenticator, Microsoft Authenticator ou Authy."),
          el("li", {}, "No aplicativo, toque em \"+\" e escolha \"Inserir chave de configuração\" (ou \"Digitar chave\")."),
          el("li", {}, "Em nome da conta, escreva Emitta. Em chave, digite o código abaixo, do tipo \"baseado em tempo\"."),
          el("li", {}, "Digite aqui o código de 6 dígitos que o aplicativo mostrar.")),
        el("div", { class: "segredo", "aria-label": "Chave de configuração" }, grupos),
        formSimples([el("label", { class: "campo" }, "Código de 6 dígitos",
          el("input", { name: "codigo", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", required: true }))],
        "Ativar", async (d) => {
          estado.eu = await api("POST", "/auth/2fa/ativar", { codigo: d.codigo });
          estado.segredo2fa = null;
          avisar("Pronto! A verificação em duas etapas está ativa.");
          desenharPrincipal();
        }),
      ];
    } else {
      blocoDoisFatores = [
        el("div", { class: "aviso aviso-alerta" }, icone("alerta"),
          "Recomendado para contadores: quem tiver só a sua senha não consegue entrar sem o código do seu celular."),
        el("div", {}, el("button", {
          class: "botao", type: "button",
          onclick: async (e) => {
            e.currentTarget.disabled = true;
            try { estado.segredo2fa = await api("POST", "/auth/2fa/iniciar"); desenharPrincipal(); }
            catch (erro) { avisar(erro.message); e.currentTarget.disabled = false; }
          },
        }, icone("escudo", 18), "Ativar verificação em duas etapas")),
      ];
    }

    return [
      el("section", { class: "card cabecalho-cliente" },
        el("div", {}, el("h1", {}, "Segurança da conta"), el("p", { class: "sub" }, `${eu.nome} · ${eu.email}`))),
      el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:14px" },
        el("h2", { class: "titulo" }, "Verificação em duas etapas"), ...blocoDoisFatores),
      el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:14px" },
        el("h2", { class: "titulo" }, "Trocar senha"), troca),
    ];
  }

  // ------------------------------------------------------------ início

  (async () => {
    try {
      estado.eu = await exigirLogin("contador");
      document.getElementById("topo-acoes").append(
        el("span", { class: "quem" }, estado.eu.nome),
        el("button", { class: "topo-botao", type: "button", onclick: abrirSeguranca }, icone("escudo", 16), "Segurança"),
        el("button", { class: "topo-botao", type: "button", onclick: () => { if (confirmarSaida()) { estado.alterado = false; sair(); } } }, icone("sair", 16), "Sair"),
      );
      const status = await api("GET", "/status");
      const selo = document.getElementById("selo-ambiente");
      if (status.ambiente === "simulacao") selo.textContent = "Simulação · sem valor fiscal";
      else if (status.ambiente === "homologacao") selo.textContent = "Homologação";
      else { selo.textContent = "Produção"; selo.className = "selo selo-verde"; }

      await carregarClientes();
      if (autonomo()) {
        // MEI/autônomo: só a própria empresa. Sem empresa ainda, abre o cadastro.
        document.body.classList.add("modo-autonomo");
        document.title = "Emitta · Ajustes da minha empresa";
        const sub = document.querySelector(".marca-sub");
        if (sub) sub.textContent = "Ajustes da minha empresa";
        if (estado.clientes.length) await abrirCliente(estado.clientes[0].id);
        else { estado.modo = "nova"; desenharPrincipal(); }
      } else {
        const ultimo = parseInt(ler("emitta.painel.cliente"), 10);
        desenharLista();
        if (estado.clientes.some((c) => c.id === ultimo)) await abrirCliente(ultimo);
        else { estado.modo = "vazio"; desenharPrincipal(); }
      }
      if (!estado.eu.dois_fatores && !ler("emitta.aviso2fa")) {
        guardar("emitta.aviso2fa", "1");
        avisar("Dica: ative a verificação em duas etapas em \"Segurança\".");
      }
    } catch (erro) {
      estado.modo = "vazio";
      desenharLista();
      desenharPrincipal();
      avisar(erro.message);
    }
  })();
})();
