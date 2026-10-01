// Approving the whole file at once: every block of every change the page shows, in one
// approval. Pure; the page only draws the button and asks.
//
// It goes by sha, like any other approval, so it approves what you saw: a change an agent
// wrote after the page read the file stays pending, and a block that is gone gets the
// approval refused.

// mudancas: the page's changes, [{unidades: [{sha}], sumidas: [linha]}]. Null with fewer
// than two: one change's own Aprovar already takes the file.
export function arquivoInteiro(mudancas) {
  if (mudancas.length < 2) return null;
  const shas = [...new Set(mudancas.flatMap((m) => m.unidades.map((u) => u.sha)))];
  const sumidas = mudancas.flatMap((m) => m.sumidas || []);
  return { shas, sumidas };
}

// A mark that disappears is the change made to pass unnoticed: approving the file in one
// click would approve its removal unseen, so the page asks, naming each one.
export function perguntaDasMarcas(sumidas) {
  if (!sumidas.length) return null;
  const n = sumidas.length;
  const linhas = sumidas.map((l) => '  ' + l.replace(/^\s*>\s*/, '')).join('\n');
  return `Aprovar o arquivo inteiro aprova a remoção de ${n} ${n === 1 ? 'marca' : 'marcas'} `
    + `que estava${n === 1 ? '' : 'm'} na chancela:\n\n${linhas}\n\nAprovar mesmo assim?`;
}
