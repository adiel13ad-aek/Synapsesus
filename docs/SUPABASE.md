# Ativar autenticação com Supabase

Esta atualização tira o cálculo de senha de produção do Worker e o delega ao Supabase Auth. Os perfis, publicações, convites, sessões, permissões administrativas e segundo fator continuam no D1; as imagens continuam no R2. Os links de confirmação de e-mail e recuperação continuam sendo enviados pelo mecanismo já existente do Synapse, com Resend. Portanto, configurar o Supabase não substitui `RESEND_API_KEY` e `MAIL_FROM`.

Nenhuma configuração remota é feita ao baixar ou extrair o pacote. A chave publicável e o endereço do projeto já estão no atualizador. Falta cadastrar a chave privada diretamente na Cloudflare e publicar os arquivos atualizados.

## 1. Atualizar a pasta que você já configurou

Extraia o pacote atualizado em uma pasta separada. Copie os arquivos `package.json`, `package-lock.json`, `.gitignore` e as pastas `src`, `scripts`, `migrations`, `tests` e `docs` para a pasta do seu projeto existente, substituindo os arquivos de mesmo nome. Preserve seu `wrangler.jsonc` configurado, `.private`, `.dev.vars` e quaisquer arquivos de backup. Não substitua o UUID real do D1 por um UUID de zeros.

No Prompt de Comando do Windows, entre na pasta existente (ajuste apenas se você mudou o local):

```bat
cd /d "C:\Users\adiel\Documents\Synapse-Discovery-v1.0-Cloudflare-RC1"
npm ci
node scripts/configure-supabase.mjs
```

O atualizador cria uma cópia `.bak` do arquivo anterior. Ele preserva o UUID do D1, o bucket R2, o endereço público já configurado e as outras variáveis. Adiciona somente a configuração de autenticação abaixo, corrige o nome antigo padrão para `synapsesus` e remove o limite configurável de CPU incompatível com o plano Free. Não altera recursos remotos.

```json
"AUTH_PROVIDER": "supabase",
"SUPABASE_URL": "https://fjsdjlqktrkyuxbenzup.supabase.co",
"SUPABASE_PUBLISHABLE_KEY": "sb_publishable_xMiWXSwmKl16CeGTadY8iQ_wAqbl7zx"
```

O arquivo de configuração original do pacote é JSON sem comentários. Se você adicionou comentários ou vírgulas finais, o atualizador recusará a edição sem modificar o arquivo; nesse caso, insira as três propriedades acima dentro de `vars` manualmente. Esta configuração usa o ambiente padrão do Worker, sem `--env`.

## 2. Preparar o projeto Supabase

