> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Synapse 0.7 — implantação e lançamento controlado

**Este guia prepara uma implantação, não confirma uma implantação feita.** O pacote permanece local. O Control Center funciona com o servidor; o HTML de demonstração não substitui hospedagem, banco ou contas compartilhadas.

## 1. Escolha uma instalação persistente

Esta versão usa SQLite e mídias em disco, com **uma instância e um processo**. Não a escale horizontalmente. Não há benchmark de capacidade nem garantia de público suportado. Comece por um piloto, monitore uso e teste carga antes de ampliar. Migração para banco e armazenamento distribuídos continua sendo trabalho futuro se o volume exigir.

No Render, use um web service com Docker e disco persistente em `/app/data`. `render.yaml` já descreve essa estrutura, mas serviço e disco são recursos pagos. Não houve contratação. Um serviço gratuito com sistema de arquivos efêmero não é um local seguro para este banco e os uploads: eles podem desaparecer ao reiniciar/reimplantar. Não publique este projeto como Static Site.

Fonte: https://render.com/docs/disks e https://render.com/docs/free (consultadas em 27/10/2026).

## 2. Preparar o repositório

Envie o conteúdo da pasta do projeto ao repositório, incluindo `Dockerfile`, `requirements*.txt`, `server.py`, `features.py`, `administration.py`, `manage.py`, `schema.sql` e `web/`. O `.gitignore` exclui dados e segredos, mas **revise o que está sendo enviado**.

Nunca envie `.env`, `data/`, bancos, e-mails de recuperação, chaves `.key/.pem`, backups ou credenciais. O ZIP desta entrega não contém uma instalação com contas reais.

No painel da hospedagem, crie o serviço conectado ao repositório. Revise custo e região antes de confirmar. Use uma única instância, disco persistente, health check `/api/health` e domínio HTTPS. O pacote não conecta automaticamente sua conta GitHub/Render.

## 3. Variáveis privadas

Defina no painel privado da hospedagem, nunca no JavaScript:

```dotenv
SYNAPSE_ENV=production
SEED_DEMO_DATA=0
PUBLIC_ORIGIN=https://SEU_DOMINIO
SYNAPSE_DB=/app/data/synapse.db
SYNAPSE_MEDIA=/app/data/media
MAIL_MODE=smtp
SMTP_HOST=HOST_DO_SEU_PROVEDOR
SMTP_PORT=587
SMTP_FROM=REMETENTE_VALIDADO_NO_PROVEDOR
SMTP_USER=USUARIO_DO_PROVEDOR
SMTP_PASSWORD=SEGREDO_DO_PROVEDOR
OPERATOR_NAME=NOME_REAL_DO_RESPONSAVEL_OU_ORGANIZACAO
SUPPORT_EMAIL=SUPORTE_MONITORADO
CHILD_SAFETY_EMAIL=CONTATO_MONITORADO
ADMIN_ENCRYPTION_KEY=CHAVE_GERADA_UMA_UNICA_VEZ
```

O SMTP usa TLS direto em 465 ou STARTTLS em outras portas configuradas. Não há serviço de e-mail incluído. Confirme remetente, autenticação e regras de entrega do provedor escolhido.

Gere a chave administrativa no console privado:

```sh
python manage.py admin-key
```

Guarde a chave em `ADMIN_ENCRYPTION_KEY` e uma cópia externa segura. **Não gere outra chave a cada deploy.** Ela protege os segredos do autenticador; perdê-la impede descriptografar esses segredos. No modo local, a chave automática fica em `data/admin-development.key`; não é uma chave de produção compartilhada pelo pacote.

Fernet: https://cryptography.io/en/stable/fernet/.

## 4. Criar sua conta responsável sem deixar a primeira inscrição tomar o controle

Opção A, console da hospedagem com o disco montado:

```sh
python manage.py create-operator --handle SEU_USUARIO --email SEU_EMAIL --name "SEU NOME"
```

A senha é solicitada sem aparecer na tela. Escolha pelo menos 16 caracteres, exclusiva para este serviço.

Opção B, primeiro bootstrap no ambiente privado:

```dotenv
BOOTSTRAP_HANDLE=SEU_USUARIO
BOOTSTRAP_EMAIL=SEU_EMAIL
BOOTSTRAP_PASSWORD=UMA_SENHA_FORTE_E_EXCLUSIVA
```

Use também OPERATOR_NAME. O bootstrap só cria uma conta nova quando não há operador. Ele não assume uma conta preexistente só porque tem o mesmo nome. Depois de criar a conta, **remova a variável BOOTSTRAP_PASSWORD** e as demais de bootstrap. Nenhuma senha padrão é fornecida.

Confirme o e-mail pelo link entregue e entre em `https://SEU_DOMINIO/admin`. Configure o autenticador e guarde os códigos de recuperação. Se o e-mail falhar, veja os registros privados e use reenviar; não marque o banco como verificado para contornar o processo de produção.

## 5. Proxy, origem e HTTPS

