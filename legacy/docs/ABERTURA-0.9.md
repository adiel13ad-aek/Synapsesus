# Synapse 0.9 — caminho de abertura ao público

**Situação da entrega:** código implementado e testado localmente; nenhum serviço de
hospedagem, envio de e-mail, verificador de idade ou armazenamento externo foi contratado
ou conectado. O servidor não foi publicado nesta etapa. Os caminhos a seguir são para
você executar na sua instalação, não ações já realizadas no seu site.

## 1. Atualize sem perder contas

Pare a instalação antiga e faça uma cópia externa do banco, das mídias e das configurações.
Nunca copie um banco ativo sozinho: use o utilitário de backup da versão anterior com o
servidor parado. Extraia este pacote em uma pasta nova. Preserve a pasta `data`, os caminhos
configurados, `.env` e especialmente a **mesma `ADMIN_ENCRYPTION_KEY`**.

A inicialização adiciona tabelas e colunas sem apagar contas existentes. Ela pode fechar os
cadastros de uma instalação de produção quando detectar requisitos não atendidos. Não
use a versão antiga sobre um banco migrado: para voltar, restaure a cópia anterior em
ambiente separado e verifique-a antes de trocar os caminhos.

Em atualização da 0.8, gere somente a nova chave de backup, uma vez:

```sh
python tools/generate_backup_key.py
```

O resultado fica em `.backup-key.local`. Copie o valor para o ambiente **privado** do
servidor e guarde outra cópia fora da hospedagem. Não altere a chave em cada atualização.

## 2. Execute o servidor correto

Para teste local no Windows: `INICIAR-WINDOWS.bat`, depois `http://localhost:8000`.
O cadastro local não é abertura pública. E-mails ficam no outbox e os testes não comprovam
entrega externa. Para preparar uma primeira implantação, use
`PREPARAR-PRODUCAO-WINDOWS.bat`; ele não cria hospedagem nem substitui chaves existentes.

Para produção, o pacote inclui Docker e `render.yaml`. A configuração de referência é:

| Item | Valor |
|---|---|
| Serviço | Web Service, runtime Docker |
| Arquivo | `Dockerfile` na raiz do repositório |
| Instâncias / processos | 1 / 1 |
| Disco persistente | `/app/data` |
| Banco | `SYNAPSE_DB=/app/data/synapse.db` |
| Mídias | `SYNAPSE_MEDIA=/app/data/media` |
| Health check | `/api/ready` |
| Ambiente | `SYNAPSE_ENV=production` |
| Exemplos | `SEED_DEMO_DATA=0` |
| Endereço | `PUBLIC_ORIGIN=https://SEU-ENDERECO` sem caminho ou barra final |

O Render documenta disco persistente em serviço pago; o sistema de arquivos comum é
volátil. Revise custos antes de contratar. Este pacote não autoriza cobranças. O subdomínio
fornecido pelo serviço pode ser usado antes de comprar domínio próprio. Se você já usa
Cloudflare, ele pode continuar como DNS; publicar somente HTML em Pages não executa este
backend. Um transporte para Workers/D1/R2 exigiria adaptação de arquitetura não feita aqui.

Faça upload do **conteúdo** do projeto para o repositório, não apenas do ZIP. Revise os
arquivos antes de enviar. Nunca publique dados, `.env`, `.backup-key.local` ou backups.
Use armazenamento persistente com permissão de escrita para o usuário do contêiner
(uid 10001); confirme essa permissão antes de receber usuários.

## 3. Configure as integrações privadas

### Responsável e e-mail

Configure `OPERATOR_NAME`, `SUPPORT_EMAIL`, `CHILD_SAFETY_EMAIL`, `MAIL_MODE=smtp`,
`SMTP_HOST`, `SMTP_PORT` (465 ou 587), `SMTP_FROM`, `SMTP_USER` e `SMTP_PASSWORD`.
Use remetente autorizado no seu provedor. Configure também `SECURITY_EMAIL` ou utilize
`SUPPORT_EMAIL` como contato de incidentes. A fila usa TLS no SMTP.

