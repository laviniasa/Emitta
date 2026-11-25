// Primeira visita: aviso com os Termos de uso e a Política de privacidade e o botão "Aceitar".
(function () {
  "use strict";
  var CHAVE = "emitta_termos_aceitos";
  var VERSAO = "2026-11-22";
  try { if (localStorage.getItem(CHAVE) === VERSAO) return; } catch (e) { /* sem armazenamento: mostra o aviso */ }

  var caixa = document.createElement("div");
  caixa.className = "aviso-termos";
  caixa.setAttribute("role", "region");
  caixa.setAttribute("aria-label", "Termos de uso");
  var texto = document.createElement("p");
  texto.style.margin = "0";
  function link(href, rotulo) { var a = document.createElement("a"); a.href = href; a.textContent = rotulo; return a; }
  texto.append("Usamos só cookies essenciais. Ao usar o Emittaê, você concorda com os ",
    link("/termos", "Termos de uso"), " e a ", link("/privacidade", "Política de privacidade"), ".");
  var botao = document.createElement("button");
  botao.type = "button";
  botao.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7"/></svg>';
  botao.append("Aceitar");
  botao.addEventListener("click", function () {
    try { localStorage.setItem(CHAVE, VERSAO); } catch (e) { /* segue sem guardar */ }
    caixa.classList.remove("visivel");
    setTimeout(function () { caixa.remove(); }, 400);
  });
  caixa.append(texto, botao);
  document.body.append(caixa);
  requestAnimationFrame(function () { requestAnimationFrame(function () { caixa.classList.add("visivel"); }); });
})();
