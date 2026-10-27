# Synapse 0.3 — descubra a web, encontre sua gente

**Nova direção:** rede social de pessoas + pesquisa + coleções de referências. Os agentes de IA foram retirados da interface e suas rotas de execução foram removidas. O protótipo anterior não foi sobrescrito.

Este pacote é um **piloto privado utilizável**, não um serviço publicado. Não é um clone completo de Instagram/Google, não possui índice próprio de toda a internet e não é um navegador nativo. Não há APK, IPA ou EXE assinado.

## Experimentar agora: demonstração independente

Abra `Synapse-Discovery-demo.html` no navegador. Em um computador, normalmente basta dar dois cliques. No celular, alguns visualizadores de arquivos não executam JavaScript; nesse caso use a versão com servidor.

A demo permite publicar texto, foto e link; curtir, comentar e salvar posts; seguir perfis fictícios; pesquisar conteúdo local; guardar links em coleções; editar perfil e compartilhar uma descoberta no feed. Os botões de pesquisa externa abrem sites reais em outra aba, usando a sua conexão.

**A demo tem uma conta fictícia “Você”; não é login real.** Os dados ficam apenas neste navegador, quando o armazenamento está disponível. Não conectam pessoas nem sincronizam dispositivos. Sem armazenamento, um aviso informa que os dados são temporários. Fotos podem atingir a cota do navegador; o aplicativo avisa e não afirma ter salvo uma alteração que falhou.

A demo não consulta APIs de pesquisa. Na aba Wikipédia, oferece um link para abrir a pesquisa na própria enciclopédia. Ela não inventa resultados web nem simula pessoas respondendo.

## Executar a versão com servidor

Requisitos: **Python 3.10+**, com pip/venv, e internet na primeira instalação das dependências. Não precisa de Node.js, npm nem compilação da interface.

### Windows

1. Extraia o ZIP inteiro. Não execute o inicializador de dentro do ZIP.
2. Instale Python, habilitando `Add Python to PATH`, caso não esteja instalado.
3. Abra `INICIAR-WINDOWS.bat`.
4. Acesse `http://localhost:8000`, clique em **Entrar** e crie uma conta.

A senha deve ter pelo menos 10 caracteres. Não há senha padrão, administrador pré-configurado ou recuperação por e-mail. Use dados e senhas de teste. Os perfis de exemplo não podem entrar no sistema.

O inicializador instala as dependências na primeira execução e inicia o servidor. Mantenha o terminal aberto. `Ctrl+C` encerra; executar novamente retoma os dados do banco.

### Linux / macOS

```bash
sh iniciar-macos-linux.sh
```

Algumas distribuições Linux exigem instalar os componentes pip e venv do Python antes.

### Inicialização manual

```bash
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

Linux/macOS:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py
```

Porta ocupada: acrescente `--port 8001`. Para não abrir automaticamente o navegador, use `--no-browser`.

## Usar no celular e no computador

A mesma interface se adapta às duas telas. Por padrão, o servidor só aceita conexões do computador em que foi iniciado.

Para testes em **Wi-Fi privado confiável**, execute:

```bat
INICIAR-WINDOWS.bat --lan
```

Ou:

```bash
sh iniciar-macos-linux.sh --lan
```

No celular conectado à mesma rede, acesse `http://IP-DO-COMPUTADOR:8000`. No Windows, `ipconfig` mostra o IPv4 local. O computador precisa continuar ligado. `localhost` no celular aponta para o próprio celular, não para o PC.

Não abra portas no roteador nem exponha este piloto diretamente à internet. HTTP na rede local não protege senhas e mensagens em trânsito. Use contas de teste e limite permissões de firewall à rede privada necessária.

### Instalação PWA

O pacote contém manifesto, ícones e service worker. Navegadores compatíveis podem oferecer instalação quando a aplicação estiver servida em HTTPS. `localhost`/loopback é a exceção de desenvolvimento no próprio computador. Instalação depende do navegador e da plataforma; não foi testada em aparelhos físicos.

O HTML aberto como arquivo não é uma PWA instalada. O service worker guarda somente arquivos públicos da interface, não sessões, conversas, resultados de busca ou fotos enviadas. Sem servidor, a versão com contas informa falha; não troca silenciosamente para uma demo.

Referência: https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable

## O que funciona nesta versão