A primeira conta pode ser criada com o assistente local ou com `BOOTSTRAP_HANDLE`,
`BOOTSTRAP_EMAIL` e `BOOTSTRAP_PASSWORD` na primeira inicialização. Remova os valores
`BOOTSTRAP_*` depois que a conta funcionar. **Mantenha `ADMIN_ENCRYPTION_KEY`.**

Confirme o e-mail real, entre em `/admin`, configure o aplicativo autenticador e guarde
os códigos de recuperação. O acesso elevado dura 15 minutos; `/operacao` exige a mesma
permissão de responsável, não cria privilégios novos. Moderadores não gerenciam backups.

Em `/operacao`, envie uma mensagem de teste. Verifique a caixa de entrada e também teste
confirmação e recuperação em uma conta secundária. “Aceito pelo SMTP” não significa
entregue; problemas de remetente, spam e DNS ainda exigem sua verificação com o provedor.

### Antiautomação

No Cloudflare Turnstile, crie um widget para o domínio real. Configure
`TURNSTILE_SITE_KEY` e `TURNSTILE_SECRET_KEY`. A primeira é pública; a segunda fica somente
no servidor. A implementação valida o token, o hostname exato e a ação `signup` no
Siteverify. Ela recusa cadastro quando a verificação falha; não oferece bypass em produção.
As chaves de teste do fornecedor não servem como comprovação de proteção de produção.

### Faixa etária

Configure um serviço externo confiável com adaptador para `docs/INTEGRACAO-IDADE.md`:
`AGE_PROVIDER_URL`, `AGE_PROVIDER_ID`, `AGE_PUBLIC_KEY`.
**Não é suficiente colar a URL de qualquer fornecedor:** o contrato de recibo assinado
deste pacote precisa ser implementado pelo fornecedor ou por um adaptador auditado.
Não há fornecedor pronto, conectado ou validado nesta entrega.

Sem isso, o cadastro pode ser testado por convite, mas os recursos sociais de uma conta
de produção permanecem bloqueados. O projeto não aceita um número digitado ou uma caixa
“tenho 18 anos” como aferição. Não envie documentos pelo chat ou pelo suporte do site.

Mantenha `MINOR_ACCOUNTS_ENABLED=0`. O código de supervisão é uma base técnica restrita;
não comprova parentesco nem todos os requisitos de proteção do público menor. Antes de
admitir esse público, avalie método de aferição, consentimento, conteúdo adequado,
moderação, recursos e obrigações aplicáveis com apoio especializado. `MINOR_SAFETY_REVIEWED`
é somente uma declaração da operação, não aprovação regulatória. Limitar o lançamento
a adultos não é, por si só, uma dispensa das obrigações aplicáveis a serviços de acesso
provável por crianças e adolescentes.

### Backups fora da hospedagem

Configure um bucket privado de armazenamento compatível com S3. Utilize credenciais com
acesso somente ao bucket/prefixo necessários, nunca uma chave de administração geral.

```text
BACKUP_ENCRYPTION_KEY=<chave original, privada, base64url de 32 bytes>
BACKUP_S3_BUCKET=<bucket privado>
BACKUP_S3_ENDPOINT=<HTTPS do endpoint do fornecedor; vazio no S3 padrão>
BACKUP_S3_PREFIX=synapse
AWS_ACCESS_KEY_ID=<chave limitada>
AWS_SECRET_ACCESS_KEY=<segredo>
AWS_DEFAULT_REGION=<região do fornecedor>
AUTO_BACKUP_ENABLED=1
BACKUP_INTERVAL_HOURS=24
BACKUP_LOCAL_KEEP=3
```

Em `/operacao`, crie um ponto de recuperação, espere o resultado registrado pelo servidor
e confirme o objeto no bucket. Faça uma restauração de teste conforme
`docs/RECUPERACAO-0.9.md`. A rotina só roda enquanto o servidor está ativo: um serviço parado
não cria backups. Não confunda o teste local com uma cópia externa funcionando.

