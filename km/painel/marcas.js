// The three marks, as the page writes and reads them. Pure: no DOM, no CodeMirror, so the
// exact forms are tested with `node --test` against the same regexes the engine greps for.
//
//   > ❓ **to_validate by AAAA-MM-DD** — …   a deadline; overdue once the date has passed
//   > 💬 **comment** — …                      for whoever reads the passage later
//   > 📌 **to_do · AAAA-MM-DD** — …           for an agent to find and address; the day written

export const PLACEHOLDER = 'add your comment here';

export const FORMAS = {
  to_validate: /^> ❓ \*\*to_validate by (\d{4}-\d{2}-\d{2})\*\* — (.+)$/,
  to_do: /^> 📌 \*\*to_do · (\d{4}-\d{2}-\d{2})\*\* — (.+)$/,
  comment: /^> 💬 \*\*comment\*\* — ()(.+)$/,
};

// A data no relógio de quem escreve: em UTC, depois das 21h no Brasil já seria amanhã.
const dois = (n) => String(n).padStart(2, '0');
export const hoje = (d = new Date()) => `${d.getFullYear()}-${dois(d.getMonth() + 1)}-${dois(d.getDate())}`;
export const emDias = (n, d = new Date()) => hoje(new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 12));

export function modelo(tipo, d = new Date()) {
  if (tipo === 'to_validate') return `> ❓ **to_validate by ${emDias(7, d)}** — ${PLACEHOLDER}`;
  if (tipo === 'to_do') return `> 📌 **to_do · ${hoje(d)}** — ${PLACEHOLDER}`;
  if (tipo === 'comment') return `> 💬 **comment** — ${PLACEHOLDER}`;
  throw new Error('marca desconhecida: ' + tipo);
}

export function marcaDaLinha(linha) {
  for (const [tipo, rx] of Object.entries(FORMAS)) {
    const m = rx.exec(linha);
    if (m && m[2].trim()) return { tipo, data: m[1], texto: m[2].trim() };
  }
  return null;
}

// Onde a marca entra: depois do bloco em que está o cursor — um parágrafo quebrado em várias
// linhas não é partido ao meio —, como bloco próprio, com uma linha em branco de cada lado, e
// com o texto de exemplo selecionado, para o que você digitar tomar o lugar dele.
const branca = (l) => /^\s*$/.test(l);
export function insercao(doc, pos, linha) {
  const linhas = doc.split('\n');
  const inicio = [];
  let p = 0;
  for (const l of linhas) { inicio.push(p); p += l.length + 1; }
  let n = 0;
  while (n + 1 < linhas.length && inicio[n + 1] <= pos) n++;
  if (!branca(linhas[n])) while (n + 1 < linhas.length && !branca(linhas[n + 1])) n++;
  const from = inicio[n] + linhas[n].length;
  const lead = branca(linhas[n]) ? '\n' : '\n\n';
  const trail = n + 1 < linhas.length && !branca(linhas[n + 1]) ? '\n' : '';
  const insert = lead + linha + trail;
  const i = linha.lastIndexOf(PLACEHOLDER);
  const anchor = from + lead.length + (i >= 0 ? i : linha.length);
  return { from, insert, anchor, head: i >= 0 ? anchor + PLACEHOLDER.length : anchor };
}
