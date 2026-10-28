# Publicar o Synapse pelo GitHub na Cloudflare

Esta versão usa **Workers, D1 e R2**. A página antiga do Pages pode permanecer no ar enquanto você testa uma instalação nova. Não altere o endereço divulgado antes de verificar as contas e mídias no serviço novo.

## 1. Preparar o projeto

Extraia o ZIP. No repositório `adiel13ad-aek/Synapsesus`, a raiz deve conter `package.json`, `wrangler.jsonc`, `src`, `web` e `migrations`. Envie os arquivos extraídos, não somente o ZIP ou o HTML. A pasta `legacy` mantém a versão Python para consulta e recuperação; não é servida ao visitante.

Instale Node.js 24. No Windows, abra a pasta que contém `package.json`, clique na barra de endereço do Explorador, digite `cmd` e pressione Enter. Execute um comando de cada vez:

```bash
npm ci
npx wrangler login
```

O login é feito pela Cloudflare. Não compartilhe o token ou sua senha. Antes de criar recursos, confira o plano e a cobrança apresentados na conta. As operações abaixo usam recursos reais; este pacote não contrata nem paga por eles. O pacote configura até 30 segundos de CPU por invocação para processamento de senhas e imagens: planeje Workers Paid e confira a cobrança de D1/R2. Nada foi contratado nesta entrega.

## 2. Criar banco e bucket privados

Para uma instalação nova:

```bash
npx wrangler d1 create synapse-db
npx wrangler r2 bucket create synapse-media
```

O primeiro comando mostra o UUID do D1. Escolha nomes diferentes se esses recursos já existirem e contiverem dados. **Não habilite `r2.dev` nem um domínio público diretamente no bucket R2.** Os arquivos privados precisam passar pela autorização do Worker. O domínio público pertence ao Worker, não ao bucket.

No painel Cloudflare, confirme seu subdomínio `workers.dev`. O endereço final segue o formato `https://NOME-DO-WORKER.SUBDOMINIO-DA-CONTA.workers.dev`. Você também pode usar um domínio próprio posteriormente.

Execute o assistente e informe os nomes, o UUID e o endereço HTTPS final:

```bash
node scripts/setup.mjs
```

Ele grava somente a configuração pública no `wrangler.jsonc` e não cria recursos. Mantenha `APP_ENV=production`, `AGE_ENFORCED=1` e `MINOR_ACCOUNTS_ENABLED=0`. O arquivo de exemplo contém um endereço e UUID inválidos propositalmente; o comando de implantação recusa esses valores.

Crie as tabelas no banco novo:

```bash
npx wrangler d1 migrations apply DB --remote
```

Se você já tem dados na versão 0.9, pare aqui e siga [MIGRACAO.md](MIGRACAO.md), antes de criar outra conta administrativa. Não importe um banco antigo por cima de contas já criadas no novo serviço.

## 3. Segredos e serviços

Somente na primeira instalação, gere duas chaves exclusivas:

```bash
node scripts/setup.mjs --secrets
```

O arquivo privado `.private/first-install-secrets.json` contém `SETUP_TOKEN` e `ADMIN_ENCRYPTION_KEY`. Guarde a chave administrativa em um gerenciador de senhas. Não rode o gerador para trocar a chave de uma instalação existente: isso impediria a leitura dos segredos já protegidos.

Depois de criar o Worker no passo 4, volte a estes comandos para importar os secrets no mesmo projeto:

```bash
npx wrangler secret bulk .private/first-install-secrets.json
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put TURNSTILE_SECRET_KEY
```

Os comandos `secret put` pedem o valor de forma interativa. Configure as chaves como **secrets de execução**, não como variáveis públicas nem apenas variáveis do processo de build.

No `wrangler.jsonc`, preencha os campos públicos abaixo e envie a atualização ao GitHub. IDs, contatos de suporte, chave pública etária e site key Turnstile não são senhas.

| Variável | Valor esperado |
|---|---|
| `PUBLIC_ORIGIN` | Endereço HTTPS exato do Worker, sem caminho ou barra final |
| `OPERATOR_NAME` | Responsável real pela operação |
| `SUPPORT_EMAIL` | Endereço acompanhado para suporte |
| `CHILD_SAFETY_EMAIL` | Contato acompanhado para segurança infantil |
| `MAIL_FROM` | Remetente autorizado no provedor de e-mail |
| `TURNSTILE_SITE_KEY` | Chave pública do widget, autorizada para seu domínio |
| `AGE_PROVIDER_URL` | URL HTTPS do fluxo do fornecedor compatível com o contrato implementado |
| `AGE_PROVIDER_ID` | Identificador do emissor do comprovante |
| `AGE_PUBLIC_KEY` | Chave pública Ed25519 esperada pelo verificador |
| `PUBLIC_INDEXING` | Comece com `0`; mude para `1` depois da validação pública |

