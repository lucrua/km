// O texto editado e ainda não salvo, quando os trechos da tela mudam por baixo dele (uma
// aprovação junta blocos iguais, um agente mexe no arquivo). Lógica pura; a página só desenha.
//
// Cada edição guarda a base: o texto do arquivo em que ela foi feita. A chave de um trecho é a
// posição dele (g:<linha>), e a posição não diz se o texto é o mesmo: colar a edição num
// trecho que cresceu mostrava o arquivo cortado, e salvar apagava o resto. A edição segue o
// texto: entra onde a base está, uma vez só, em linhas inteiras; se não há lugar certo, volta
// para você em `perdidas`, nunca é colada no lugar errado.

const semFim = (t) => (t || '').replace(/\s+$/, '');

// Onde a agulha aparece como linhas inteiras — nunca no meio de uma linha.
function ondeEsta(texto, agulha) {
  const out = [];
  for (let i = texto.indexOf(agulha); i >= 0; i = texto.indexOf(agulha, i + 1)) {
    const antes = i === 0 || texto[i - 1] === '\n';
    const fim = i + agulha.length;
    if (antes && (fim === texto.length || texto[fim] === '\n')) out.push(i);
  }
  return out;
}

// sujos: {chave: texto editado}; bases: {chave: texto do arquivo quando a edição começou};
// trechos: [{chave, texto}] editáveis na tela agora, com o texto do arquivo.
export function realocar(sujos, bases, trechos) {
  const arquivo = new Map(trechos.map((t) => [t.chave, t.texto]));
  const out = {}, outBases = {}, perdidas = [], soltas = [];
  // Onde o trecho continua o mesmo, a edição fica como está — o editor nem é mexido.
  for (const [chave, texto] of Object.entries(sujos)) {
    const base = bases[chave];
    if (base !== undefined && arquivo.has(chave) && semFim(arquivo.get(chave)) === semFim(base)) {
      out[chave] = texto; outBases[chave] = base;
    } else soltas.push({ texto, base });
  }
  for (const { texto, base } of soltas) {
    const agulha = semFim(base);
    const achados = agulha ? trechos.filter((t) => ondeEsta(t.texto, agulha).length) : [];
    const vezes = achados.reduce((n, t) => n + ondeEsta(t.texto, agulha).length, 0);
    if (vezes !== 1) { perdidas.push(texto); continue; }
    const alvo = achados[0].chave;
    const atual = out[alvo] !== undefined ? out[alvo] : arquivo.get(alvo);
    const onde = ondeEsta(atual, agulha);
    if (onde.length !== 1) { perdidas.push(texto); continue; }
    out[alvo] = atual.slice(0, onde[0]) + semFim(texto) + atual.slice(onde[0] + agulha.length);
    outBases[alvo] = arquivo.get(alvo);
  }
  return { sujos: out, bases: outBases, perdidas };
}
