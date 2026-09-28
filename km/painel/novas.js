// Which lines on screen are wholly new. A line that did not exist in the chancel gets a bar
// in the margin instead of the word underline: in a new document every word would be
// underlined, and the mark says nothing. A word changed inside an old line keeps the
// underline. Pure: the caller gives the text, the line starts that are joined to the line
// above (a paragraph that flows is one line on screen) and the changed ranges, [de, até).

const branco = (c) => c === ' ' || c === '\t' || c === '\n' || c === '\r';
const mudou = (faixas, k) => faixas.some(([a, b]) => k >= a && k < b);

// The visible characters in [de, até) all changed, give or take the diff's loose matches: a
// character diff pairs a new paragraph's final period with the old one's, or a common word,
// and leaves a hole in a line that is new. Up to 10% (at least one) may stay unmarked.
export function coberto(texto, de, ate, faixas) {
  let sim = 0, nao = 0;
  for (let k = de; k < ate; k++) {
    if (branco(texto[k])) continue;
    if (mudou(faixas, k)) sim++; else nao++;
  }
  return sim > nao && nao <= Math.max(1, Math.floor((sim + nao) / 10));
}

// The start of each new line on screen, in document positions.
export function linhasNovas(texto, juntas, faixas) {
  if (!faixas.length) return [];
  const out = [];
  let ini = 0;
  while (ini <= texto.length) {
    // A linha da tela vai até a próxima quebra que não se emenda.
    let fim = texto.indexOf('\n', ini);
    while (fim !== -1 && juntas.has(fim + 1)) fim = texto.indexOf('\n', fim + 1);
    if (fim === -1) fim = texto.length;
    if (fim > ini || ini < texto.length) {
      // Uma linha em branco é nova quando a quebra de antes e a dela entraram juntas.
      const nova = texto.slice(ini, fim).trim()
        ? coberto(texto, ini, fim, faixas)
        : (ini === 0 || mudou(faixas, ini - 1)) && mudou(faixas, fim);
      if (nova) out.push(ini);
    }
    ini = fim + 1;
  }
  return out;
}
