# Registro de verificação — Synapse 0.3

## API: 30 testes aprovados

Execução: `python -m pytest -q --disable-warnings --maxfail=1`.

Inclui autenticação/sessão/hash; duplicidade e senha incorreta; CSRF/origem/autoria; posts com links, curtidas, comentários e salvos; upload, reencodificação e exclusão de imagens; rejeição de formatos/links inválidos; isolamento, atualização e remoção de coleções; busca social sem acentos; atalhos externos sem resultados falsos; adaptadores Wikipédia/Brave com respostas simuladas; erros do provedor; limites por conta/global e persistência da cota global após exclusão; seguir/bloquear; conversas entre humanos; exportação/exclusão; ausência de rotas de agentes; migração aditiva a partir do esquema anterior e reinicialização da aplicação.

Não foram feitas chamadas reais autenticadas ao Brave. Uma tentativa real de conexão com a Wikipédia falhou na resolução de DNS deste ambiente. Os testes de provedores verificam o contrato de dados e tratamento de erros com respostas controladas, não conectividade real nem precisão de resultados.

## Interface: 16 verificações aprovadas

Execução: `python tests/browser_smoke.py`, com um servidor descartável ativo em `http://127.0.0.1:8776` e Chromium instalado. O caminho do navegador pode ser ajustado com `CHROMIUM_PATH`; a URL com `SYNAPSE_TEST_URL`.

O script verifica publicação/curtida/comentário na demo; busca local e links externos; endereço → coleção → compartilhamento; cadastro real; foto validada e exibida; interação com posts; coleções persistentes; mensagens entre duas contas; edição de perfil; tentativa de injeção HTML exibida como texto; reconexão com mesma sessão; e ausência de rolagem horizontal em cinco telas, em 320, 390, 768 e 1440 pixels. Verifica também ausência de exceções JavaScript não tratadas.

O navegador gerenciado não permite navegar para localhost. Os testes carregam o HTML/CSS/JS inlined e usam uma ponte Python para as requisições HTTP ao servidor real e para imagens. Não substituem a lógica de autenticação/dados por mocks. O teste não valida CSP aplicada pelo navegador sobre uma navegação HTTP normal: os cabeçalhos foram inspecionados nos testes de API. O armazenamento persistente da demo standalone também não foi validado no contexto de arquivo real; no teste inlined a demo avisou sobre dados temporários.

O arquivo `browser-results.json` registra as verificações executadas. Imagens de prévia são capturas da interface, não conceitos gerados.

## Não testado / não entregue

Instalação real em Android/iOS/Windows/macOS, PWA instalada via HTTPS, publicação em lojas, API externa ao vivo, carga/escala, comportamento em Safari/Firefox, teste de acessibilidade completo, auditoria de segurança e banco de produção.

Nenhum resultado de teste deve ser apresentado como certificado de segurança ou como prova de disponibilidade na internet.
