// Aberto pelo app instalado (tela inicial do celular ou do computador): pula a página
// explicativa e vai para a abertura do app, que leva ao "Entrar" (ou à área de quem já entrou).
(function () {
  var instalado = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;
  if (instalado) location.replace("/abrir?origem=app");
})();
// Antes da primeira pintura: o título da abertura espera o motion.js (sem piscar) e o momento da frase.
document.documentElement.classList.add('m-enter');
setTimeout(function () { document.documentElement.classList.add('m-enter-done'); }, 700);
document.documentElement.classList.add('mo-js');
setTimeout(function () { document.documentElement.classList.add('mo-safe'); }, 2500);
