> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Synapse 0.8 — do código ao primeiro grupo real

**Estado desta entrega:** código e testes locais, não uma implantação realizada. Não há endereço público confirmado, domínio comprado, conta conectada à hospedagem nem serviço contratado por este pacote. A apresentação pública pode ser publicada antes da abertura geral da rede. O sistema não tem certificação de segurança ou conformidade jurídica.

## Decisão principal: visível não significa operacional

Um HTML de demonstração no Cloudflare pode abrir normalmente e ainda assim não possuir contas compartilhadas. O Synapse real precisa de **interface + servidor Python + banco persistente + armazenamento de imagens + e-mail**.

A arquitetura deste pacote usa FastAPI, SQLite e arquivos locais, com uma instância e um processo. Não é uma aplicação pronta para múltiplas instâncias. Não há capacidade de usuários simultâneos certificada. O backend atual não é colocado no ar enviando apenas `web/`, `index.html` ou a demo a uma hospedagem estática.

O caminho descrito aqui é manter site e API juntos em um Web Service Docker no Render, com disco persistente. Você pode usar o endereço HTTPS fornecido pelo serviço, sem comprar um domínio para começar. Esse caminho tem custos: serviço e disco persistente são pagos. Revise o preço mostrado antes de contratar. Não foi autorizada cobrança nesta entrega.

O Cloudflare pode continuar como DNS do seu domínio. Workers já oferece suporte a Python/FastAPI, mas levar ESTE projeto para esse runtime exigiria adaptar banco, armazenamento e processamento; isso não foi implementado aqui.

Fontes oficiais consultadas em 27/10/2026:
- https://render.com/docs/web-services
- https://render.com/docs/disks
- https://render.com/docs/free
- https://developers.cloudflare.com/workers/languages/python/packages/fastapi/

## 1. Preserve o que você já tem

Extraia este ZIP em uma pasta nova. Não apague arquivos do computador, repositório ou servidor sem backup. Faça uma cópia externa do banco e das mídias antes de atualizar. Preserve `.env`, a chave `ADMIN_ENCRYPTION_KEY` já usada e os caminhos dos dados. A atualização adiciona a tabela de convites sem apagar contas antigas.

**Não execute o gerador de PRIMEIRA instalação para substituir uma chave de uma instalação existente.** Uma chave diferente impede abrir os segredos TOTP existentes. Não copie dados privados para `web/`.

Leia também `GERENCIAR.md` e `OPERACAO.md` para as rotinas que já existiam na 0.7. Este guia prevalece para os novos convites e para a liberação pública.

## 2. Defina quem opera e quem pode entrar

Defina o responsável pela operação, um e-mail de suporte monitorado e um contato de segurança. Um mesmo endereço pode atender ambos no início, desde que seja realmente acompanhado. Como o criador é menor de idade, envolva um adulto responsável nas decisões contratuais, privacidade, moderação e atendimento. Esta é uma orientação operacional, não um parecer jurídico.

**Há uma pendência relevante:** o pacote NÃO implementa aferição de idade, vínculo de conta ao responsável e supervisão parental completos. Não comece convidando crianças e adolescentes como se essas proteções estivessem prontas. Um campo “tenho idade” ou um convite não equivale a aferição de idade ou consentimento parental.

No Brasil, o ECA Digital está em vigor desde março de 2026 e abrange serviços direcionados ou de acesso provável por menores. A lei prevê, entre outros pontos, vínculo de contas de usuários de até 16 anos ao responsável. Avalie o público com apoio apropriado e implemente as proteções aplicáveis antes de admiti-lo. Um piloto fechado não é uma dispensa das obrigações. Enquanto isso, use dados fictícios em desenvolvimento e um grupo de teste autorizado compatível com a avaliação de público, preferencialmente adultos para a validação inicial.

A nova verificação `audience_review` no painel é uma declaração documentada do responsável, **não um verificador automático ou certificado de conformidade**. Não a marque para esconder funções que ainda faltam.

Fontes oficiais:
- https://www.gov.br/anpd/pt-br/assuntos/noticias/eca-digital
- https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/l15211.htm
- https://www.gov.br/mdh/pt-br/assuntos/noticias/2026/defeso-eleitoral/agosto/eca-digital-conheca-as-regras-de-protecao-de-criancas-e-adolescentes-no-ambiente-online/

## 3. Suba o código ao GitHub

Use um repositório de teste novo ou uma branch para revisar a atualização antes de trocar a versão pública. Na raiz do repositório precisam estar `Dockerfile`, `render.yaml`, `server.py`, `launch.py`, `administration.py`, `features.py`, `manage.py`, `schema.sql`, `requirements*.txt`, `tools/` e `web/`. Não coloque o ZIP fechado como único arquivo do repositório.

