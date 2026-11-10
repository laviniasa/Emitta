// Administração da plataforma: acompanhar quem entra e sai e ajudar com contas.
// Não mostra notas nem certificados de ninguém (acesso mínimo).
(() => {
  const { api, el, icone, avisar, dataHora, sair } = Emitta;
  const $principal = document.getElementById("principal");
  const $topo = document.getElementById("topo-acoes");

  const OCIOSO_MS = 30 * 60 * 1000; // igual ao servidor
  const estado = { eu: null, aba: "atividades", contas: [], eventos: [], filtro: "todos", conta: "", segredo: null };

  const NOMES = {
    entrou: "Entrou",
    saiu: "Saiu",
    senha_errada: "Senha errada",
    bloqueio_por_tentativas: "Bloqueada por tentativas",
    codigo_2fa_errado: "Código de verificação errado",
    conta_desativada_tentou_entrar: "Conta desativada tentou entrar",
    instalacao_recusada: "Tentativa de instalação recusada",
    administracao_criada: "Administração criada",
    conta_contador_criada: "Contador criou a conta",
    contador_pediu_acesso: "Contador pediu conta (aguardando aprovação)",
    conta_pendente_tentou_entrar: "Conta aguardando aprovação tentou entrar",
    admin_aprovou_conta: "Administração aprovou conta",
    admin_recusou_conta: "Administração recusou pedido de conta",
    senha_trocada: "Trocou a senha",
    duas_etapas_ativada: "Ativou a verificação em duas etapas",
    duas_etapas_desativada: "Desativou a verificação em duas etapas",
    empresa_cadastrada: "Cadastrou empresa",
    acesso_empresa_criado: "Criou/redefiniu acesso de empresa",
    certificado_enviado: "Enviou certificado",
    certificado_removido: "Removeu certificado",
    nota_emitida: "Emitiu nota",
    nota_cancelada: "Cancelou nota",
    admin_gerou_senha_provisoria: "Administração gerou senha provisória",
    admin_desbloqueou: "Administração desbloqueou conta",
    admin_desativou_conta: "Administração desativou conta",
    admin_reativou_conta: "Administração reativou conta",
    admin_desconectou_conta: "Administração desconectou conta",
    admin_removeu_duas_etapas: "Administração removeu verificação em duas etapas",
  };
  const ALERTAS = new Set(["senha_errada", "bloqueio_por_tentativas", "codigo_2fa_errado", "conta_desativada_tentou_entrar", "instalacao_recusada"]);
  const FILTROS = {
    todos: ["Tudo", () => true],
    acessos: ["Entradas e saídas", (t) => t === "entrou" || t === "saiu"],
    alertas: ["Tentativas suspeitas", (t) => ALERTAS.has(t)],
    contas: ["Contas e senhas", (t) => /conta|senha|duas_etapas|acesso_empresa|administracao/.test(t) && !ALERTAS.has(t)],
    admin: ["Ações da administração", (t) => t.startsWith("admin_")],
  };

  // ------------------------------------------------------------ utilidades

  function formulario(campos, textoBotao, enviar, classeBotao = "botao botao-grande") {
    const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
    const botao = el("button", { class: classeBotao, type: "submit" }, textoBotao);
    const form = el("form", { novalidate: true }, $erro, ...campos, botao);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      $erro.hidden = true;
      const vazio = [...form.querySelectorAll("input[required]")].find((i) => !i.value.trim());
      if (vazio) { $erro.textContent = "Preencha todos os campos."; $erro.hidden = false; vazio.focus(); return; }
      botao.disabled = true;
      try { await enviar(Object.fromEntries(new FormData(form))); }
      catch (erro) { $erro.textContent = erro.message; $erro.hidden = false; botao.disabled = false; }
    });
    return form;
  }

  const campo = (rotulo, atributos) => el("label", { class: "campo" }, rotulo, el("input", { required: true, ...atributos }));
  const carregando = () => el("div", { style: "display:grid;place-items:center;padding:40px" }, el("div", { class: "carregando", role: "img", "aria-label": "Carregando" }));

  function topo() {
    $topo.replaceChildren();
    if (!estado.eu) return;
    $topo.append(
      el("span", { class: "quem" }, estado.eu.nome),
      el("button", { class: "topo-botao", type: "button", onclick: sair }, icone("sair", 18), "Sair"),
    );
  }

  // Sai sozinho depois de 30 minutos sem mexer (o servidor também corta).
  function vigiarInatividade() {
    let timer;
    const reiniciar = () => { clearTimeout(timer); timer = setTimeout(sair, OCIOSO_MS); };
    ["click", "keydown", "pointerdown", "scroll"].forEach((ev) => document.addEventListener(ev, reiniciar, { passive: true }));
    reiniciar();
  }

  // ------------------------------------------------------------ primeira vez

  function telaInstalar() {
    $principal.replaceChildren(el("section", { class: "card bloco estreito" },
      el("h1", {}, "Criar a conta de administração"),
      el("p", { class: "sub" }, "Só funciona uma vez, com o código de instalação do servidor. Depois disso esta tela some."),
      formulario([
        campo("Código de instalação", { name: "codigo", autocomplete: "off" }),
        campo("Seu nome", { name: "nome", autocomplete: "name" }),
        campo("E-mail", { name: "email", type: "email", autocomplete: "username" }),
        campo("Senha (mínimo de 10 caracteres)", { name: "senha", type: "password", autocomplete: "new-password" }),
        campo("Repita a senha", { name: "repetir", type: "password", autocomplete: "new-password" }),
      ], "Criar e continuar", async (d) => {
        if (d.senha !== d.repetir) throw new Error("As duas senhas não são iguais.");
        const r = await api("POST", "/auth/instalacao", { codigo: d.codigo, nome: d.nome, email: d.email, senha: d.senha }, { semRedirecionar: true });
        estado.eu = r.usuario;
        iniciar();
      })));
  }

  function telaDuasEtapas() {
    topo();
    const corpo = [];
    if (!estado.segredo) {
      corpo.push(
        el("p", { class: "sub" }, "A administração só abre com a verificação em duas etapas ligada. Assim, mesmo que alguém descubra a sua senha, não entra sem o código do seu celular."),
        el("button", { class: "botao botao-grande", type: "button", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { estado.segredo = await api("POST", "/auth/2fa/iniciar"); telaDuasEtapas(); }
          catch (erro) { avisar(erro.message); e.currentTarget.disabled = false; }
        } }, icone("escudo", 18), "Configurar agora"));
    } else {
      corpo.push(
        el("ol", { class: "passos" },
          el("li", {}, "Instale no celular o Google Authenticator, Microsoft Authenticator ou Authy."),
          el("li", {}, "Toque em \"+\" e escolha \"Inserir chave de configuração\"."),
          el("li", {}, "Nome da conta: Emitta Admin. Chave: o código abaixo, do tipo \"baseado em tempo\"."),
          el("li", {}, "Digite o código de 6 dígitos que aparecer.")),
        el("div", { class: "segredo", "aria-label": "Chave de configuração" }, estado.segredo.segredo.match(/.{1,4}/g).join(" ")),
        el("a", { href: estado.segredo.uri, class: "botao botao-secundario" }, "Abrir no aplicativo autenticador (pelo celular)"),
        formulario([campo("Código de 6 dígitos", { name: "codigo", class: "codigo", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6" })],
          "Ativar e entrar", async (d) => {
            estado.eu = await api("POST", "/auth/2fa/ativar", { codigo: d.codigo });
            estado.segredo = null;
            avisar("Verificação em duas etapas ativada.");
            iniciar();
          }));
    }
    $principal.replaceChildren(el("section", { class: "card bloco estreito" },
      el("h1", {}, "Proteja a administração"), ...corpo));
  }

  // ------------------------------------------------------------ telas principais

  async function carregar() {
    const [contas, eventos] = await Promise.all([
      api("GET", "/admin/contas"),
      api("GET", "/admin/atividades?limite=500" + (estado.conta ? `&usuario_id=${estado.conta}` : "")),
    ]);
    estado.contas = contas;
    estado.eventos = eventos;
  }

  function abas() {
    const aba = (id, texto) => el("button", {
      class: "aba", type: "button", role: "tab", "aria-selected": String(estado.aba === id),
      onclick: () => { estado.aba = id; desenhar(); },
    }, texto);
    const pendentes = estado.contas.filter((c) => c.aguardando_aprovacao).length;
    return el("div", { class: "abas", role: "tablist" }, aba("atividades", "Atividades"),
      aba("contas", pendentes ? `Contas · ${pendentes} aguardando` : "Contas"), aba("eu", "Minha conta"));
  }

  function resumo() {
    const hoje = new Date().toISOString().slice(0, 10);
    const deHoje = estado.eventos.filter((e) => (e.quando || "").startsWith(hoje));
    const n = (texto, valor) => el("div", { class: "card numero" }, el("strong", {}, String(valor)), el("span", {}, texto));
    const pendentes = estado.contas.filter((c) => c.aguardando_aprovacao).length;
    return el("div", { class: "resumo" },
      pendentes ? el("button", { class: "card numero pendente", type: "button", onclick: () => { estado.aba = "contas"; desenhar(); } },
        el("strong", {}, String(pendentes)), el("span", {}, "Aguardando aprovação →")) : null,
      n("Contadores", estado.contas.filter((c) => c.papel === "contador" && !c.aguardando_aprovacao).length),
      n("Acessos de empresas", estado.contas.filter((c) => c.papel === "empresa").length),
      n("Entradas hoje", deHoje.filter((e) => e.tipo === "entrou").length),
      n("Tentativas suspeitas hoje", deHoje.filter((e) => ALERTAS.has(e.tipo)).length));
  }

  function telaAtividades() {
    const filtro = el("select", { onchange: (e) => { estado.filtro = e.target.value; desenhar(); } },
      ...Object.entries(FILTROS).map(([id, [nome]]) => el("option", { value: id, selected: estado.filtro === id }, nome)));
    const pessoa = el("select", { onchange: async (e) => { estado.conta = e.target.value; await recarregar(); } },
      el("option", { value: "" }, "Todas as contas"),
      ...estado.contas.map((c) => el("option", { value: String(c.id), selected: String(c.id) === estado.conta }, `${c.nome} (${c.papel_nome})`)));
    const lista = estado.eventos.filter((e) => FILTROS[estado.filtro][1](e.tipo));
    const linhas = lista.map((e) => {
      const classe = ALERTAS.has(e.tipo) ? "tipo-alerta" : e.tipo.startsWith("admin_") ? "tipo-admin" : "";
      return el("tr", {},
        el("td", { class: "quando" }, dataHora(e.quando)),
        el("td", {}, e.email || "—"),
        el("td", { class: classe }, NOMES[e.tipo] || e.tipo),
        el("td", {}, e.detalhe || ""),
        el("td", { class: "ip" }, e.ip || ""));
    });
    return [
      resumo(),
      el("section", { class: "card bloco" },
        el("div", { style: "display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center" },
          el("h2", {}, "Quem entrou, saiu e o que fez"),
          el("button", { class: "botao botao-secundario", type: "button", onclick: recarregar }, icone("trocar", 16), "Atualizar")),
        el("div", { class: "filtros" },
          el("label", { class: "campo" }, "Mostrar", filtro),
          el("label", { class: "campo" }, "Conta", pessoa)),
        lista.length
          ? el("div", { class: "tabela-caixa" }, el("table", {},
              el("thead", {}, el("tr", {}, ...["Quando", "Conta", "O que aconteceu", "Detalhe", "IP"].map((t) => el("th", {}, t)))),
              el("tbody", {}, ...linhas)))
          : el("p", { class: "vazio" }, "Nada por aqui ainda.")),
    ];
  }

  async function acao(conta, caminho, confirmacao, sucesso) {
    if (confirmacao && !(await confirmar(confirmacao))) return;
    try {
      const r = await api("POST", `/admin/contas/${conta.id}/${caminho}`);
      if (r.senha_provisoria) return mostrarSenha(conta, r.senha_provisoria);
      avisar(sucesso);
      await recarregar();
    } catch (erro) { avisar(erro.message); }
  }

  // Confirmação dentro da página (sem janelas do navegador).
  function confirmar(texto) {
    return new Promise((resolver) => {
      const caixa = el("section", { class: "card bloco", role: "alertdialog", "aria-label": "Confirmar" },
        el("p", {}, texto),
        el("div", { style: "display:flex;gap:10px;flex-wrap:wrap" },
          el("button", { class: "botao", type: "button", onclick: () => { caixa.remove(); resolver(true); } }, "Confirmar"),
          el("button", { class: "botao botao-secundario", type: "button", onclick: () => { caixa.remove(); resolver(false); } }, "Voltar")));
      $principal.prepend(caixa);
      caixa.querySelector("button").focus();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  function mostrarSenha(conta, senha) {
    const caixa = el("section", { class: "card bloco", role: "alert" },
      el("h2", {}, `Senha provisória de ${conta.nome}`),
      el("div", { class: "senha-gerada" }, senha),
      el("p", { class: "sub" }, `Passe para ${conta.email} por um canal seguro (de preferência falando ou por mensagem que você apaga depois). A pessoa vai criar uma senha nova no primeiro acesso. Esta senha não aparece de novo.`),
      el("button", { class: "botao", type: "button", onclick: () => { caixa.remove(); recarregar(); } }, "Já anotei"));
    $principal.prepend(caixa);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function telaContas() {
    const pedidos = estado.contas.filter((c) => c.aguardando_aprovacao);
    const blocoPedidos = pedidos.length ? el("section", { class: "card bloco pedidos" },
      el("h2", {}, `Pedidos de conta (${pedidos.length})`),
      el("p", { class: "sub" }, "Contadores que criaram conta e esperam a sua liberação. Antes de aprovar, confirme que você conhece a pessoa."),
      el("div", {}, ...pedidos.map(linhaPedido))) : null;
    const grupos = [["contador", "Contadores"], ["empresa", "Acessos de empresas"], ["admin", "Administração"]];
    return [blocoPedidos, ...grupos.map(([papel, titulo]) => {
      const contas = estado.contas.filter((c) => c.papel === papel && !c.aguardando_aprovacao);
      return el("section", { class: "card bloco" }, el("h2", {}, `${titulo} (${contas.length})`),
        contas.length ? el("div", {}, ...contas.map(linhaConta)) : el("p", { class: "vazio" }, "Nenhuma conta."));
    })];
  }

  function linhaPedido(c) {
    return el("div", { class: "conta" },
      el("div", { class: "info" },
        el("span", { class: "nome" }, c.nome),
        el("span", { class: "detalhes" }, c.email),
        el("span", { class: "detalhes" }, `Pedido em ${dataHora(c.criado_em)}`),
        el("div", { class: "selos" }, el("span", { class: "selo selo-amarelo" }, "Aguardando aprovação"))),
      el("div", { class: "acoes" },
        el("button", { class: "botao", type: "button",
          onclick: () => acao(c, "aprovar", `Aprovar a conta de ${c.nome} (${c.email})? A pessoa passa a poder entrar e cadastrar empresas.`, "Conta aprovada. A pessoa já pode entrar.") },
          icone("certo", 16), "Aprovar"),
        el("button", { class: "botao botao-secundario", type: "button",
          onclick: () => acao(c, "recusar", `Recusar o pedido de ${c.nome} (${c.email})? O pedido é apagado. O histórico continua em Atividades.`, "Pedido recusado.") },
          icone("x", 16), "Recusar")));
  }

  function linhaConta(c) {
    const eu = c.id === estado.eu.id;
    const selos = [];
    if (!c.ativo) selos.push(el("span", { class: "selo selo-vermelho" }, "Desativada"));
    else if (c.bloqueada) selos.push(el("span", { class: "selo selo-vermelho" }, "Bloqueada por tentativas"));
    else selos.push(el("span", { class: "selo selo-verde" }, "Ativa"));
    if (c.aguardando_primeiro_acesso) selos.push(el("span", { class: "selo selo-amarelo" }, "Aguardando primeiro acesso"));
    if (c.dois_fatores) selos.push(el("span", { class: "selo selo-cinza" }, "Duas etapas"));
    const detalhes = [
      c.empresa && `Empresa: ${c.empresa}`,
      c.contador && `Contador: ${c.contador}`,
      c.empresas_cadastradas != null && `${c.empresas_cadastradas} empresa(s)`,
      `Último acesso: ${c.ultimo_acesso ? dataHora(c.ultimo_acesso) : "nunca"}`,
    ].filter(Boolean).join(" · ");

    const botoes = [];
    if (!eu) {
      botoes.push(el("button", { class: "botao botao-secundario", type: "button",
        onclick: () => acao(c, "senha-provisoria", `Gerar uma senha provisória para ${c.nome}? A senha atual deixa de funcionar e a pessoa é desconectada.`) },
        icone("chave", 16), "Senha provisória"));
      if (c.bloqueada) botoes.push(el("button", { class: "botao botao-secundario", type: "button",
        onclick: () => acao(c, "desbloquear", null, "Conta desbloqueada.") }, "Desbloquear"));
      if (c.dois_fatores && c.papel !== "admin") botoes.push(el("button", { class: "botao botao-secundario", type: "button",
        onclick: () => acao(c, "remover-2fa", `Remover a verificação em duas etapas de ${c.nome}? Faça isso só se a pessoa perdeu o celular e você confirmou que é ela.`, "Verificação em duas etapas removida.") },
        "Remover duas etapas"));
      botoes.push(el("button", { class: "botao botao-secundario", type: "button",
        onclick: () => acao(c, "desconectar", `Desconectar ${c.nome} de todos os aparelhos?`, "Desconectada de todos os aparelhos.") },
        icone("sair", 16), "Desconectar"));
      botoes.push(c.ativo
        ? el("button", { class: "botao botao-perigo", type: "button",
            onclick: () => acao(c, "desativar", `Desativar a conta de ${c.nome}? Ela não consegue mais entrar até você reativar. Nada é apagado.`, "Conta desativada.") }, "Desativar")
        : el("button", { class: "botao", type: "button", onclick: () => acao(c, "reativar", null, "Conta reativada.") }, "Reativar"));
    }
    botoes.push(el("button", { class: "botao botao-texto", type: "button",
      onclick: async () => { estado.conta = String(c.id); estado.aba = "atividades"; estado.filtro = "todos"; await recarregar(); } },
      "Ver atividade"));

    return el("div", { class: "conta" },
      el("div", { class: "info" },
        el("span", { class: "nome" }, c.nome, eu ? " (você)" : ""),
        el("span", { class: "detalhes" }, c.email),
        el("span", { class: "detalhes" }, detalhes),
        el("div", { class: "selos" }, ...selos)),
      el("div", { class: "acoes" }, ...botoes));
  }

  function telaEu() {
    return [el("section", { class: "card bloco estreito" },
      el("h2", {}, "Trocar a minha senha"),
      el("p", { class: "sub" }, "Trocar a senha desconecta os outros aparelhos."),
      formulario([
        campo("Senha atual", { name: "atual", type: "password", autocomplete: "current-password" }),
        campo("Nova senha (mínimo de 10 caracteres)", { name: "nova", type: "password", autocomplete: "new-password" }),
        campo("Repita a nova senha", { name: "repetir", type: "password", autocomplete: "new-password" }),
      ], "Salvar nova senha", async (d) => {
        if (d.nova !== d.repetir) throw new Error("As duas senhas não são iguais.");
        await api("POST", "/auth/senha", { atual: d.atual, nova: d.nova });
        avisar("Senha trocada.");
        desenhar();
      }, "botao")),
      el("section", { class: "card bloco estreito" },
        el("h2", {}, "Proteções desta área"),
        el("ul", { class: "passos" },
          el("li", {}, "Só abre com senha + código do celular (duas etapas obrigatória)."),
          el("li", {}, "Sai sozinha depois de 30 minutos sem uso."),
          el("li", {}, "Tudo o que você faz aqui fica registrado em Atividades."),
          el("li", {}, "Não mostra notas nem certificados das empresas.")))];
  }

  function desenhar() {
    topo();
    const conteudo = estado.aba === "contas" ? telaContas() : estado.aba === "eu" ? telaEu() : telaAtividades();
    $principal.replaceChildren(abas(), ...conteudo.filter(Boolean));
  }

  async function recarregar() {
    try { await carregar(); desenhar(); }
    catch (erro) { tratarErro(erro); }
  }

  function tratarErro(erro) {
    const d = erro.dados && erro.dados.detail;
    if (d && d.codigo === "admin_2fa") return telaDuasEtapas();
    $principal.replaceChildren(el("section", { class: "card bloco estreito" }, el("h1", {}, "Não foi possível carregar"), el("p", { class: "sub" }, erro.message)));
  }

  // ------------------------------------------------------------ início

  async function iniciar() {
    $principal.replaceChildren(carregando());
    try {
      if (!estado.eu) {
        estado.eu = await api("GET", "/auth/eu", null, { semRedirecionar: true }).catch((e) => { if (e.status === 401) return null; throw e; });
      }
      if (!estado.eu) {
        const s = await api("GET", "/auth/situacao", null, { semRedirecionar: true });
        if (s.precisa_instalar && s.instalacao_disponivel) return telaInstalar();
        location.href = "/entrar?volta=/admin";
        return;
      }
      if (estado.eu.trocar_senha) { location.href = "/entrar?volta=/admin"; return; }
      if (estado.eu.papel !== "admin") {
        $principal.replaceChildren(el("section", { class: "card bloco estreito" }, el("h1", {}, "Página não encontrada")));
        return;
      }
      if (!estado.eu.dois_fatores) return telaDuasEtapas();
      vigiarInatividade();
      await carregar();
      desenhar();
    } catch (erro) { tratarErro(erro); }
  }

  iniciar();
})();