O envio de e-mail usa API HTTPS do Resend nesta migração, não as variáveis SMTP antigas. Para configurar:

1. No Resend, abra **Domains**, adicione um domínio seu e copie os registros DNS que o serviço fornecer para o painel DNS desse domínio. Aguarde a verificação. O domínio de e-mail precisa ser seu: não use `workers.dev`, `gmail.com` ou outro domínio que você não controla. O site pode continuar no endereço `workers.dev`.
2. Crie uma API key com permissão de envio para esse domínio e importe como `RESEND_API_KEY`, usando o comando interativo acima.
3. Em `MAIL_FROM`, informe algo como `Synapse <avisos@SEU-DOMINIO>` com seu domínio verificado. Esse exemplo não é um endereço pronto. `SUPPORT_EMAIL` deve ser uma caixa que você realmente acompanha; cadastrar o remetente de envio não cria uma caixa de entrada.
4. Teste confirmação e recuperação em uma caixa real. A aceitação pela API não prova chegada à caixa de entrada.

Para o Turnstile, abra **Turnstile → Add widget** na Cloudflare, informe o hostname exato do site (sem `https://` nem caminho), escolha **Managed** e crie o widget. Copie a Site Key pública para `TURNSTILE_SITE_KEY` e importe a Secret Key como `TURNSTILE_SECRET_KEY`. O código já exibe o widget e valida a resposta no servidor. Ao trocar o domínio, atualize também o hostname autorizado no widget.

A aferição etária exige um serviço ou adaptador que implemente o contrato descrito no código e nos guias de segurança. Colocar a URL de uma empresa não cria essa integração automaticamente. Não use chaves de teste como se fossem validação de usuários reais.

## 4. Conectar GitHub ao Worker

No painel Cloudflare, abra **Workers & Pages → Create application → conectar um repositório GitHub** e selecione `adiel13ad-aek/Synapsesus`. Crie um **Worker**. Os nomes das telas podem mudar; não escolha publicação estática no Pages para este pacote.

| Campo | Configuração |
|---|---|
| Nome do Worker | Igual ao `name` no `wrangler.jsonc` |
| Branch de produção | `main` |
| Diretório raiz | Raiz do projeto, onde está `package.json` |
| Build command | `npm run build` |
| Deploy command | `npm run deploy` |
| Build variable `NODE_VERSION` | `24.22.1` (também indicada no arquivo `.node-version`) |
| Bindings | `DB` → D1, `MEDIA` → R2, `ASSETS` → `web` conforme Wrangler |

O build executa verificações de código, testes automatizados e testes no runtime local dos Workers. Se algum falhar, a publicação é interrompida.

O primeiro deploy pode ocorrer antes dos secrets; nesse intervalo o serviço deve permanecer fechado para cadastros gerais. Execute agora os comandos `wrangler secret` do passo 3, configure os serviços e publique a configuração final antes de testar. O envio de e-mails usa uma fila processada pelo agendamento do Worker; consulte o estado da fila no painel se a mensagem não chegar.

O comando `npm run deploy` valida a configuração, aplica as migrations D1 pendentes e publica o Worker. O token de implantação precisa de acesso ao Worker, ao banco D1 e ao bucket R2 configurados. Confira especialmente a permissão de edição de D1: o token automático de Builds pode não a incluir. Se uma migration falhar, a publicação não continua. Não habilite builds de branches de teste apontando aos recursos de produção.

**Alternativa GitHub Actions:** o arquivo `.github/workflows/cloudflare.yml` valida pushes e pull requests; implantação exige acionamento manual em Actions → Validar e implantar Cloudflare → Run workflow, com `deploy` marcado. Crie o environment `production` e seus secrets `CLOUDFLARE_API_TOKEN` e `CLOUDFLARE_ACCOUNT_ID`; restrinja o token aos recursos necessários. O workflow aplica migrations e publica após os testes. Escolha um caminho de implantação para evitar duas publicações simultâneas.

## 5. Criar sua conta administrativa

Abra `/instalar` no endereço HTTPS do seu Worker. Informe o `SETUP_TOKEN` guardado no arquivo privado e crie sua conta com nome, usuário, e-mail e senha exclusiva de pelo menos 16 caracteres. A tela envia o token em um cabeçalho para `/api/setup`; depois da primeira conta de responsável, esse fluxo fica bloqueado. Nunca coloque esse token na URL, em um print público ou em um arquivo do repositório.