**Nunca envie:** `.env`, `.env.production.local`, `data/`, banco, senhas, chaves SMTP/TOTP, e-mails de recuperação ou backups. O `.gitignore` protege o fluxo normal do Git, mas não substitui a sua revisão, nem remove automaticamente algo já publicado. Uma credencial publicada deve ser revogada/trocada no provedor, não apenas apagada do commit atual.

O workflow de testes está em `.github/workflows/test.yml`. Os testes foram executados no ambiente desta entrega; nenhum workflow foi executado na sua conta GitHub.

## 4. Crie o serviço real

No Render, conecte o repositório e crie um **Web Service com Docker**, não um Static Site. A opção Blueprint lê `render.yaml`, mas é preciso revisar plano, custos e variáveis. Não crie serviços pagos sem entender o preço.

Configuração proposta:

| Campo | Valor |
|---|---|
| Runtime | Docker |
| Dockerfile | `./Dockerfile` |
| Instâncias/processos | 1 / 1 |
| Health check | `/api/health` |
| Disco persistente | Montagem `/app/data` |
| Banco | `/app/data/synapse.db` |
| Mídias | `/app/data/media` |
| Autodeploy | Desligado inicialmente; implante após revisar/testar |

O template propõe 5 GB de disco. Isso é uma configuração inicial, não uma recomendação de capacidade garantida. Vídeos podem demandar memória/processamento e banda consideráveis. Monitore uso; não aumente réplicas deste projeto SQLite para tentar resolver carga.

Copie o endereço HTTPS que o serviço receber. Se o endereço só estiver disponível depois de criar o serviço, complete `PUBLIC_ORIGIN` antes do primeiro deploy bem-sucedido. Uma implantação bloqueada por configuração ausente deve ser corrigida; não troque para modo de desenvolvimento só para passar da verificação.

## 5. Configure as variáveis privadas

Para uma PRIMEIRA implantação, após conhecer o endereço do serviço, execute no Windows:

```text
PREPARAR-PRODUCAO-WINDOWS.bat
```

Ou, com as dependências instaladas:

```bash
python tools/prepare_production.py
```

O assistente pede o domínio, contatos, SMTP e conta administrativa; gera uma chave administrativa nova e salva **somente no computador** `.env.production.local`. As senhas não são impressas. Ele não contrata hospedagem nem envia dados a serviços externos. Não sobrescreve um arquivo existente.

No Render, use Environment → Add from .env e importe os valores desse arquivo PRIVADO. Confira os valores importados, especialmente senhas com espaços ou caracteres especiais; se o importador alterar algum valor, informe-o diretamente no campo privado correspondente. Faça isso somente na área de variáveis da sua hospedagem. Não envie o arquivo ao GitHub, à pasta pública ou ao chat. O importador de `.env` é documentado em https://render.com/docs/configure-environment-variables.

| Variável | O que informar |
|---|---|
| `SYNAPSE_ENV` | `production` |
| `PUBLIC_ORIGIN` | Seu endereço HTTPS exato, sem caminho; o mesmo que os usuários usarão |
| `SEED_DEMO_DATA` | `0` |
| `SYNAPSE_DB` / `SYNAPSE_MEDIA` | Caminhos do disco persistente da tabela anterior |
| `OPERATOR_NAME` | Responsável/organização que realmente opera o serviço |
| `SUPPORT_EMAIL` / `CHILD_SAFETY_EMAIL` | Contatos monitorados |
| `MAIL_MODE` | `smtp` |
| `SMTP_HOST`, `SMTP_PORT` | Valores do provedor de e-mail; 587 com STARTTLS ou 465 com TLS |
| `SMTP_FROM` | Remetente autorizado no provedor |
| `SMTP_USER`, `SMTP_PASSWORD` | Credenciais do provedor, não uma senha compartilhada no frontend |
| `BOOTSTRAP_HANDLE`, `BOOTSTRAP_EMAIL`, `BOOTSTRAP_PASSWORD` | Apenas para criar sua primeira conta de responsável |
| `ADMIN_ENCRYPTION_KEY` | Chave gerada e guardada uma única vez; preserve nas atualizações |
| `PUBLIC_INDEXING` | Comece com `0`; depois de revisar as páginas públicas, use `1` |
| `GOOGLE_SITE_VERIFICATION` | Opcional, apenas o valor da meta tag do Search Console |
| `CALLS_ENABLED` | Mantenha `0` até testar a infraestrutura experimental |