O servidor verifica o Host contra PUBLIC_ORIGIN e aceita gravações somente de origem permitida, com cabeçalhos próprios e token de sessão. Cookies passam a ser Secure quando PUBLIC_ORIGIN começa com HTTPS. O proxy público precisa preservar o Host correto.

`FORWARDED_ALLOW_IPS` deve conter somente IPs/CIDRs de proxies realmente confiáveis. Não use `*` numa origem acessível diretamente por clientes. Caso o proxy não seja confiado, diversos visitantes podem compartilhar a mesma chave de limite por IP. Verifique a infraestrutura do seu provedor antes de ajustar essa variável.

Para o Compose + Caddy fornecido, as redes usam IPs fixos: app `172.30.42.3`, proxy `172.30.42.2`. Use `FORWARDED_ALLOW_IPS=172.30.42.2`. Se essa sub-rede conflitar com sua rede, altere os endereços do Compose e a variável juntos. O app publica a porta 8000 somente em loopback; as portas públicas são 80/443 do Caddy.

```sh
docker compose -f compose.yaml -f compose.https.yaml up -d --build
```

Defina também DOMAIN (somente o hostname), aponte o DNS, confira firewall e emissão do certificado. **A configuração Docker/Caddy não foi executada neste ambiente.**

Fonte: https://fastapi.tiangolo.com/advanced/behind-a-proxy/.

## 6. Antes de abrir os cadastros

No Control Center:

- Remova exemplos em Sistema sem apagar contas reais.
- Publique Termos, Privacidade e Regras adequados à sua operação. Os textos existentes são rascunhos. Não basta mudar uma variável de ambiente.
- Realize cadastro/entrada/confirmação/recuperação, postagem, denúncia, bloqueio e exclusão em uma conta de teste no domínio HTTPS.
- Faça backup, copie-o para fora do servidor e restaure-o em uma pasta nova de teste.
- Defina responsáveis por suporte, moderação, recursos e segurança infantil.

Registre as verificações reais na aba Lançamento. As quatro verificações operacionais são declarações suas, não testes executados automaticamente. O painel não permite abrir cadastros em produção enquanto houver pendências na checklist. Configuração pronta não comprova ausência de vulnerabilidades nem adequação jurídica. Faça revisão independente antes de exposição ampla.

Abra primeiro para poucas pessoas convidadas e acompanhe os primeiros incidentes. Não deixe crianças/adolescentes como únicos responsáveis por contratos, dados pessoais ou atendimento: organize a operação com um adulto responsável e apoio apropriado.

## 7. Backup, restauração, limpeza e atualização

Pare o processo da aplicação antes do backup. O comando exige `--server-stopped` como confirmação; ele **não para o processo por você**.

```sh
python manage.py backup /CAMINHO_PRIVADO/synapse-backup.zip --server-stopped
python manage.py restore /CAMINHO_PRIVADO/synapse-backup.zip --into /PASTA_NOVA_PRIVADA --server-stopped
```

O backup contém banco e mídias; não inclui `.env`, credenciais SMTP nem a chave ADMIN_ENCRYPTION_KEY. Guarde os segredos separadamente. A restauração verifica hashes e integridade, recusa caminhos desconhecidos e não sobrescreve uma pasta existente com dados. Sessões, tokens, assinaturas push, chamadas e concessões administrativas antigas são invalidados.

Em Docker, com a imagem construída e o serviço app parado, um exemplo é:

```sh
docker compose stop app
docker compose run --rm --no-deps app python manage.py backup /app/data/backup-UNICO.zip --server-stopped
docker compose start app
```

Troque o nome a cada cópia, transfira o arquivo para fora do disco e defina retenção. Uma cópia no mesmo disco não protege de perda da hospedagem. O arquivo de backup é privado e não deve ir para o repositório.

Execute periodicamente pelo agendador do seu servidor:

```sh
python manage.py cleanup
python manage.py check
```

A rotina cleanup remove sessões/tokens expirados, stories expirados, uploads antigos não publicados e arquivos temporários antigos. **Nenhum agendamento externo foi criado nesta entrega.** Defina frequências e retenções coerentes com suas políticas.

Atualize código apenas após backup e testes em uma cópia; a migração adiciona as tabelas administrativas. Verifique SQLite e mídias e mantenha um plano de retorno. Retornar para código antigo com o banco alterado deve ser validado antes; não há downgrade automático garantido.

## 8. Limitações que não devem ser anunciadas como concluídas

Não há publicação feita, entrega SMTP real validada, HTTPS/proxy de hospedagem validado, teste de carga, auditoria independente, política jurídica certificada, operação de moderação contratada ou APK compilado. Busca Brave, Web Push e chamadas continuam dependentes de configuração e validação externa. Chamadas são experimentais e ficam desligadas por padrão. Mensagens não têm criptografia de ponta a ponta.

O arquivo render.yaml é uma configuração proposta, não comprovação de deploy. A interface administrativa não expõe todas as conversas, mas quem controla a máquina ainda pode acessar o banco. Os registros administrativos não são imutáveis contra o próprio administrador do banco.

Referências de princípios: https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html e https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html. O uso dessas referências não equivale a certificação OWASP.
