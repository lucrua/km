// A régua da esquerda como árvore: só os arquivos que o painel revisa, e as pastas acima deles.
// Tudo aqui é lógica pura — montar, ordenar, somar, decidir o que abre —; a página só desenha.

const ordem = new Intl.Collator('pt', { sensitivity: 'base', numeric: true });
const comparar = (a, b) => ordem.compare(a.nome, b.nome) || (a.nome < b.nome ? -1 : a.nome > b.nome ? 1 : 0);

// D.docs → {tipo:'pasta', caminho:'', filhos}. Uma pasta cujo único filho é outra pasta vira uma
// linha só (`descoberta/guides`), como as pastas compactas do VS Code. Pastas antes, depois arquivos.
export function montarArvore(docs) {
  const raiz = pasta('', '');
  docs.forEach((d, i) => {
    const partes = d.file.split('/');
    let p = raiz;
    for (let k = 0; k < partes.length - 1; k++) {
      const caminho = partes.slice(0, k + 1).join('/');
      let f = p.filhos.find((x) => x.tipo === 'pasta' && x.caminho === caminho);
      if (!f) { f = pasta(caminho, partes[k]); p.filhos.push(f); }
      p = f;
    }
    p.filhos.push({ tipo: 'arquivo', caminho: d.file, nome: partes[partes.length - 1], i, doc: d });
  });
  raiz.filhos = raiz.filhos.map(compactar);
  arrumar(raiz);
  return raiz;
}

function pasta(caminho, nome) {
  return { tipo: 'pasta', caminho, nome, filhos: [], total: 0, pendentes: 0, novos: 0 };
}

function compactar(n) {
  if (n.tipo !== 'pasta') return n;
  while (n.filhos.length === 1 && n.filhos[0].tipo === 'pasta') {
    const f = n.filhos[0];
    n = { ...f, nome: n.nome + '/' + f.nome };
  }
  n.filhos = n.filhos.map(compactar);
  return n;
}

// Ordena e soma de baixo para cima: quantos arquivos, quantos a aprovar e quantos sem
// chancela, em qualquer profundidade.
function arrumar(p) {
  p.total = p.pendentes = p.novos = 0;
  for (const f of p.filhos) {
    if (f.tipo === 'pasta') {
      arrumar(f);
      p.total += f.total; p.pendentes += f.pendentes; p.novos += f.novos;
    } else {
      p.total++;
      if (!f.doc.rastreado) p.novos++;
      else if (f.doc.pendente) p.pendentes++;
    }
  }
  p.filhos.sort((a, b) => (a.tipo === b.tipo ? comparar(a, b) : a.tipo === 'pasta' ? -1 : 1));
}

// O que a coluna da direita diz de um arquivo: quanto falta, em dia, ou nunca chancelado.
export function estadoArquivo(d) {
  if (!d.rastreado) return { classe: 'novo', texto: 'novo' };
  if (d.pendente) return { classe: 'ace', texto: d.pct };
  return { classe: 'ok', texto: '✓' };
}

// E de uma pasta: ●N arquivos a aprovar abaixo dela; ✓ se tudo está em dia; `novo` se nada
// abaixo tem chancela. Uma mistura de em dia e sem chancela não diz nada — fica quieta.
export function estadoPasta(p) {
  if (p.pendentes) return { classe: 'ace', texto: '●' + p.pendentes };
  if (!p.novos) return { classe: 'ok', texto: '✓' };
  return { classe: 'novo', texto: p.novos === p.total ? 'novo' : '' };
}

// As pastas que começam abertas: as que guardam algo a aprovar.
export function abertasPadrao(raiz) {
  const out = new Set();
  (function andar(p) {
    for (const f of p.filhos) if (f.tipo === 'pasta') { if (f.pendentes) out.add(f.caminho); andar(f); }
  })(raiz);
  return out;
}

// As linhas de pasta acima de um arquivo, da mais alta para a mais baixa.
export function ancestrais(raiz, file) {
  const acima = [];
  (function andar(p) {
    for (const f of p.filhos) {
      if (f.tipo === 'arquivo') { if (f.caminho === file) return true; continue; }
      if (!file.startsWith(f.caminho + '/')) continue;
      acima.push(f.caminho);
      if (andar(f)) return true;
      acima.pop();
    }
    return false;
  })(raiz);
  return acima;
}

// As linhas que aparecem com estas pastas abertas, na ordem da tela, com o que o
// WAI-ARIA pede de uma árvore plana: nível, posição entre os irmãos e quantos são.
export function visiveis(raiz, abertas) {
  const out = [];
  (function andar(p, nivel, pai) {
    p.filhos.forEach((no, k) => {
      out.push({ no, nivel, pos: k + 1, de: p.filhos.length, pai });
      if (no.tipo === 'pasta' && abertas.has(no.caminho)) andar(no, nivel + 1, no.caminho);
    });
  })(raiz, 1, null);
  return out;
}