O provedor de e-mail pode exigir domínio/remetente verificado e configurações DNS. Não basta inventar um endereço em `SMTP_FROM`. E-mail configurado não é e-mail entregue: faça o teste real.

A chave `ADMIN_ENCRYPTION_KEY` protege os segredos do autenticador no banco, mas não criptografa todo o banco ou seus backups. Guarde cópia externa privada. O arquivo de configuração também contém segredos e precisa de armazenamento protegido.

## 6. Confira o primeiro funcionamento

Depois de um deploy bem-sucedido, abra, trocando o domínio de exemplo:

```text
https://SEU-ENDERECO/api/health
https://SEU-ENDERECO/
https://SEU-ENDERECO/admin
https://SEU-ENDERECO/bem-vindo
```

A primeira rota deve retornar JSON com `ok: true` e `version: "0.8.0"`. HTML, tela de demo ou resposta 404 nessa rota indicam que esse endereço não está servindo o backend esperado.

Confirme o e-mail da conta administrativa pelo link recebido. Entre no painel, configure o autenticador e guarde os códigos de recuperação. Depois da primeira criação bem-sucedida, remova as variáveis `BOOTSTRAP_*` do ambiente hospedado e suas cópias desnecessárias. Não remova `ADMIN_ENCRYPTION_KEY`.

Se o bootstrap criou a conta, mas a mensagem não chegou, corrija o SMTP e use Reenviar confirmação. Não marque o banco manualmente como verificado para contornar o teste de produção.

## 7. Prepare a comunidade e teste por convite

No painel:

- Em **Sistema**, remova as contas fictícias e confira armazenamento.
- Em **Políticas**, publique Termos, Privacidade e Regras revisados para a operação real. Rascunhos não viram políticas adequadas só por mudar o título.
- Em **Configurações**, deixe cadastro geral fechado e coloque um aviso honesto de lançamento em preparação.
- Em **Convites**, gere inicialmente um convite por pessoa, com 1 uso e validade curta. Copie o código imediatamente: o banco só guarda seu hash. Compartilhe de forma privada. Um link encaminhado pode ser usado por outra pessoa; convite não é prova de identidade.

O código autoriza cadastro mesmo com inscrições gerais fechadas, mas manutenção ativa continua bloqueando o cadastro. Convite revogado/expirado/sem vagas não cria conta. Revogar não exclui contas já criadas.

Os convites usam o fragmento `#convite=...`, que não é enviado ao servidor como parte da URL HTTP. Ainda assim são credenciais: não publique capturas com códigos ativos. O frontend retira o fragmento após capturá-lo. O link direto precisa ser testado no domínio final.

Faça estes testes com uma conta descartável e outra pessoa autorizada: convite → cadastro → confirmação real de e-mail → perfil → foto → comentário → seguir → mensagem → denúncia → bloqueio → recuperação de senha → exportação → exclusão. As contas novas recebem mensagens apenas de pessoas que elas seguem por padrão; o usuário pode ajustar isso nas preferências. Isso **não** substitui as proteções específicas de menores.

## 8. Backup, restauração e moderação

Antes de convidar público, mantenha uma cópia do banco e das mídias fora do disco da hospedagem e teste restaurá-la. O `manage.py` existente fornece `backup` e `restore`, mas exige parar a aplicação antes da cópia; `--server-stopped` é sua confirmação, não uma ação que para o servidor.

```bash
python manage.py backup /PASTA_PRIVADA/synapse-backup.zip --server-stopped
python manage.py restore /PASTA_PRIVADA/synapse-backup.zip --into /PASTA_NOVA_PRIVADA --server-stopped
```

Em Docker próprio, siga `OPERACAO.md` para parar `app`, executar a tarefa com o volume montado e reiniciar. No provedor hospedado, organize uma janela/tarefa compatível com a persistência e confirme que o processo está parado; não execute esse comando como se fosse um backup online certificado. O backup não inclui suas variáveis privadas; preserve-as separadamente. Restauração não deve sobrescrever produção; valide numa pasta nova.

Nenhum backup externo periódico foi contratado ou agendado nesta entrega. Defina essa rotina com o responsável técnico. A opção de manutenção ajuda a pausar publicações, mas não equivale a desligar o processo.

Defina quem acompanha denúncias e suporte, uma rotina diária, um modo de suspender cadastros e um procedimento para incidentes. Não prometa atendimento instantâneo se não houver equipe para isso. Não acesse mensagens privadas indiscriminadamente.

