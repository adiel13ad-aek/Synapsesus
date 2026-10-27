# Segurança e privacidade — piloto privado 0.4

## Controles implementados

Senhas são derivadas com PBKDF2-SHA256 e salt; cookies de sessão são HttpOnly/SameSite Strict e Secure quando PUBLIC_ORIGIN é HTTPS. Tokens de sessão e de confirmação/reset são armazenados em hash. Há proteção CSRF nas mutações autenticadas, verificações de origem, limitação local de requisições, autorização por dono/participante, escape de conteúdo, cabeçalhos CSP e validação de URLs. Imagens são decodificadas/reencodificadas, não aceitas como scripts/SVG arbitrários, com limites por arquivo/pixels. Isso não significa segurança garantida ou auditoria independente.

Dados do perfil e posts são públicos. Links de fotos e capas podem ser acessados por quem conhecer seu URL, inclusive fora da sessão. Coleções/anotações são privadas por autorização da API, mas não cifradas individualmente no banco. Mensagens só são mostradas aos participantes, sem criptografia ponta a ponta. Um administrador do servidor com acesso ao banco pode ler dados. Fotos privadas e material sensível não devem ser usados neste beta.

Confirmação de e-mail é implementada, mas não é requisito para publicar nesta versão. Identidade e idade não são verificadas. Não há MFA, CAPTCHA, antivírus de upload, reputação anti-spam ou proteção industrial contra abuso. Bloqueios não impedem alguém de abrir outro perfil ou consultar conteúdo público sem login.

## Dados e retenção

Excluir conta remove registros ativos associados, inclusive as mensagens de suas conversas no banco deste protótipo, além das mídias da conta. Exportar produz JSON, não arquivo com todos os bytes das fotos. Cópias já salvas por outras pessoas, backups e arquivos de log não são automaticamente apagados. O operador precisa definir retenção, direitos e rotina de limpeza antes do lançamento. Stories expiram em 24h e a remoção física é acionada por consultas posteriores, não por serviço agendado permanente.

O modo de e-mail `file` contém tokens confidenciais em `.eml` fora do diretório web. Arquivos são criados com permissões restritas quando o sistema permite. Há limpeza por idade nas próximas emissões e remoção dos arquivos correspondentes na exclusão da conta. Não é um sistema real de e-mail. Com SMTP, o provedor terá acesso aos dados necessários para entrega.

## Moderação

Fila manual, restrita a usuários em ADMIN_HANDLES. Crie/proteja essas contas ANTES de configurar a lista. Denúncias podem remover post/comentário/story/mensagem ou suspender perfil. Não há equipe, classificação automática ou resposta de emergência. Ter uma fila não é cumprir todas as políticas da Play.

## Antes de expor à internet

Configure HTTPS e PUBLIC_ORIGIN corretamente; nunca publique o servidor de desenvolvimento diretamente. Revise confiança em proxy/IP e substitua o limitador por IP em memória por proteção apropriada. Coloque limites e monitoramento no proxy de entrada, controle tráfego, revise dependências e teste backup/restauração. Para escala, substitua o modo de um processo/SQLite e adicione paginação, serviços de armazenamento, filas e testes de carga. Mantenha permissões de arquivo, segredo SMTP/API e assinatura Android fora do repositório. Faça revisão independente de autorização, upload, exclusão, CSRF/XSS, abuso, reset e retenção.

As páginas legais fornecidas são rascunhos técnicos para teste privado; não certificam conformidade legal nem aprovação da loja. Defina operador, suporte, público-alvo, responsável de segurança infantil e procedimentos antes de coletar dados do público.
