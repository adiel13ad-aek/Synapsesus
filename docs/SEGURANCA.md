# Segurança — piloto privado, não certificado

## Controles implementados

- Senhas com PBKDF2-SHA256, salt aleatório e 600.000 iterações. Cookies HttpOnly, SameSite Strict e Secure quando PUBLIC_ORIGIN é HTTPS; sessão expira em sete dias.
- Escritas exigem cabeçalho da aplicação, JSON, verificação de origem e token CSRF ligado à sessão autenticada. Autoria, exclusão, notas privadas e conversas são conferidas no servidor.
- SQL parametrizado. HTML de posts e resultados é exibido como texto escapado. Links aceitam apenas HTTP/HTTPS; esquemas executáveis e credenciais na URL são rejeitados. Links externos usam noopener/noreferrer.
- Imagens raster são decodificadas e reencodificadas; SVG é rejeitado, há limites de bytes/dimensões e nomes gerados pelo servidor. A chave de API nunca é enviada ao cliente.
- CSP restringe scripts e conexões ao próprio servidor e proíbe frames. Não há carregamento automático de imagens de sites terceiros. A demo standalone não recebe os cabeçalhos de segurança do servidor.
- A pesquisa externa usa hosts fixos, timeout e sem seguir redirecionamentos. Não existe endpoint de proxy para um endereço arbitrário. O servidor não busca o conteúdo de links de posts.
- Limites de tentativas por IP/conta, cota diária de pesquisa por conta e global, erros explícitos de provedor. Sem cache de APIs no service worker.

## Limitações materiais

O operador pode ler o banco, incluindo mensagens e notas. Não há criptografia de ponta a ponta nem segregação organizacional de administradores. Credenciais reais, documentos privados e dados sensíveis não devem ser usados no teste.

HTTP em rede local não protege dados em trânsito. A configuração HTTPS de produção, proxy e certificado ainda precisa ser implementada e auditada. Não há recuperação de senha, verificação de e-mail, segundo fator, revisão completa de dependências, antivírus de arquivos, moderação operada nem defesa distribuída contra abuso.

Os limites de requisição em memória são para um único processo. Há limite individual de foto, mas não cota de disco por conta. A API é síncrona para partes do trabalho; carga e resistência a grandes requisições maliciosas não foram auditadas. Não exponha a um público aberto.

A filtragem strict do provedor não garante ausência de conteúdo impróprio. Links podem levar a phishing, conteúdo incorreto ou sites que mudam depois de publicados. Validar um URL não certifica o seu destino.

A demo usa armazenamento do navegador e não tem autenticação; qualquer pessoa com acesso a esse perfil do navegador pode ler seus dados. Não é equivalente à privacidade da API com conta.

## Exclusão e backup

A exclusão normal de posts/conta remove arquivos de mídia associados e registros dependentes. Exportação JSON não inclui os bytes das fotos; faça backup da pasta data com servidor parado. Backup externo, logs de terceiros e contas em buscadores não são apagados pelo Synapse.

Agentes e missões antigos ficam arquivados em migrações. Exportações podem conter esses registros privados antigos. A preservação é deliberada; não executa os agentes.

## Antes de abrir ao público

Revisar autenticação/recuperação, moderação e denúncias, proteção do público jovem, tratamento de dados e políticas, infraestrutura HTTPS, backups/restauração, cotas de armazenamento, logging com minimização, proteção contra abuso e custos, testes de carga, dependências e auditoria independente.

Documentação de referência:
https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors
https://www.electronjs.org/docs/latest/tutorial/security