Abra seu projeto no [painel Supabase](https://supabase.com/dashboard/project/fjsdjlqktrkyuxbenzup).

1. Em **Authentication**, mantenha o provedor de e-mail habilitado e a confirmação de e-mail ativada.
2. Na configuração geral da autenticação, desative **Allow new users to sign up**. O Synapse criará identidades pelo servidor somente depois de validar a instalação ou as regras de convite/cadastro. A chave publicável não deve permitir criar contas diretamente fora desse fluxo.
3. Em **Settings → API Keys**, encontre ou crie uma **Secret key**, com prefixo `sb_secret_`. Ela é diferente da chave publicável enviada anteriormente.

Nesta integração não há callback do navegador para o Supabase nem necessidade de configurar o SMTP padrão do Supabase. Os links enviados pelo Synapse usam o seu `PUBLIC_ORIGIN` e o Resend já configurado no Worker. Não desative a confirmação para contornar a falta de e-mail.

## 3. Guardar a chave privada na Cloudflare

Na mesma pasta do projeto, execute:

```bat
npx wrangler secret put SUPABASE_SECRET_KEY --name synapsesus
```

Quando o terminal pedir o valor, cole a chave `sb_secret_` do projeto Supabase e confirme. Não coloque essa chave no código, no GitHub ou nesta conversa. A alternativa pelo painel é abrir o Worker `synapsesus`, ir a **Settings → Variables and Secrets**, adicionar `SUPABASE_SECRET_KEY` com tipo **Secret** e salvar.

Mantenha os secrets `ADMIN_ENCRYPTION_KEY`, `SETUP_TOKEN`, `RESEND_API_KEY` e `TURNSTILE_SECRET_KEY` já configurados. Não gere uma nova chave de criptografia administrativa por causa desta atualização.

## 4. Aplicar a migração e publicar

Execute:

```bat
npm run check
npm test
npm run deploy
```

`npm run deploy` verifica a configuração, aplica as migrações no D1 remoto e publica o Worker. Ele não cria outro banco nem outro bucket. Se o Wrangler solicitar login, entre na conta Cloudflare que já contém `synapsesus`.

Para continuar usando a publicação automática pelo GitHub, envie as pastas atualizadas e o **seu** `wrangler.jsonc` após executar o atualizador. O comando de deploy do Workers Builds deve ser `npm run deploy`, para aplicar as migrações antes de publicar. Não envie `node_modules`, `.private`, `.dev.vars`, `.bak` nem chaves privadas. A chave publicável pode estar no repositório.

## 5. Conferir no site

1. Abra [a instalação](https://synapsesus.adielrodriguesdemorais793.workers.dev/instalar). Se ainda não existe uma conta responsável, use o mesmo código privado de instalação e crie a conta.
2. Abra o link de confirmação recebido por e-mail. Se perder a sessão antes de confirmar, use “Esqueci minha senha” com seu e-mail: enquanto a conta estiver pendente, esse formulário reenvia a confirmação. Se não chegar, confira o remetente e a configuração Resend; o Supabase não envia esse link nesta integração.
3. Entre em [administração](https://synapsesus.adielrodriguesdemorais793.workers.dev/admin), configure o autenticador e teste sair e entrar novamente.
4. Teste a recuperação de senha pelo site. Só depois de confirmar o acesso administrativo, remova `SETUP_TOKEN` da hospedagem.

Os cadastros públicos permanecem sujeitos às regras do painel, convites, antiautomação e verificações existentes. Esta atualização não abre os cadastros automaticamente, não desativa a verificação de idade e não remove o segundo fator administrativo.

Os testes do pacote usam serviços simulados e o ambiente local. O teste real com a chave privada, o domínio público e a entrega de e-mail precisa ser feito depois da publicação. Os limites gratuitos dos provedores continuam valendo; esta mudança resolve a incompatibilidade do cálculo de senha, sem prometer capacidade ilimitada ou ausência de custos futuros.

Referências oficiais: [chaves da API](https://supabase.com/docs/guides/getting-started/api-keys), [criação administrativa de usuários](https://supabase.com/docs/reference/javascript/auth-admin-createuser), [configuração de autenticação](https://supabase.com/docs/guides/auth/general-configuration).

## Contas antigas e limpeza

Contas locais que já existiam não são vinculadas por coincidência de e-mail. Com o Supabase ativado, devem usar a recuperação de senha do Synapse para comprovar acesso ao e-mail e criar uma identidade nova. Se esse e-mail já existir no Supabase, a migração é recusada; o responsável precisa verificar a identidade antes de resolver o conflito. Não exclua contas de outra pessoa para contornar esse aviso.

Uma criação externa que não foi confirmada no D1 fica numa fila durável de limpeza, com espera de uma hora para evitar conflito com uma criação em andamento. Exclusões de contas também ficam nessa fila em caso de indisponibilidade; o cron existente tenta novamente. Não remova o cron nem a chave privada enquanto houver trabalho pendente. As sessões do Synapse são locais: alterações feitas diretamente no painel Supabase exigem revogar também as sessões locais pelo painel Synapse.

Verificação de configuração em 28/10/2026: o endpoint público do projeto respondeu HTTP 200 à chave publicável informada; o provedor de e-mail e a confirmação estavam ativados, mas os cadastros diretos do Supabase ainda estavam permitidos. Essa consulta não testou login, a chave secreta nem envio de e-mail. Siga a etapa 2 para desativar os cadastros diretos.
