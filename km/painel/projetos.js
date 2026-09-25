// Os projetos: qual abre primeiro e o que cada linha diz. Lógica pura; a página só desenha.

// A URL manda (um favorito, a extensão do VS Code); sem ela, o último usado neste navegador;
// depois, o repositório de onde o `km serve` foi chamado; por fim, o primeiro da lista.
// Uma URL com um projeto que não está na lista não escolhe outro no lugar: diz que não há.
export function escolherInicial(lista, { param = null, lembrado = null, inicial = null } = {}) {
  const tem = (n) => !!n && lista.some((p) => p.nome === n);
  if (param) return tem(param) ? { nome: param, aviso: '' }
    : { nome: null, aviso: `o projeto ${param} não está na lista — adicione-o abaixo` };
  for (const n of [lembrado, inicial]) if (tem(n)) return { nome: n, aviso: '' };
  return { nome: lista.length ? lista[0].nome : null, aviso: '' };
}

export function situacao(p) {
  if (p.erro) return { texto: p.erro, classe: 'ruim' };
  if (p.pct) return { texto: `${p.pct} a aprovar`, classe: 'ace' };
  if (!p.n) return { texto: 'nada acompanhado', classe: 'mut' };
  return { texto: 'em dia', classe: 'ok' };
}

// O título da aba começa pelo nome da pasta do repositório, seguido de ` · `: o ActivityWatch
// grava o título da janela e o /activity da esteira cobra o tempo ao que vem antes. É contrato.
// Sem projeto (a vista Projetos, ainda vazia), o tempo é do próprio km.
export function tituloDaAba(projeto) {
  return projeto ? `${projeto.split('/').pop()} · km chancela` : 'km · projetos';
}
