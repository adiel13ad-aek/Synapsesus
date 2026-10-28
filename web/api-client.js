'use strict';
// A successful HTTP status alone does not establish that the API is running.
(() => {
  const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  function error(code, message) {
    return Object.assign(new Error(message), {code});
  }
  async function request(path, method = 'GET', data, csrf = '') {
    const headers = {'X-Synapse-Client': 'web-v10'};
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      if (csrf) headers['X-CSRF-Token'] = csrf;
    }
    let response;
    try {
      response = await fetch(path, {
        method, headers, credentials: 'same-origin', cache: 'no-store',
        ...(data === undefined ? {} : {body: JSON.stringify(data)}),
      });
    } catch {
      throw error('network_error', 'Sem conexão com o servidor. Confira a internet e tente novamente.');
    }
    const contentType = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    if (contentType !== 'application/json' && !/^application\/[a-z0-9.+-]+\+json$/.test(contentType)) {
      if (!response.ok) throw error('http_error', `O servidor respondeu com erro HTTP ${response.status}. Tente novamente.`);
      throw error('api_not_json', 'Este endereço não está entregando os dados da rede. Verifique se o domínio aponta para o Worker do Synapse.');
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw error('api_invalid_json', 'A resposta do servidor está incompleta ou inválida. Tente novamente.');
    }
    if (!object(payload)) throw error('api_invalid_json', 'O servidor devolveu dados incompatíveis com esta versão do site.');
    if (!response.ok) {
      let message = payload.detail;
      if (Array.isArray(message)) message = 'Revise os campos: ' + message.map(item => Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : 'dados').join(', ');
      const failure = error('http_error', typeof message === 'string' ? message : 'Não foi possível concluir.');
      failure.status = response.status;
      failure.requestId = typeof payload.request_id === 'string' ? payload.request_id : '';
      throw failure;
    }
    return payload;
  }
  function validateState(value) {
    const lists = ['actors', 'posts', 'following', 'saved', 'blocked', 'links', 'stories', 'notifications'];
    if (!object(value) || !['server', 'demo'].includes(value.mode) ||
        !(value.me === null || object(value.me)) || lists.some(key => !Array.isArray(value[key]))) {
      throw error('state_invalid', 'Os dados recebidos estão incompletos ou incompatíveis. Atualize o site e o Worker para a mesma versão.');
    }
    return value;
  }
  window.SynapseAPI = Object.freeze({request, validateState});
})();
