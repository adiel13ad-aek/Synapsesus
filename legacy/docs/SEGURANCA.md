> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Segurança — complemento da versão 0.7

A implementação não foi auditada independentemente. Consulte `OPERACAO.md` e `TESTES.md` para limites e procedimentos.

Novos controles: funções administrativas negadas por padrão; responsável/moderador com verificação a cada requisição; autorização temporária e TOTP obrigatório em produção; recuperação por códigos de uso único; segredo do autenticador cifrado com chave externa; CSRF nas mutações; limites persistentes em produção; corpo HTTP limitado antes de parsing; validação de Host e Origin; contas responsáveis protegidas contra suspensão indevida. Senhas continuam armazenadas com hash lento e sal.

O modo development não deve ser exposto publicamente: ele admite o teste do painel sem MFA e mantém a compatibilidade dos endpoints antigos de moderação para testes locais. Em produção, esses endpoints também exigem autorização administrativa temporária. `SYNAPSE_ENV=production` é parte indispensável da configuração.

As ações do painel não exibem senhas, segredos SMTP ou caixas de mensagens inteiras. Apenas mensagens denunciadas entram na moderação. Isso não impede o administrador da infraestrutura de consultar o banco; não há E2EE. Logs administrativos guardam rótulo do operador e justificativa e precisam de retenção documentada.

Leia também os princípios do OWASP citados em `OPERACAO.md`. Os testes automatizados não equivalem a uma certificação, pentest ou garantia contra abuso/DDoS. A operação continua single-instance e requer manutenção, atualizações, monitoramento, backup externo e moderação humana.
