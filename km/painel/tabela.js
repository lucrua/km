// A table as its source lines. Every operation returns new lines; a cell no control
// touched keeps its bytes, padding included, so the file changes only where asked.

export function partes(linha) {
  let ini = 0;
  while (ini < linha.length && (linha[ini] === ' ' || linha[ini] === '\t')) ini++;
  const pre = linha.slice(0, ini);
  let corpo = linha.slice(ini);
  const inicial = corpo.startsWith('|');
  if (inicial) corpo = corpo.slice(1);
  const celulas = [];
  let atual = '';
  for (let k = 0; k < corpo.length; k++) {
    const c = corpo[k];
    if (c === '\\' && k + 1 < corpo.length) { atual += c + corpo[k + 1]; k++; continue; }
    if (c === '|') { celulas.push(atual); atual = ''; continue; }
    atual += c;
  }
  // Terminou numa barra (fora espaços)? Então `atual` é só o que sobra depois dela.
  const final = celulas.length > 0 && atual.trim() === '' && /\|\s*$/.test(corpo);
  if (!final) celulas.push(atual);
  return { pre, inicial, celulas, final, fim: final ? atual : '' };
}

export function montar(p) {
  return p.pre + (p.inicial ? '|' : '') + p.celulas.join('|') + (p.final ? '|' + p.fim : '');
}

export const celulas = (linha) => partes(linha).celulas.map((c) => c.trim());

export const ehSeparador = (linha) => {
  const cs = celulas(linha);
  return cs.length > 0 && cs.every((c) => /^:?-+:?$/.test(c));
};

const colunas = (linhas) => partes(linhas[0]).celulas.length;

function vazia(modelo, n) {
  const p = partes(modelo);
  return montar({ ...p, celulas: Array.from({ length: n }, () => ' '), final: true, fim: '' });
}

export function inserirLinha(linhas, depoisDe) {
  const i = Math.max(1, depoisDe);
  return [...linhas.slice(0, i + 1), vazia(linhas[0], colunas(linhas)), ...linhas.slice(i + 1)];
}

export function removerLinha(linhas, i) {
  if (i < 2) throw new Error('o cabeçalho e o separador não saem');
  return linhas.filter((_, k) => k !== i);
}

export function inserirColuna(linhas, depoisDe) {
  return linhas.map((l, k) => {
    const p = partes(l);
    const cs = [...p.celulas];
    while (cs.length < depoisDe + 1) cs.push(' ');
    cs.splice(depoisDe + 1, 0, k === 1 ? ' --- ' : ' ');
    return montar({ ...p, celulas: cs });
  });
}

export function removerColuna(linhas, j) {
  if (colunas(linhas) <= 1) throw new Error('a última coluna não sai');
  return linhas.map((l) => {
    const p = partes(l);
    if (j >= p.celulas.length) return l;
    return montar({ ...p, celulas: p.celulas.filter((_, k) => k !== j) });
  });
}
