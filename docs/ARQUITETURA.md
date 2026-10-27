# Synapse Discovery — arquitetura e direção do produto

## A experiência central

Uma rede social de descobertas: a pessoa pesquisa, encontra uma fonte, guarda uma referência e decide se quer conversar sobre ela. O feed não precisa ser separado da pesquisa: a fonte pode acompanhar o post, e um assunto do feed pode voltar à busca.

A proposta não afirma ineditismo mundial. O diferencial a validar é a continuidade entre **pesquisa → coleção privada → publicação com fonte → conversa**, sem compartilhar automaticamente o histórico de navegação.

A analogia “Google + Instagram” descreve a experiência desejada, não afiliação, acesso a bancos privados dessas empresas ou reprodução de seus produtos.

## Implementação entregue

```text
Navegador desktop / celular
        │
        ├── Interface responsiva + manifesto PWA
        │      Feed / Explorar / Coleções / Perfis / Mensagens
        │
        ├── HTTPS externo em nova aba (abrir site/buscador)
        │
        └── API FastAPI no mesmo domínio
               ├── Sessões + autoria + bloqueios
               ├── Feed, seguidores, mensagens, denúncias
               ├── Links e notas privados por proprietário
               ├── SQLite
               ├── JPEG público reencodificado em data/media
               └── Provedores de pesquisa, hosts fixos
                      ├── Wikipédia (enciclopédia)
                      └── Brave Search (opcional, chave no servidor)
```

Sem agentes de IA, treinamento de modelos, scraping de buscadores ou execução de código remoto. A busca padrão sem chave não consulta APIs: fornece atalhos explícitos para buscadores externos.

### Por que manter esta base

A versão 0.2 já possuía contas e relações sociais. O protótipo 0.3 reaproveita esse núcleo e o amplia, evitando uma reescrita desnecessária do armazenamento. A interface foi redesenhada sem dependências frontend e sem exigir compilação, para facilitar execução em máquinas modestas.

SQLite e um processo de API são uma escolha para o piloto, não uma arquitetura final de escala. Nenhuma comparação de desempenho em grande escala foi realizada.

## Identidade e dados

`actors` guarda contas humanas; perfis iniciais são fictícios e não podem autenticar. O nome de usuário é público; não é verificação de identidade. `sessions` guarda hashes dos tokens, não o cookie bruto. A API atribui a autoria pelo usuário autenticado, nunca pelo ID enviado no corpo.

`posts` ganhou `link_url`, `link_title`, `image_path` e `image_alt`. O usuário escreve a legenda e o título da referência. O servidor não baixa a página indicada, não extrai metadados e não cria um proxy aberto.

`web_links` contém proprietário, endereço, título, coleção e nota. Um mesmo endereço normalizado tem uma entrada por conta; guardar novamente atualiza seus dados. Coleções são nomes por entrada, não espaços compartilhados. Renomear um link de coleção move apenas esse link. Coleções públicas/colaborativas ainda não existem.

Fotos de posts são públicas para quem conhece o endereço dentro do servidor. Não existe upload privado neste piloto. Fotos são apagadas junto do post ou da conta na operação normal. Backups externos não são apagados pela API.

Tabelas antigas de IA permanecem somente para atualização não destrutiva. Os endpoints não existem nesta versão; não há agentes executando em segundo plano.

## Privacidade por padrão

A aba “Na rede” não chama um provedor externo. Na aba Wikipédia ou Web integrada, a consulta vai ao serviço identificado. O usuário deve poder distinguir uma recomendação da comunidade de um resultado de buscador.

A pesquisa não vira publicação. Guardar um link não publica a nota. A publicação é feita somente no formulário explícito. Não existe registro persistente de histórico de pesquisas, compartilhamento automático de visitas nem rastreador de sites externos.

Essa arquitetura não impede registros pelo provedor ou infraestrutura. O servidor lê mensagens e notas para operar; não há criptografia de ponta a ponta. Não prometa sigilo que a arquitetura não oferece.

## Navegação real, sem falsa promessa de acesso irrestrito

Um site comum não consegue incorporar qualquer serviço: CSP `frame-ancestors` e X-Frame-Options controlam a incorporação. A versão entregue abre sites em novas abas e preserva as proteções. Não há “desbloqueador”, acesso automático a login nem remoção de restrições.

https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors

Uma fase desktop posterior pode usar `WebContentsView` de Electron com páginas remotas em contextos isolados. Deve manter Node.js desativado para conteúdo remoto, sandbox/context isolation, autorização explícita de permissões e nenhum IPC privilegiado exposto aos sites. Não deve compartilhar sessão/cookies do Synapse com páginas externas. Essa fase não está no pacote.

https://www.electronjs.org/docs/latest/tutorial/web-embeds
https://www.electronjs.org/docs/latest/tutorial/security

Para celular, avaliar uma experiência de navegação compatível com cada sistema antes de prometer o mesmo motor em todas as plataformas. PWA, navegação nativa e mecanismo de busca são componentes distintos.

## Evolução proposta, ainda não implementada

**Piloto fechado:** hospedar com HTTPS, validar provedores reais, observar o percurso completo, entrevistar usuários e testar contas entre aparelhos. Medir tarefas concluídas, erros e uso de coleções sem colher histórico desnecessário.

**Rede visual:** imagens em carrossel, compressão/entrega de mídia, edição de post, perfis melhorados, recuperação de conta, notificações e moderação operada. Vídeos exigem pipeline próprio, limites e orçamento.

**Descoberta integrada:** paginação de busca, filtros claros, pesquisa nos links públicos que a comunidade decidiu compartilhar, busca textual dedicada e ranking que não confunda popularidade com confiabilidade. Evitar promover um site como verdadeiro apenas por receber curtidas.

**Escala:** após medir gargalos, separar mídia em armazenamento de objetos, migrar dados transacionais para PostgreSQL, usar fila para tarefas demoradas e limites compartilhados entre instâncias. Ainda não há benchmark que justifique microserviços.

**Navegação interna:** implementar e auditar um cliente nativo separado, com abas, sessões isoladas, origem visível e permissões de download/câmera/microfone. Não declarar “acesso total à internet”: autenticação, disponibilidade, licenciamento e regras dos serviços continuam existindo.

## Não objetivos desta versão

Índice global próprio, crawler da internet, motor Chromium próprio, login em serviços terceiros, importação de contas Instagram/Google, agentes, recomendações por modelo, publicações autônomas, mensagens com E2EE, moderação automática, APK/IPA/EXE assinado.
