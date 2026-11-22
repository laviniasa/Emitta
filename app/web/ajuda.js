// Central de ajuda: perguntas frequentes com busca, filtro por assunto e link direto (#id).
(function () {
  "use strict";

  const CATEGORIAS = [
    ["todas", "Todas"],
    ["comecar", "Primeiros passos"],
    ["certificado", "Certificado"],
    ["notas", "Notas fiscais"],
    ["impostos", "Impostos e MEI"],
    ["conta", "Conta e segurança"],
  ];

  // r: lista de blocos. Texto simples vira parágrafo; {ol:[...]} ou {ul:[...]} vira lista.
  const PERGUNTAS = [
    { id: "o-que-e", cat: "comecar", q: "O que é o Emitta?", r: [
      "É um emissor de NFS-e para escritórios contábeis. O contador cadastra a empresa e libera os serviços que ela presta; a própria empresa emite a nota pelo celular, direto no Emissor Nacional do governo, sem precisar escolher código de serviço.",
      "Também funciona para MEI e autônomo que emitem as próprias notas, com a conta \"MEI ou autônomo\"." ] },
    { id: "cadastrar-empresa", cat: "comecar", q: "Como cadastro uma empresa no painel?", r: [
      { ol: [
        "No painel, toque em \"Nova empresa\".",
        "Digite o CNPJ. Razão social, cidade, endereço e atividades vêm da Receita Federal.",
        "Confira a alíquota do ISS e salve.",
        "Siga as três etapas que aparecem: certificado, serviços e acesso ao app." ] } ] },
    { id: "liberar-servicos", cat: "comecar", q: "Como escolho os serviços que a empresa pode emitir?", r: [
      "Na aba \"Serviços\" da empresa aparecem primeiro os sugeridos pela atividade (CNAE) do cartão CNPJ, com base na tabela oficial. Toque em \"Liberar\" nos que ela realmente presta.",
      "Se precisar de outro, use \"Todos os serviços\" para buscar na lista nacional completa. A empresa só vê, na hora de emitir, o que você liberou." ] },
    { id: "acesso-empresa", cat: "comecar", q: "Como a empresa recebe o acesso ao app?", r: [
      "Na aba \"Acesso ao app\", informe o nome e o e-mail de quem vai emitir. O Emitta mostra uma senha provisória uma única vez: passe para a pessoa por um canal seguro.",
      "No primeiro acesso ela cria a própria senha. Se esquecer, é só criar o acesso de novo com o mesmo e-mail que uma nova senha provisória é gerada." ] },
    { id: "instalar-app", cat: "comecar", q: "Dá para instalar o Emitta no celular?", r: [
      "Sim. Abra o Emitta no navegador do celular e toque em \"Instalar o app no celular\" na tela de entrar.",
      { ul: [
        "iPhone: no Safari, toque em Compartilhar e depois em \"Adicionar à Tela de Início\".",
        "Android: no Chrome, toque nos três pontinhos e depois em \"Instalar app\"." ] },
      "O ícone abre direto na tela de entrar." ] },

    { id: "certificado-tipo", cat: "certificado", q: "Qual certificado digital preciso?", r: [
      "O certificado A1 da empresa, aquele que vem como arquivo .pfx (ou .p12) com uma senha. O certificado A3, de cartão ou token, não funciona em sistemas on-line." ] },
    { id: "certificado-enviar", cat: "certificado", q: "Como envio o certificado?", r: [
      "Na aba \"Certificado\" da empresa, escolha o arquivo .pfx e digite a senha dele. O Emitta confere se o certificado é do mesmo CNPJ e se ainda está na validade.",
      "O certificado e a senha ficam guardados criptografados e são usados só para assinar as notas dessa empresa. Você pode remover a qualquer momento." ] },
    { id: "certificado-vencendo", cat: "certificado", q: "E quando o certificado vence?", r: [
      "O painel avisa quando faltam 30 dias ou menos e marca a empresa na lista. Com o certificado vencido a emissão para. Renove com a certificadora e envie o arquivo novo na mesma aba." ] },

    { id: "emitir", cat: "notas", q: "Como a empresa emite uma nota?", r: [
      { ol: [
        "No app, toque em \"Nova nota\".",
        "Escolha o serviço (só aparecem os liberados pelo contador).",
        "Digite o CPF ou CNPJ do cliente. Com CNPJ, o nome vem da Receita.",
        "Informe o valor e confira o resumo.",
        "Toque em emitir. Em segundos a nota volta autorizada, com PDF e XML." ] } ] },
    { id: "rejeitada", cat: "notas", q: "A nota foi recusada. E agora?", r: [
      "Quando o governo recusa, o Emitta mostra o motivo em português, sem código técnico. Na maioria das vezes é um dado do cliente ou do serviço: corrija e emita de novo.",
      "Se a mensagem falar de alíquota, serviço ou certificado, quem resolve é o contador, no painel." ] },
    { id: "cancelar", cat: "notas", q: "Como cancelo uma nota emitida errada?", r: [
      "Abra a nota e toque em \"Cancelar esta nota\", escolhendo o motivo. Se o problema foi um dado errado, cancele e emita uma nota nova com os dados certos.",
      "O prazo para cancelar é definido pela prefeitura. Passado o prazo, o pedido precisa ser feito direto na prefeitura." ] },
    { id: "baixar-xml", cat: "notas", q: "Como baixo os PDF e XML das notas?", r: [
      "Cada nota tem os botões \"Baixar PDF\" e \"Baixar XML\".",
      "O contador também pode baixar tudo de uma vez em \"Notas do escritório\": escolha o mês e a empresa e baixe o pacote com PDFs, XMLs e uma planilha para importar no sistema contábil." ] },
    { id: "recebidas", cat: "notas", q: "O que são as \"Notas recebidas\"?", r: [
      "São as notas de serviço que outras empresas emitiram para o CNPJ do seu cliente. O Emitta busca no Ambiente Nacional usando o certificado da empresa, e você pode baixar os XML para a escrituração." ] },
    { id: "ibs-cbs", cat: "notas", q: "As notas já saem com IBS e CBS?", r: [
      "Sim. Em 2026 o grupo do IBS e da CBS é opcional e entra na nota quando o cliente é empresa com endereço completo. Com CPF, a nota sai sem esse grupo, o que é permitido neste ano." ] },

    { id: "guias", cat: "impostos", q: "Como funcionam as guias de impostos?", r: [
      "O contador envia o PDF da guia (DAS, DARF, ISS e outras) na aba \"Impostos\". A empresa recebe no app, baixa, paga no banco e toca em \"Já paguei\". O contador vê na hora o que já foi pago." ] },
    { id: "limite-mei", cat: "impostos", q: "Como o Emitta acompanha o limite do MEI?", r: [
      "Para MEI, o painel soma o faturamento das notas no ano e compara com o limite de R$ 81.000. No ano de abertura o limite é proporcional: R$ 6.750 por mês de atividade.",
      "O aviso aparece ao chegar perto do limite e quando ele é passado. Até 20% acima, o MEI paga a diferença e vira ME no ano seguinte; acima disso o desenquadramento é retroativo. Vale conversar com o contador." ] },
    { id: "resumo-ano", cat: "impostos", q: "Onde vejo o faturamento do ano?", r: [
      "Na aba \"Resumo do ano\" da empresa (e no cartão do ano, no app da empresa), com o total por mês, a média mensal e uma planilha para baixar." ] },

    { id: "esqueci-senha", cat: "conta", q: "Esqueci a minha senha.", r: [
      { ul: [
        "Empresa: peça ao seu contador para criar o seu acesso de novo. Você recebe uma senha provisória.",
        "Contador ou MEI: fale com o suporte do Emitta pelo contato no fim desta página." ] } ] },
    { id: "duas-etapas", cat: "conta", q: "Como ativo a verificação em duas etapas?", r: [
      "Em \"Segurança\", toque em ativar e leia o QR code com um aplicativo autenticador (Google Authenticator, Microsoft Authenticator ou similar). Depois disso, além da senha, o Emitta pede o código de 6 dígitos do aplicativo." ] },
    { id: "remover-empresa", cat: "conta", q: "Como removo uma empresa?", r: [
      "Abra a empresa, vá em \"Dados da empresa\" e toque em \"Remover esta empresa\". Serviços, acessos, certificado, guias e as notas guardadas no Emitta são apagados.",
      "As notas emitidas continuam no Emissor Nacional. Se precisar dos XML e PDF, baixe antes em \"Notas do escritório\"." ] },
    { id: "dados-seguros", cat: "conta", q: "Meus dados estão seguros?", r: [
      "A conexão é criptografada, o certificado fica criptografado, as senhas são guardadas de forma irreversível e cada contador vê só as próprias empresas. Os detalhes estão na Política de privacidade." ] },
  ];

  const $busca = document.getElementById("busca");
  const $cats = document.getElementById("categorias");
  const $lista = document.getElementById("perguntas");
  const $contagem = document.getElementById("contagem");
  const NOME_CAT = Object.fromEntries(CATEGORIAS);
  let categoria = "todas";

  const SETA = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
  const sem = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const textoDe = (p) => [p.q, ...p.r.map((b) => (typeof b === "string" ? b : (b.ol || b.ul).join(" ")))].join(" ");

  // Destaca o termo buscado sem usar HTML vindo de fora.
  function comDestaque(texto, termo) {
    const frag = document.createDocumentFragment();
    if (!termo) { frag.append(texto); return frag; }
    const base = sem(texto);
    let i = 0, achou;
    while ((achou = base.indexOf(termo, i)) !== -1) {
      frag.append(texto.slice(i, achou));
      const m = document.createElement("mark");
      m.textContent = texto.slice(achou, achou + termo.length);
      frag.append(m);
      i = achou + termo.length;
    }
    frag.append(texto.slice(i));
    return frag;
  }

  function cartao(p, termo, aberta) {
    const art = document.createElement("article");
    art.className = "pergunta" + (aberta ? " aberta" : "");
    art.id = p.id;
    const h3 = document.createElement("h3");
    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "pergunta-botao";
    botao.setAttribute("aria-expanded", String(aberta));
    botao.setAttribute("aria-controls", `r-${p.id}`);
    const titulo = document.createElement("span");
    const cat = document.createElement("span");
    cat.className = "pergunta-cat";
    cat.textContent = NOME_CAT[p.cat];
    titulo.append(cat, comDestaque(p.q, termo));
    const seta = document.createElement("span");
    seta.className = "pergunta-seta";
    seta.innerHTML = SETA; // ícone fixo
    botao.append(titulo, seta);
    h3.append(botao);

    const resp = document.createElement("div");
    resp.className = "pergunta-resposta";
    resp.id = `r-${p.id}`;
    resp.setAttribute("role", "region");
    const dentro = document.createElement("div");
    const texto = document.createElement("div");
    texto.className = "texto";
    p.r.forEach((b) => {
      if (typeof b === "string") {
        const par = document.createElement("p");
        par.append(comDestaque(b, termo));
        texto.append(par);
      } else {
        const lista = document.createElement(b.ol ? "ol" : "ul");
        (b.ol || b.ul).forEach((item) => { const li = document.createElement("li"); li.append(comDestaque(item, termo)); lista.append(li); });
        texto.append(lista);
      }
    });
    dentro.append(texto);
    resp.append(dentro);
    if (!aberta) resp.inert = true;

    botao.addEventListener("click", () => {
      const abrir = !art.classList.contains("aberta");
      art.classList.toggle("aberta", abrir);
      botao.setAttribute("aria-expanded", String(abrir));
      resp.inert = !abrir;
      if (abrir) history.replaceState(null, "", `#${p.id}`);
    });
    art.append(h3, resp);
    return art;
  }

  function desenhar(abrirId) {
    const termo = sem($busca.value.trim());
    const filtradas = PERGUNTAS.filter((p) =>
      (categoria === "todas" || p.cat === categoria) && (!termo || sem(textoDe(p)).includes(termo)));
    $lista.replaceChildren(...filtradas.map((p) => cartao(p, termo, p.id === abrirId || (!!termo && filtradas.length <= 2))));
    if (!filtradas.length) {
      const v = document.createElement("div");
      v.className = "vazio-ajuda";
      v.textContent = "Nenhuma pergunta encontrada. Tente outra palavra ou fale com a gente logo abaixo.";
      $lista.append(v);
    }
    $contagem.textContent = termo || categoria !== "todas"
      ? `${filtradas.length} ${filtradas.length === 1 ? "pergunta encontrada" : "perguntas encontradas"}`
      : "";
  }

  CATEGORIAS.forEach(([id, nome]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = nome;
    b.setAttribute("aria-pressed", String(id === categoria));
    b.addEventListener("click", () => {
      categoria = id;
      [...$cats.children].forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      desenhar();
    });
    $cats.append(b);
  });

  let espera;
  $busca.addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(() => desenhar(), 120); });

  function irParaHash() {
    const id = decodeURIComponent(location.hash.slice(1));
    if (id && !PERGUNTAS.some((p) => p.id === id)) return;
    if (id) { $busca.value = ""; categoria = "todas"; [...$cats.children].forEach((x, i) => x.setAttribute("aria-pressed", String(i === 0))); }
    desenhar(id);
    const alvo = id && document.getElementById(id);
    if (alvo) setTimeout(() => alvo.scrollIntoView({ block: "center" }), 60);
  }
  window.addEventListener("hashchange", irParaHash);
  irParaHash();
})();
