// Antes da primeira pintura: o título da abertura espera o motion.js (sem piscar) e o momento da frase.
document.documentElement.classList.add('m-enter');
setTimeout(function () { document.documentElement.classList.add('m-enter-done'); }, 700);
document.documentElement.classList.add('mo-js');
setTimeout(function () { document.documentElement.classList.add('mo-safe'); }, 2500);
