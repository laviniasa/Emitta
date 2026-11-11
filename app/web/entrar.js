// Tela de entrar: login, verificação em duas etapas, primeiro acesso e troca de senha.
(() => {
  const { api, el, icone } = Emitta;
  const $caixa = document.getElementById("caixa");
  document.getElementById("rodape").append(icone("cadeado", 16), "Conexão protegida. Sua senha nunca é guardada em texto puro.");

  const estado = { desafio: null, senhaAtual: "" };

  // Só aceita voltar para páginas deste próprio site.
  function destino(papel) {
    const volta = new URLSearchParams(location.search).get("volta") || "";
    const valido = volta.startsWith("/") && !volta.startsWith("//") && !volta.startsWith("/entrar");
    const area = { admin: "/admin", contador: "/escritorio" }[papel] || "/empresa";
    return valido && volta.startsWith(area) ? volta : area;
  }

  function campoSenha(rotulo, nome, autocomplete, extra = {}) {
    const input = el("input", { type: "password", name: nome, autocomplete, required: true, ...extra });
    const botao = el("button", { class: "ver-senha", type: "button", "aria-label": "Mostrar senha", "aria-pressed": "false" }, icone("olho"));
    botao.addEventListener("click", () => {
      const mostrar = input.type === "password";
      input.type = mostrar ? "text" : "password";
      botao.setAttribute("aria-pressed", String(mostrar));
      botao.setAttribute("aria-label", mostrar ? "Esconder senha" : "Mostrar senha");
    });
    const id = `senha-${nome}`;
    input.id = id;
    // O botão de mostrar fica fora do rótulo, para o nome do campo ser só o rótulo.
    return el("div", { class: "campo" }, el("label", { for: id }, rotulo), el("span", { class: "senha-caixa" }, input, botao));
  }

  let contadorIds = 0;
  // Rótulo + campo, com a ajuda FORA do rótulo (ligada por aria-describedby),
  // para o leitor de tela anunciar o nome do campo sem misturar com a dica.
  function campoComAjuda(rotulo, input, ...ajudas) {
    const id = `ajuda-${++contadorIds}`;
    input.setAttribute("aria-describedby", id);
    return el("div", { class: "campo" },
      el("label", { class: "campo" }, rotulo, input),
      el("div", { id, style: "display:flex;flex-direction:column;gap:6px" }, ...ajudas));
  }

  function medidorDeForca(input) {
    const barra = el("span");
    const texto = el("span", { class: "ajuda", "aria-live": "polite" }, "Mínimo de 10 caracteres. Uma frase curta é fácil de lembrar e difícil de adivinhar.");
    input.addEventListener("input", () => {
      const s = input.value;
      let pontos = 0;
      if (s.length >= 10) pontos++;
      if (s.length >= 14) pontos++;
      if (/[a-z]/.test(s) && /[A-Z]/.test(s)) pontos++;
      if (/\d/.test(s)) pontos++;
      if (/[^A-Za-z0-9]/.test(s)) pontos++;
      const nivel = s.length < 10 ? 0 : Math.min(pontos, 4);
      const cores = ["#B42318", "#B42318", "#B45309", "#1F7A50", "#16603E"];
      const nomes = ["Curta demais", "Fraca", "Razoável", "Boa", "Forte"];
      barra.style.width = `${Math.max(8, nivel * 25)}%`;
      barra.style.background = cores[nivel];
      texto.textContent = s ? nomes[nivel] : "Mínimo de 10 caracteres. Uma frase curta é fácil de lembrar e difícil de adivinhar.";
    });
    return [el("div", { class: "forca", "aria-hidden": "true" }, barra), texto];
  }

  function formulario(titulo, sub, campos, textoBotao, enviar) {
    const $erro = el("div", { class: "aviso aviso-erro", role: "alert", hidden: true });
    const botao = el("button", { class: "botao botao-grande", type: "submit" }, textoBotao);
    const form = el("form", { novalidate: true }, $erro, ...campos, botao);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      $erro.hidden = true;
      const dados = Object.fromEntries(new FormData(form));
      const vazio = [...form.querySelectorAll("input[required]")].find((i) => !i.value.trim());
      if (vazio) {
        $erro.textContent = "Preencha todos os campos.";
        $erro.hidden = false;
        vazio.focus();
        return;
      }
      botao.disabled = true;
      try {
        await enviar(dados);
      } catch (erro) {
        $erro.textContent = erro.message;
        $erro.hidden = false;
        botao.disabled = false;
      }
    });
    $caixa.replaceChildren(el("div", {}, el("h1", {}, titulo), sub && el("p", { class: "sub" }, sub)), form);
    setTimeout(() => form.querySelector("input")?.focus(), 0);
    return form;
  }

  // ------------------------------------------------------------ telas

  function voltarPara(fn) {
    return el("button", { type: "button", class: "botao-link", style: "align-self:flex-start", onclick: fn }, "← Voltar");
  }

  function telaEscolha() {
    const opcao = (titulo, texto, perfil) => el("button", {
      type: "button", class: "opcao-perfil", onclick: () => telaEntrar(perfil),
    }, el("strong", {}, titulo), el("span", {}, texto));
    $caixa.replaceChildren(
      el("div", {}, el("h1", {}, "Bem-vindo ao Emitta"), el("p", { class: "sub" }, "Como você vai usar o Emitta?")),
      opcao("Sou contador", "Cadastro as empresas e libero os serviços de cada uma.", "contador"),
      opcao("Sou empresa", "Emito e cancelo as notas da minha empresa.", "empresa"),
    );
  }

  function telaEntrar(perfil) {
    const ehEmpresa = perfil === "empresa";
    formulario(
      ehEmpresa ? "Entrar · Empresa" : perfil === "contador" ? "Entrar · Contador" : "Entrar",
      "Use o e-mail e a senha da sua conta.",
      [
        el("label", { class: "campo" }, "E-mail", el("input", { type: "email", name: "email", autocomplete: "username", inputmode: "email", required: true })),
        campoSenha("Senha", "senha", "current-password"),
      ],
      "Entrar",
      async (d) => {
        const r = await api("POST", "/auth/entrar", { email: d.email, senha: d.senha }, { semRedirecionar: true });
        estado.senhaAtual = d.senha;
        if (r.precisa_2fa) { estado.desafio = r.desafio; return telaCodigo(); }
        depoisDeEntrar(r.usuario);
      },
    );
    const extras = [];
    if (perfil === "contador") {
      extras.push(el("div", { class: "separador" }, "Ainda não tem conta?"),
        el("button", { type: "button", class: "botao botao-secundario botao-grande", onclick: telaCadastro }, "Criar conta de contador"),
        el("p", { class: "nota-pe" }, "Esqueceu a senha? Fale com o suporte do Emitta."));
    } else if (ehEmpresa) {
      extras.push(el("div", { class: "aviso aviso-info" }, icone("escudo"),
        "Seu acesso é criado pelo seu contador. Ele te passa o e-mail e uma senha provisória, e no primeiro acesso você cria a sua."),
        el("p", { class: "nota-pe" }, "Esqueceu a senha? Peça ao seu contador para redefinir o seu acesso."));
    }
    $caixa.prepend(voltarPara(telaEscolha));
    $caixa.append(...extras);
  }

  function telaCadastro() {
    const senha = el("input", { type: "password", name: "senha", autocomplete: "new-password", required: true });
    formulario(
      "Criar conta de contador", "Depois de enviar, a sua conta passa por uma aprovação do Emitta. Você vai ver só as empresas que cadastrar.",
      [
        el("label", { class: "campo" }, "Seu nome", el("input", { name: "nome", autocomplete: "name", maxlength: "120", required: true })),
        el("label", { class: "campo" }, "E-mail", el("input", { type: "email", name: "email", autocomplete: "username", inputmode: "email", required: true })),
        campoComAjuda("Senha", senha, ...medidorDeForca(senha)),
        campoSenha("Repita a senha", "repetir", "new-password"),
      ],
      "Enviar pedido de conta",
      async (d) => {
        if (d.senha !== d.repetir) throw new Error("As duas senhas não são iguais.");
        const r = await api("POST", "/auth/cadastro", { nome: d.nome, email: d.email, senha: d.senha }, { semRedirecionar: true });
        telaPedidoEnviado(r.email);
      },
    );
    $caixa.prepend(voltarPara(() => telaEntrar("contador")));
    $caixa.append(el("p", { class: "nota-pe" }, "Já tem conta? ",
      el("button", { type: "button", class: "botao-link", onclick: () => telaEntrar("contador") }, "Entrar")));
  }

  function telaPedidoEnviado(email) {
    $caixa.replaceChildren(
      el("div", { style: "width:56px;height:56px;border-radius:50%;background:var(--verde-claro);color:var(--verde);display:grid;place-items:center" }, icone("relogio", 28)),
      el("div", {}, el("h1", {}, "Pedido enviado!"),
        el("p", { class: "sub" }, `A sua conta (${email}) está aguardando aprovação do Emitta. Assim que for liberada, é só entrar com o e-mail e a senha que você criou.`)),
      el("button", { type: "button", class: "botao botao-secundario botao-grande", onclick: () => telaEntrar("contador") }, "Voltar para entrar"),
    );
  }

  function telaCodigo() {
    formulario(
      "Verificação em duas etapas", "Abra o aplicativo autenticador no celular e digite o código de 6 dígitos do Emitta.",
      [el("label", { class: "campo" }, "Código",
        el("input", { class: "codigo", name: "codigo", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", pattern: "[0-9]*", required: true }))],
      "Confirmar",
      async (d) => {
        const r = await api("POST", "/auth/2fa", { desafio: estado.desafio, codigo: d.codigo }, { semRedirecionar: true });
        depoisDeEntrar(r.usuario);
      },
    );
  }

  function telaTrocarSenha(usuario) {
    const nova = el("input", { type: "password", name: "nova", autocomplete: "new-password", required: true });
    const campoNova = campoComAjuda("Nova senha", nova, ...medidorDeForca(nova));
    const campos = [];
    if (!estado.senhaAtual) campos.push(campoSenha("Senha provisória", "atual", "current-password"));
    campos.push(campoNova, campoSenha("Repita a nova senha", "repetir", "new-password"));
    formulario(
      `Olá, ${usuario.nome.split(" ")[0]}!`, "Este é o seu primeiro acesso. Crie uma senha só sua para continuar.",
      campos, "Salvar senha e entrar",
      async (d) => {
        if (d.nova !== d.repetir) throw new Error("As duas senhas não são iguais.");
        await api("POST", "/auth/senha", { atual: d.atual || estado.senhaAtual, nova: d.nova }, { semRedirecionar: true });
        estado.senhaAtual = "";
        location.href = destino(usuario.papel);
      },
    );
  }

  function depoisDeEntrar(usuario) {
    if (usuario.trocar_senha) return telaTrocarSenha(usuario);
    location.href = destino(usuario.papel);
  }

  // ------------------------------------------------------------ início

  (async () => {
    $caixa.replaceChildren(el("div", { style: "display:grid;place-items:center;padding:24px" }, el("div", { class: "carregando", role: "img", "aria-label": "Carregando" })));
    try {
      const eu = await api("GET", "/auth/eu", null, { semRedirecionar: true }).catch((e) => { if (e.status === 401) return null; throw e; });
      if (eu) return depoisDeEntrar(eu);
      const params = new URLSearchParams(location.search);
      const volta = params.get("volta") || "";
      const perfil = params.get("perfil")
        || (volta.startsWith("/escritorio") ? "contador" : volta.startsWith("/empresa") ? "empresa" : "");
      if (volta.startsWith("/admin")) telaEntrar("");
      else if (params.get("criar") === "1") telaCadastro();
      else if (perfil === "contador" || perfil === "empresa") telaEntrar(perfil);
      else telaEscolha();
    } catch (erro) {
      $caixa.replaceChildren(el("h1", {}, "Não foi possível carregar"), el("p", { class: "sub" }, erro.message));
    }
  })();
})();