## 4. Valide por convite antes de abrir

Use `/admin` para remover exemplos, publicar Termos, Privacidade e Regras **realmente
revisados**, configurar suporte e criar um convite restrito. Não publique os textos
sintéticos dos testes. O convite continua sujeito a antiautomação e à ativação de contas;
não bypassa idade, e-mail, suspensão ou manutenção.

Políticas já publicadas na 0.8 precisam ser revistas e salvas novamente para os novos tratamentos de dados da 0.9. O painel não aceita a revisão antiga como suficiente.

No domínio real, complete o percurso com uma conta de teste autorizada:

1. Cadastro por convite e Turnstile; confirmação recebida por e-mail.
2. Aferição externa e ativação; perfil privado e aceite dos Termos atuais.
3. Publicação, solicitação de seguidor e aprovação em uma segunda conta.
4. Comentário, bloqueio, denúncia e revisão no painel; solicitação de suporte e resposta.
5. Recuperação de senha, encerramento de outra sessão e exclusão de uma conta de teste.
6. Backup externo, restauração isolada e entrada administrativa na cópia restaurada.

O servidor grava evidências de validação do CAPTCHA e da assinatura etária, vinculadas
ao domínio e à configuração. Trocar chaves/emissor invalida essa evidência. As condições
para abertura também incluem um backup externo nas últimas 48 horas e ausência de
falhas definitivas válidas de e-mail. A entrega na caixa, a restauração operacional e a
revisão de público continuam verificações humanas, identificadas no painel.

Aplique políticas de retenção no bucket, monitore a caixa de suporte e estabeleça quem
responderá a denúncias. A ferramenta de moderação não substitui essas pessoas.

## 5. Abra somente após validar o endereço

Execute no seu computador, apontando **apenas para seu site**:

```sh
python tools/check_public.py https://SEU-ENDERECO --output verificacao-publica.json
```

O diagnóstico é somente leitura: testa API, páginas, caminhos privados e indexação. Ele
não se autentica, não testa e-mail nem mede capacidade. `PUBLIC_INDEXING=0` causa a
pendência de indexação durante a preparação; isso é esperado. Não ignore as demais falhas.

Depois dos testes externos e da revisão, a aba Lançamento deve explicar cada pendência.
Quando os requisitos forem atendidos, o responsável pode abrir inscrições em `/admin`.
O servidor não as abre sozinho. Se os requisitos falharem depois, novas inscrições são
recusadas e as páginas públicas deixam de anunciar “cadastros abertos”.

Para visibilidade, use `/bem-vindo` como página de divulgação, configure a verificação
do Search Console, habilite `PUBLIC_INDEXING=1` e envie o sitemap. Indexação e posição
nos resultados não são garantidas por estas configurações. Comece com uma comunidade
pequena, conteúdo próprio útil e convites consentidos; não compre tráfego antes de
comprovar que as pessoas conseguem usar e retornar ao serviço.

## 6. Limites que ainda precisam de trabalho

Não foram realizados deploy, chamada real SMTP/Turnstile/verificador/S3, teste em aparelho,
auditoria independente, revisão jurídica ou ensaio de carga de produção. O site é de uma
instância, não uma infraestrutura de escala semelhante ao Instagram. Sem fornecedor etário
compatível, a integração ainda precisa ser finalizada. Chamadas/push continuam opcionais
sem validação externa; Android legado não foi compilado nem atualizado neste escopo.

## Fontes primárias consultadas em 28/10/2026

- Render — serviço web e disco: https://render.com/docs/web-services e https://render.com/docs/disks
- Turnstile — validação no servidor: https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
- ANPD — orientações e implementação do ECA Digital: https://www.gov.br/anpd/pt-br/assuntos/eca-digital

As fontes informam requisitos externos; não certificam este projeto. O procedimento acima
descreve as escolhas técnicas desta versão, não um parecer jurídico.