## 9. Verificação de leitura do domínio

Na pasta do projeto, rode:

```bash
python tools/check_public.py https://SEU-ENDERECO --output verificacao-lancamento.json
```

O comando faz GETs de baixa frequência e sem login para checar backend, produção, interface real, páginas públicas, sitemap, cabeçalhos básicos, restrição do painel e ausência de arquivos privados acessíveis. **Não** testa caixa de e-mail, restauração, carga, idade, cumprimento da lei ou vulnerabilidades em geral. Não altera nenhum dado nem abre cadastros. Use apenas no seu próprio serviço.

Ele retorna falha enquanto a indexação estiver desativada, o que é esperado no preparo. Não mude variáveis só para obter um resultado verde antes de revisar a página. A execução bem-sucedida não substitui os testes de contas reais acima.

## 10. Google e endereço público

A página para divulgação é `/bem-vindo`; `/` continua sendo a rede social. As páginas `/como-funciona` e `/ajuda` explicam o serviço sem login e sem depender de JavaScript para o conteúdo.

Depois de revisar domínio e textos, coloque `PUBLIC_INDEXING=1` e faça novo deploy. O sitemap conterá só essas três páginas. Painel, API, perfis, conversas e parâmetros de autenticação não são listados. `noindex` não é controle de acesso: privacidade depende das permissões do servidor.

No Google Search Console, adicione uma propriedade de Prefixo do URL com seu endereço HTTPS. Você pode verificar por meta tag: copie só o conteúdo da tag para `GOOGLE_SITE_VERIFICATION`, faça deploy e conclua a verificação. Se usar propriedade de domínio, siga a verificação DNS correspondente.

Envie `sitemap.xml`, inspecione `/bem-vindo` e solicite indexação. O Google não promete indexação nem posição nos resultados. Escreva uma descrição verdadeira; não use centenas de palavras-chave nem compre tráfego artificial.

Fontes oficiais:
- https://support.google.com/webmasters/answer/9008080?hl=pt-BR
- https://developers.google.com/search/docs/crawling-indexing/ask-google-to-recrawl
- https://developers.google.com/search/docs/fundamentals/seo-starter-guide

## 11. Cloudflare: o que fazer com o que já foi publicado

Não conseguimos confirmar o endereço ou conteúdo atualmente hospedado nesta entrega. Não apague a publicação existente sem revisar a migração.

**Se é um domínio seu administrado no Cloudflare:** adicione-o primeiro em Custom Domains do Render e siga o DNS mostrado pelo serviço; a orientação oficial inicial é CNAME e DNS only. Depois ajuste `PUBLIC_ORIGIN` para esse domínio e repita os testes. O projeto valida o Host: endereços alternativos de aplicação não autorizados podem retornar 400, de propósito. O `/api/health` é uma exceção pública limitada para verificações do provedor. Fonte: https://render.com/docs/configure-cloudflare-dns

**Se é um endereço `pages.dev` servindo somente HTML:** ele não se torna este backend por receber o ZIP. Use o endereço do Web Service para a rede real. Opcionalmente mantenha apenas a apresentação no Pages, com botão para o app verdadeiro:

```bash
python tools/export_landing.py --origin https://SUA-APRESENTACAO.pages.dev --app-origin https://SEU-APP.onrender.com --output public-site
```

Envie **só a pasta `public-site` gerada** ao serviço estático. Ela não contém contas, cadastro local, banco ou API. O script não sobrescreve uma pasta existente. Essa exportação é opcional e precisa ser testada no Pages real; não foi implantada aqui. O estado estático permanece “lançamento em preparação” até uma edição/reexportação consciente: não consulta automaticamente o backend.

Para ativar indexação na exportação use `--index` depois da revisão. Evite manter duas apresentações idênticas indexáveis em domínios diferentes: escolha um endereço canônico. O caminho mais simples deste guia continua sendo servir tudo no mesmo Web Service.

## 12. Só então libere a fase adequada

Conclua a aba Lançamento com os testes e revisões realmente realizados. O painel permite abrir inscrições gerais apenas depois das verificações previstas, mas não prova automaticamente a qualidade delas. Não abra a rede infantojuvenil sem implementar e revisar as proteções que faltam. Comece pequeno, monitore erros e denúncias, acompanhe quem consegue publicar e corrija dificuldades antes de ampliar divulgação.

A frase correta ao divulgar é: **“Synapse está começando. Rede social para descobrir, guardar e compartilhar.”** Não anuncie “100% seguro”, “navegador com acesso irrestrito”, “milhares de usuários” ou “IA completa” sem base.