| Área | Implementação |
|---|---|
| Conta | Cadastro, login, logout, sessão, edição de nome e biografia |
| Feed | Texto, uma foto e um link por publicação; curtidas, comentários, posts salvos e exclusão própria |
| Pessoas | Perfis, seguir/deixar de seguir, filtro “Seguindo” e bloqueio |
| Explorar | Busca de posts/perfis, abertura de endereços, pesquisa externa e adaptadores opcionais |
| Coleções | Links privados, nome de coleção, nota privada, edição, remoção e compartilhamento explícito |
| Mensagens | Conversas entre contas humanas reais no mesmo servidor; consulta a cada 8 segundos |
| Controle | Registro de denúncias, exportação JSON e exclusão da própria conta |
| Dados | SQLite para registros; arquivos JPEG reencodificados para fotos |

A lista de assuntos sugeridos é editorial: **não são tendências medidas em tempo real**. O feed é cronológico, sem recomendação por IA. Não há Stories, Reels, vídeos, notificações push, chamadas, contas verificadas ou moderação operada.

Uploads: JPEG, PNG e WebP, até 3 MB e 16 megapixels. O servidor valida, redimensiona para no máximo 1440 × 1440, converte para JPEG e não preserva metadados EXIF. A demo guarda a imagem localmente sem esse processamento do servidor; não a publique em outro lugar supondo que seus metadados foram removidos.

## Como funciona a pesquisa

### Na rede / Pessoas

Busca apenas no conteúdo visível deste servidor. Não envia a consulta a Google, Brave ou Wikipédia. O piloto busca num recorte de até 100 posts recentes e 500 perfis, não em um índice paginado completo. A comparação ignora maiúsculas e acentos.

### Web — padrão sem chave

Mostra atalhos para Google, Brave e DuckDuckGo, que abrem em outra aba. **Isto não é resultado web renderizado dentro do Synapse.** O próprio buscador recebe a consulta quando você clica no botão. A interface informa a diferença; não há resultados fictícios.

Digite um endereço HTTP/HTTPS em Explorar para abrir o site, guardar o link ou preparar um post com ele. Não há coleta automática da página nem proxy de sites arbitrários.

### Web integrada — Brave Search opcional

O adaptador usa a API oficial de busca web, não uma API de IA. Ela permite consultar o índice do provedor e receber resultados estruturados:

https://api-dashboard.search.brave.com/app/documentation/web-search/get-started
https://api-dashboard.search.brave.com/api-reference/web/search/get

Copie `.env.example` para `.env`, configure no computador que roda o servidor e reinicie:

```dotenv
SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=SUA_CHAVE_APENAS_NO_SERVIDOR
SEARCH_DAILY_LIMIT=30
SEARCH_GLOBAL_DAILY_LIMIT=300
```

Nunca publique a chave nem a coloque no HTML/JavaScript. Sem chave válida, o modo externo continua disponível. A integração exige login, tem limite diário por conta e global e solicita filtragem `strict` ao provedor. Essa filtragem não é uma garantia absoluta de conteúdo seguro. O uso da API pode gerar cobranças conforme sua conta e plano; os limites são de chamadas, não um teto financeiro garantido. Uma tentativa reservada que falha também consome cota.

Não são registrados os textos das consultas no banco. Contadores por conta são apagados após sete dias ou na exclusão da conta; contadores globais sem identificador pessoal permanecem. O inicializador desativa o log de acessos do Uvicorn. O provedor e a infraestrutura externa ainda podem registrar requisições: não é navegação anônima garantida.

**O adaptador foi testado com respostas simuladas; não houve chamada real autenticada à API Brave.**

### Wikipédia

A versão com servidor inclui um adaptador para busca na Wikipédia em português, sem chave. É uma busca enciclopédica, não em toda a internet. A consulta só é enviada ao selecionar/pesquisar nessa aba. A fonte e o link do artigo ficam identificados. Revise o artigo, as fontes, a autoria e os termos de licença antes de reutilizar conteúdo.

Referência: https://www.mediawiki.org/wiki/API:Search

A tentativa de acesso real à Wikipédia neste ambiente falhou por resolução de DNS. O formato das respostas, a limpeza de marcação e o tratamento de erro foram testados com respostas controladas. **A disponibilidade externa não foi validada aqui.** Em caso de erro, há uma mensagem explícita e atalhos externos; não há substituição silenciosa por resultados inventados.

## “Navegador com acesso total” — limite importante