A conta administrativa exige confirmação de e-mail e configuração de autenticador. A criação não concede um desbloqueio administrativo permanente. Em `/admin`, configure 2FA e guarde os códigos de recuperação. Depois de confirmar acesso, remova `SETUP_TOKEN` dos secrets do Worker:

```bash
npx wrangler secret delete SETUP_TOKEN
```

Não remova `ADMIN_ENCRYPTION_KEY`. Sua senha não deve ser a do GitHub, Cloudflare ou e-mail.

## 6. Validar a instalação antes da abertura

No endereço HTTPS real, teste duas contas e confira:

1. Cadastro restrito por convite, recebimento de e-mail, recuperação de senha e aferição de idade.
2. Publicação, comentário, curtida, coleção e mensagem permitida.
3. Perfil privado: uma conta sem aprovação não pode obter as mídias nem pelo endereço direto. Bloquear/remover seguidor deve retirar o acesso.
4. Denúncia, resposta de suporte, suspensão e encerramento de sessões.
5. Administração com senha e 2FA; um usuário comum não pode acessar as ações administrativas.
6. Exportação e exclusão de uma conta de teste; cópia externa do D1 e das mídias; restauração em recursos separados.

Use `/api/health` para saber se o código responde; a resposta deve ser JSON com `ok: true` e `runtime: "cloudflare-workers"`. `/api/ready` confere também o acesso à tabela de configuração do D1. `/api/state` deve responder JSON com listas como `actors`, `posts` e `stories`, mesmo que vazias. Se estiver conectado à sua conta, essa resposta pode conter dados privados; não publique seu conteúdo.

Se uma dessas URLs abrir o próprio site em HTML, confira se o endereço aponta para o Worker e se a integração está publicando o projeto inteiro. Se aparecer erro 500, confira bindings, migrations e logs do Worker. Se aparecer “Endereço não autorizado”, confira `PUBLIC_ORIGIN`. Recarregar com Ctrl+Shift+R só ajuda a atualizar arquivos do navegador; não cria um servidor que não foi implantado.

Esses diagnósticos, sozinhos, não provam que todos os serviços funcionam. Revise as pendências em `/operacao` e `/admin` e só então abra cadastros gerais. As verificações locais desta entrega não equivalem a auditoria independente ou teste de carga pública.

**Pendência que exige integração real:** o pacote não inclui um fornecedor comercial de aferição etária nem um adaptador pronto. A rede em produção exige e-mail confirmado e comprovante adulto assinado no contrato implementado. Os campos `AGE_PROVIDER_URL`, `AGE_PROVIDER_ID` e `AGE_PUBLIC_KEY` precisam vir de uma integração compatível; inventar valores ou apenas cadastrar a URL de um fornecedor não a conclui. Você consegue instalar e acessar o painel com e-mail confirmado e 2FA antes dessa integração, mas não liberar a experiência social completa. O acesso social de menores permanece desabilitado nesta edição.

## 7. Operação e cópias de segurança

D1 Time Travel ajuda a recuperar o banco conforme a retenção do plano; não copia os arquivos R2. Mantenha também exportações privadas e cópias independentes das mídias. Um exemplo de exportação, durante uma janela de manutenção:

```bash
npx wrangler d1 export DB --remote --output=.private/d1-backup.sql
```

A pasta `.private` precisa existir. O SQL contém dados privados. Preserve o banco e as mídias do mesmo momento, teste a recuperação em outra instalação e acompanhe falhas de e-mail, denúncias, uso de armazenamento e custos. O pacote não agenda cópias fora da conta Cloudflare.

## Fontes oficiais verificadas

- [Workers Builds e integração](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/)
- [GitHub Actions](https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/)
- [Importação e exportação D1](https://developers.cloudflare.com/d1/best-practices/import-export-data/)
- [R2 e comandos Wrangler](https://developers.cloudflare.com/r2/reference/wrangler-commands/)
- [R2 público e restrições](https://developers.cloudflare.com/r2/buckets/public-buckets/)
- [D1 Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/)
- [Limites D1](https://developers.cloudflare.com/d1/platform/limits/)
- [Domínios verificados no Resend](https://resend.com/docs/dashboard/domains/introduction)
- [Widget Turnstile no painel](https://developers.cloudflare.com/turnstile/get-started/widget-management/dashboard/)
- [Node.js no ambiente de build](https://developers.cloudflare.com/workers/ci-cd/builds/build-image/)
