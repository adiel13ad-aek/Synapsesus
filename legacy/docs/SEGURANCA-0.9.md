# Segurança, privacidade e operação — Synapse 0.9

## Controles adicionados

**Visibilidade:** perfil privado exige aprovação; a proteção é aplicada ao estado inicial,
feed paginado, stories, anexos e imagens de perfil/capa, não apenas à interface. Nome e
usuário de uma conta podem continuar aparecendo para membros habilitados encontrarem
pessoas. Comentários publicados no post de outra pessoa seguem a visibilidade desse post.
Tornar um perfil privado não recupera cópias anteriormente feitas.

**Contas:** produção exige e-mail confirmado, ativação etária e aceite dos Termos atuais
antes de escrever conteúdo social. Sessões usam cookie HttpOnly/SameSite e podem ser
encerradas pelo titular. Há limite de dez sessões; novas sessões substituem as mais
antigas acima do limite. A lista não armazena localização. O segundo fator é exigido
para administração, não foi adicionado como MFA geral de todas as contas.

**Cadastro:** Turnstile validado no servidor, limites de frequência, bloqueio de origem,
CSRF e exigência de tipos de conteúdo. Respostas do fornecedor são conferidas para
hostname e ação. Isso não elimina bots, ataques distribuídos ou abuso de contas legítimas.

**Recuperação:** links de e-mail usam fragmento e são trocados por hash no banco; apenas a
mensagem cifrada da fila contém o link para entrega. Tokens vencidos ou substituídos não
são enviados. Há até seis tentativas por mensagem; erros ficam em código genérico sem
resposta bruta do SMTP. Mensagens enviadas têm conteúdo da fila apagado. Metadados de
mensagens concluídas são removidos após 14 dias pela rotina do servidor.

**Operação:** diagnóstico de banco/espaço, limitação de armazenamento, requests com ID,
falhas sem stacktrace para o cliente, cópia criptografada consistente, rotinas de limpeza,
fila de suporte e permissões administrativas preservadas. Backups não têm URL pública.

## Limites e trabalhos não concluídos

- Sem auditoria independente, pentest ou teste de carga de produção. Os testes são
  regressões específicas, não provas de ausência de vulnerabilidades.
- Uma instância/um worker; estado em SQLite e arquivos locais. Sem cluster, réplica,
  recuperação multi-região ou tolerância a falha de hospedagem automática.
- Mensagens sem criptografia de ponta a ponta. Operadores do servidor têm acesso técnico
  ao banco; o painel não dá leitura geral das conversas. Mensagens denunciadas podem ser
  analisadas para moderação conforme regras existentes.
- O método de aferição de idade não está integrado a fornecedor real. Vínculo de responsável
  não atesta parentesco. Adequação integral do público menor não foi certificada.
- Conteúdo não passa por análise automática confiável de segurança infantil ou de todos
  os tipos de mídia. A plataforma depende de uma operação humana de moderação e suporte.
- Uploads de vídeo passam por FFmpeg/FFprobe com formatos permitidos, mas não há sandbox
  de processo especializado nem antivírus de arquivos. Restrinja recursos da hospedagem,
  aplique atualizações e teste arquivos antes de ampliação de tráfego.
- Quotas verificam reserva de espaço por solicitação; não são contabilização distribuída.
  Monitore disco, memória e processamento. O suporte a escalabilidade precisa de nova
  arquitetura antes de várias instâncias ou grandes volumes.
- Busca web integrada, chamadas e push exigem serviços/configuração externos e não foram
  testados ao vivo. Nesta entrega, nenhuma conta externa foi acessada ou alterada.

## Responsabilidades antes da abertura

Definir público, responsável pela operação, canais monitorados, políticas reais de
moderação/privacidade/retenção, tratamento de denúncias e recursos. Revisar a adequação
legal conforme serviço, público e jurisdição. Realizar aferição confiável sem coletar
mais dados que o necessário. Testar o domínio com HTTPS, CSP, cookies, recuperação e
restauração. Controlar contratos, gastos e acesso dos fornecedores.

Um modo adulto por padrão é uma configuração do produto, não uma declaração de isenção
legal. Um convite não substitui proteção de público. Não envie documentos, senha ou token
para a equipe por mensagens. Caso precise analisar conteúdo ilegal, estabeleça um
procedimento especializado e seguro, não compartilhe indiscriminadamente.

## Diante de incidente

Feche novas inscrições; pause uploads ou coloque a instalação em manutenção quando
necessário. Preserve registros mínimos de forma privada e revogue sessões/credenciais
comprometidas. Identifique escopo e comunique envolvidos/autoridades quando aplicável
com orientação adequada. Corrija em ambiente separado e restaure somente após validar
integridade, permissões e dados posteriores à cópia. Não publique bancos ou backups
como parte de um pedido público de ajuda.

O endpoint `/.well-known/security.txt` oferece um contato quando configurado. Isso não
instala monitoramento externo nem garante tempo de atendimento.
