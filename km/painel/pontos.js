// O servidor conta posições em code points (o len do Python); o CodeMirror, em unidades
// UTF-16. Um 📌 ou um 🔒 vale uma posição lá e duas aqui: toda posição que vai ao servidor
// passa por esta conversão.
export function emPontos(texto, i) {
  let n = 0;
  for (let k = 0; k < i; k++) {
    const c = texto.charCodeAt(k);
    if (c >= 0xd800 && c <= 0xdbff && k + 1 < i) k++;
    n++;
  }
  return n;
}
