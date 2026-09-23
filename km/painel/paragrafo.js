// Which line breaks inside paragraphs to show as a space. Pure: the caller gives the
// paragraph ranges (from the Markdown syntax tree) and the cursor; -1 means no cursor,
// as in the read-only chancel column, where every paragraph flows.

export function quebrasOcultas(texto, paragrafos, cursor) {
  const out = [];
  for (const { from, to } of paragrafos) {
    if (cursor >= from && cursor <= to) continue;          // onde você está, as quebras reais
    for (let i = texto.indexOf('\n', from); i !== -1 && i < to; i = texto.indexOf('\n', i + 1)) {
      const antes = texto.slice(Math.max(from, i - 2), i);
      if (antes.endsWith('  ') || antes.endsWith('\\')) continue;   // quebra dura do Markdown
      out.push({ from: i, to: i + 1 });
    }
  }
  return out;
}
