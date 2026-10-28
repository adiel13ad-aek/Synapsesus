> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Novidades de gestão 0.8

**Convites:** crie códigos com 1 a 50 usos e validade de 1 a 30 dias. O código só aparece ao criar; copie em local privado. Revogar bloqueia cadastros futuros, sem excluir contas existentes. A manutenção bloqueia até cadastros por convite. Convites não são identidade, idade ou consentimento parental.

**Crescimento:** indicadores agregados de contas e posts, sem rastreamento de visitantes. Os nomes das métricas explicam seus denominadores e limites.

**Página pública:** `/bem-vindo`; `PUBLIC_INDEXING=1` somente após revisão do domínio e texto. Contas existentes continuam usando `/`.

**Revisão de público:** a aba Lançamento exige registrar a avaliação das obrigações de privacidade e idade. Não marque como concluído um requisito que ainda não foi implementado.

Para publicação, consulte [LANCAR-AGORA.md](LANCAR-AGORA.md).

---

## Administração existente desde a versão 0.7

# Como gerenciar o Synapse 0.7

## Primeiro acesso

Crie a conta pelo assistente `CONFIGURAR-ADMIN-WINDOWS.bat` no computador que possui o banco correto. Em uma hospedagem, use o console privado ou as variáveis de bootstrap descritas em OPERACAO.md. Criar uma conta no formulário público não concede permissões administrativas.

Acesse `/admin`. Entre com sua conta e configure o autenticador. A chave exibida é um segredo: adicione uma conta do tipo TOTP, SHA-1, 6 dígitos, 30 segundos no aplicativo autenticador. Digite o código atual e guarde os oito códigos de recuperação. Eles são exibidos uma única vez, usados uma única vez e armazenados no banco apenas como hashes.

Em desenvolvimento, o painel permite um teste local com senha. **Em produção, o atalho não existe no servidor:** é necessário e-mail confirmado, senha e código. A autorização administrativa expira em 15 minutos e pode ser encerrada no botão Bloquear, sem sair da conta social.

## Visão geral

Os números vêm das contas reais deste banco, excluindo perfis fictícios do total de pessoas e publicações. O painel mostra pessoas, publicações, denúncias abertas e tamanho das mídias. Não são estimativas de alcance, usuários online ou usuários ativos mensais. “Nenhuma falha de e-mail registrada” não prova que o provedor entregou mensagens.

## Usuários

Busque por nome ou usuário, filtre ativos/suspensos e navegue pelas páginas. Suspenda contas mediante uma justificativa: suas sessões são revogadas e os conteúdos deixam de aparecer no acesso público. Reativar não recria sessões antigas; a pessoa precisa entrar novamente. O comando Encerrar sessões revoga acessos sem suspender a conta.

Somente o responsável pode conceder o papel de moderador a uma conta ativa com e-mail confirmado. Moderadores não veem e-mails na listagem e não podem modificar outro administrador. Transferir a propriedade exige o console de confiança; não há botão público para criar responsáveis. Confira a identidade antes de promover uma conta existente.

## Publicações e denúncias

Ocultar retira uma publicação do feed e bloqueia suas mídias no servidor. Restaurar volta a publicá-la. Uma cópia que alguém já salvou fora do serviço não pode ser recolhida por essa função.

Na fila de denúncias, revise o conteúdo, escolha descartar ou remover e explique sua decisão. A remoção do conteúdo é permanente; em denúncias de perfil, a ação é suspensão. Não use a fila como ferramenta para investigar conversas privadas: só a mensagem denunciada é exibida.

O painel é uma ferramenta de trabalho. Não existe equipe de suporte ou moderação contratada pelo pacote. Defina quem acompanha a fila, os horários de atendimento, os recursos e o contato de segurança infantil.

## Configurações e lançamento

Você pode fechar novas inscrições, habilitar manutenção de leitura, pausar novos arquivos e publicar um aviso de até 300 caracteres. Contas existentes continuam entrando quando só os cadastros estão fechados. A manutenção preserva leitura, denúncias, acesso e controles de exclusão/exportação.

A aba Políticas permite publicar texto simples de Termos, Privacidade e Regras. A publicação é imediata e registrada, sem renderização de HTML fornecido pelo usuário. Os rascunhos antigos continuam sendo servidos até você publicar versões revisadas.

A aba Lançamento separa verificações de configuração de confirmações do responsável. Teste de entrega de e-mail, restauração, definição de atendimento e teste no domínio precisam ser realizados de verdade. Marcar uma verificação não executa o teste e não certifica o serviço. Abrir cadastros em produção só é permitido quando não há pendências registradas.

## Histórico, sistema e cópias

Ações administrativas são registradas com responsável, data e justificativa. A interface não permite editar esses registros. Eles não são uma trilha imutável contra alguém que controla o banco ou a máquina. Defina retenção adequada na política.

A aba Sistema mostra diagnóstico do banco, espaço livre, configuração de recursos e remoção explícita de perfis demonstrativos. Não há botão para baixar todos os dados privados dos usuários. Backups são feitos no console, com o servidor parado, e guardados fora da hospedagem.

## Perdi o autenticador

Use um código de recuperação no campo do autenticador. Sem ele, o responsável pela infraestrutura pode executar:

```sh
python manage.py reset-admin-mfa SEU_USUARIO
```

Esse comando exige confirmação no console, remove o segundo fator e revoga as sessões da conta. Configure um novo autenticador antes de voltar a administrar em produção. A recuperação da senha por e-mail **não remove o segundo fator**.

Não divulgue a senha, os códigos, `.env`, `ADMIN_ENCRYPTION_KEY`, arquivos `.eml` ou o banco. A chave administrativa tem de acompanhar a recuperação do servidor, mas deve ser guardada separadamente do backup distribuído.
