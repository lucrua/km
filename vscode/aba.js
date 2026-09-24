// O arquivo que a aba ativa mostra, aberto como texto ou num editor customizado (o webview
// de outra extensão): a barra de status é a única superfície que serve aos dois.
function uriDaAba(aba, { TabInputText, TabInputCustom }) {
  const entrada = aba && aba.input;
  return (entrada instanceof TabInputText || entrada instanceof TabInputCustom)
    ? entrada.uri : undefined;
}

module.exports = { uriDaAba };