O protótipo abre páginas HTTP/HTTPS no navegador normal, em uma aba separada, com `noopener noreferrer`. Não embute todo site num iframe e não remove as proteções de outros serviços. Sites podem proibir incorporação usando CSP `frame-ancestors` e X-Frame-Options.

https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors

Para navegação dentro de uma janela desktop própria, uma próxima etapa seria um componente de navegação nativo isolado, por exemplo Electron `WebContentsView`, com segurança e testes dedicados. Isso **não foi implementado neste pacote**. Mesmo um navegador nativo não dá acesso automático a contas privadas, assinaturas ou conteúdo restrito.

https://www.electronjs.org/docs/latest/tutorial/web-embeds
https://www.electronjs.org/docs/latest/tutorial/security

## Faça um teste completo

Crie uma conta. Em **Explorar**, digite `https://example.com`. Clique em **Guardar**, escolha a coleção “Meu projeto” e escreva uma nota. Abra **Coleções**: o link e a nota estão privados. Clique em **Compartilhar**, escreva sua legenda e publique. Agora o feed contém o link e o comentário, mas não a nota privada da coleção.

Para fotos, crie uma publicação e escolha uma imagem pequena. Para mensagens, use outra janela anônima ou outro navegador, crie uma segunda conta no mesmo servidor e atualize o primeiro cliente. Os perfis de exemplo não respondem.

## Dados, backup e atualização da versão 0.2

O banco padrão fica em `data/synapse.db`; imagens ficam em `data/media/`. Para backup simples consistente, pare o servidor e copie a pasta `data` inteira. O JSON exporta registros e caminhos das imagens, **não inclui os bytes das fotos**. Arquivos SQLite `-wal`/`-shm` podem existir enquanto o banco estiver aberto.

Não sobreponha pastas em uso. Para atualizar um piloto 0.2: pare a versão antiga, faça backup, extraia esta versão numa pasta separada e copie o banco para `data/synapse.db`. A migração acrescenta campos de links/imagens e tabelas de coleções; preserva contas e posts antigos. Dados de agentes, missões e rascunhos ficam arquivados no banco e podem aparecer na exportação do proprietário, mas não têm rotas de criação/execução e não aparecem no novo feed. Preserve uma cópia intocada para voltar à versão anterior; não há ferramenta de downgrade.

## Segurança e limites de lançamento

Há hash de senha, cookies HttpOnly/SameSite, proteção CSRF, verificações de autoria, limites básicos de requisição, consultas SQL parametrizadas e texto escapado na interface. Imagens externas não são carregadas automaticamente; os links não são visitados pelo servidor.

Essas medidas não equivalem a uma auditoria nem tornam a aplicação pronta para um público aberto. Limites de requisição em memória pressupõem um único processo. Faltam HTTPS operado, recuperação/verificação de contas, moderação, políticas de privacidade e proteção de usuários, backups automatizados, cotas de armazenamento, monitoramento, paginação e testes de carga.

Mensagens e coleções são privadas pela autorização da aplicação, **não criptografadas de ponta a ponta**. O operador com acesso ao banco pode lê-las. Feed/perfis são públicos para quem consegue acessar o servidor. Bloqueio restringe interações e visualização no feed da conta, não transforma uma publicação pública em segredo.

## Testes executados

**30 testes de API aprovados** e **16 verificações de interface aprovadas**. A interface foi exercitada em Chromium, em 320, 390, 768 e 1440 pixels; cinco telas por largura foram conferidas quanto a rolagem horizontal. Consulte `docs/TESTES.md`.

A política do navegador deste ambiente impede navegação para localhost. Por isso, os testes de interface carregaram HTML/CSS/JS inlined e conectaram `fetch` e imagens ao servidor HTTP real por uma ponte Python. Não houve substituição da lógica da aplicação. Isto não prova instalação PWA, conectividade HTTPS ou funcionamento em Android/iOS físicos.

Nenhum teste usou uma chave real de busca nem realizou cobrança. Os testes não são uma certificação de segurança.

## Estrutura

```text
server.py                 API, autenticação, pesquisa, coleções e mídia
schema.sql                Dados sociais e migrações aditivas
web/                      Interface, manifesto e service worker
run.py                    Inicializador do servidor
Synapse-Discovery-demo.html Demonstração independente
build_demo.py             Reconstrói a demo sem incluir dados privados
tests/                    Testes de API e interface
docs/                     Arquitetura, segurança e resultados
```
