// Painel do contador: empresas, serviços liberados e notas.
(() => {
  const { api, el, dinheiro, dataHora, formatarDocumento, seloSituacao, avisar, icone, guardar, ler, sair, exigirLogin } = Emitta;

  const estado = {
    clientes: [],
    selecionado: null, // id
    servicos: [], // catálogo com "liberado" e "apelido"
    notas: [],
    alterado: false,
    acessos: [],
    acessoCriado: null, // {email, senha_provisoria} mostrado uma única vez
    modo: "carregando", // carregando | cliente | nova | vazio | seguranca
    busca: "",
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

  // ------------------------------------------------------------ dados

  async function carregarClientes() {
    estado.clientes = await api("GET", "/contador/clientes");
  }

  async function abrirCliente(id) {
    if (!confirmarSaida()) return;
    estado.selecionado = id;
    estado.modo = "carregando";
    estado.alterado = false;
    guardar("emitta.painel.cliente", String(id));
    desenharLista();
    desenharPrincipal();
    try {
      const [servicos, notas, acessos] = await Promise.all([
        api("GET", `/contador/clientes/${id}/servicos`),
        api("GET", `/contador/clientes/${id}/notas`),
        api("GET", `/contador/clientes/${id}/acessos`),
      ]);
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
      .map((s) => ({ codigo: s.codigo, apelido: (s.apelido || "").trim() || s.descricao }));
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
    for (const c of filtrados) {
      const qtd = c.servicos_liberados;
      $lista.append(
        el("button", {
          class: "item-cliente", type: "button",
          "aria-current": c.id === estado.selecionado ? "true" : "false",
          onclick: () => abrirCliente(c.id).then(mostrarPrincipalNoCelular),
        },
          el("span", { class: "nome" }, c.razao_social),
          el("span", { class: "info" },
            `${c.municipio_nome} · ${qtd === 0 ? "nenhum serviço liberado" : qtd === 1 ? "1 serviço" : qtd + " serviços"}`),
        ),
      );
    }
  }

  // ------------------------------------------------------------ área principal

  function desenharPrincipal() {
    $principal.replaceChildren();
    if (estado.modo === "carregando") {
      $principal.append(el("div", { class: "card", style: "display:grid;place-items:center;padding:48px" },
        el("div", { class: "carregando", role: "img", "aria-label": "Carregando" })));
    } else if (estado.modo === "nova") {
      $principal.append(formularioNovaEmpresa());
    } else if (estado.modo === "cliente") {
      $principal.append(...telaCliente());
    } else if (estado.modo === "seguranca") {
      $principal.append(...telaSeguranca());
    } else {
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

  function telaCliente() {
    const c = estado.clientes.find((x) => x.id === estado.selecionado);
    const liberados = estado.servicos.filter((s) => s.liberado);

    const cabecalho = el("section", { class: "card cabecalho-cliente" },
      el("div", {},
        el("h1", {}, c.razao_social),
        el("p", { class: "sub" }, `CNPJ ${formatarDocumento(c.cnpj)} · ${c.municipio_nome} · Simples Nacional`)),
      el("a", { class: "botao botao-secundario", href: `/app?empresa=${c.id}` }, "Ver como o cliente vê"),
    );

    // Serviços
    const listaServicos = estado.servicos.map((s) => {
      const caixa = el("input", {
        type: "checkbox", checked: s.liberado,
        "aria-label": `Liberar ${s.descricao}`,
        onchange: (e) => {
          s.liberado = e.target.checked;
          estado.alterado = true;
          desenharPrincipal();
        },
      });
      const apelido = el("input", {
        class: "apelido", value: s.apelido, "aria-label": `Nome que o cliente vê para ${s.descricao}`,
        oninput: (e) => { s.apelido = e.target.value; estado.alterado = true; atualizarPrevia(); },
      });
      return el("label", { class: "servico" + (s.liberado ? " ligado" : "") },
        caixa,
        el("span", { class: "textos" },
          s.liberado ? apelido : el("span", { style: "font-weight:600" }, s.apelido),
          el("span", { class: "oficial" }, `Código ${s.subitem || s.codigo} · ${s.descricao}`)),
        el("span", { class: s.liberado ? "selo selo-verde" : "selo selo-cinza" }, s.liberado ? "Liberado" : "Bloqueado"),
      );
    });

    const colServicos = el("section", { class: "card col-servicos" },
      el("div", {},
        el("h2", { class: "titulo" }, "Serviços liberados para emitir"),
        el("p", { class: "sub2", style: "margin-top:4px" },
          "Só os serviços marcados aparecem no app do cliente. Clique no nome para trocar pelo nome que ele entende.")),
      ...listaServicos,
    );

    // Prévia + regras + salvar
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

    const regras = el("section", { class: "card regras" },
      el("h2", { class: "titulo" }, "Regras da empresa"),
      el("div", { class: "linha" }, el("span", {}, "Alíquota de ISS"), el("strong", {}, `${String(c.aliquota_iss).replace(".", ",")}%`)),
      el("div", { class: "linha" }, el("span", {}, "Prazo para cancelar"),
        el("strong", {}, c.prazo_cancelamento_dias ? `${c.prazo_cancelamento_dias} dias` : "Definido pela prefeitura")),
    );

    const botaoSalvar = el("button", {
      class: "botao botao-grande", type: "button", disabled: !estado.alterado,
      onclick: (e) => salvarServicos(e.currentTarget),
    }, estado.alterado ? "Salvar e enviar para o app" : "Tudo salvo");

    const colLado = el("div", { class: "col-lado" }, previa, botaoSalvar, regras);

    // Notas
    const notas = el("section", { class: "card", style: "padding:20px 24px;display:flex;flex-direction:column;gap:12px" },
      el("h2", { class: "titulo" }, "Notas desta empresa"),
      estado.notas.length
        ? el("div", { class: "tabela-caixa" },
          el("table", {},
            el("thead", {}, el("tr", {},
              el("th", {}, "Nº"), el("th", {}, "Data"), el("th", {}, "Cliente"),
              el("th", {}, "Situação"), el("th", { style: "text-align:right" }, "Valor"))),
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
            )))))
        : el("p", { class: "vazio" }, "Esta empresa ainda não emitiu notas."),
    );

    return [cabecalho, el("div", { class: "colunas" }, colServicos, colLado), secaoAcessos(c), notas];
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

    const form = el("form", { class: "card", style: "padding:24px;display:flex;flex-direction:column;gap:18px", novalidate: true },
      el("div", {},
        el("h1", { style: "font-size:22px" }, "Nova empresa"),
        el("p", { class: "sub2", style: "margin-top:4px" }, "Depois de cadastrar, você escolhe os serviços que ela pode emitir.")),
      $erro,
      el("div", { class: "form-grade" },
        campo("CNPJ", "cnpj", { required: true, inputmode: "numeric", placeholder: "00.000.000/0000-00", autocomplete: "off" }),
        campo("Razão social", "razao_social", { required: true }),
        campo("Município", "municipio_nome", { required: true, placeholder: "Ex.: São Paulo" }),
        campo("Código IBGE do município", "municipio_ibge", { required: true, inputmode: "numeric", maxlength: "7", placeholder: "7 dígitos" },
          "Ex.: São Paulo é 3550308"),
        campo("Alíquota de ISS (%)", "aliquota_iss", { required: true, inputmode: "decimal", placeholder: "Ex.: 3" }),
        campo("Prazo para cancelar (dias)", "prazo_cancelamento_dias", { inputmode: "numeric", placeholder: "Opcional" },
          "Deixe em branco se não souber"),
      ),
      el("div", { class: "acoes" },
        el("button", { class: "botao botao-secundario", type: "button", onclick: () => { estado.modo = estado.selecionado ? "cliente" : "vazio"; desenharPrincipal(); } }, "Cancelar"),
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
      };
      const botao = form.querySelector("[type=submit]");
      botao.disabled = true;
      try {
        const novo = await api("POST", "/contador/clientes", corpo);
        await carregarClientes();
        avisar("Empresa cadastrada. Agora libere os serviços.");
        await abrirCliente(novo.id);
      } catch (erro) {
        $erro.textContent = erro.message;
        $erro.hidden = false;
        botao.disabled = false;
      }
    });
    setTimeout(() => form.querySelector("input").focus(), 0);
    return form;
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
      const ultimo = parseInt(ler("emitta.painel.cliente"), 10);
      desenharLista();
      if (estado.clientes.some((c) => c.id === ultimo)) await abrirCliente(ultimo);
      else { estado.modo = "vazio"; desenharPrincipal(); }
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
