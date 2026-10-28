# Changelog — Synapse Discovery

## 0.9.0 — preparação de abertura pública, 28/10/2026

### Contas e privacidade
- Perfis privados, solicitação/aprovação/recusa de seguidores e remoção de seguidores.
- Visibilidade aplicada ao servidor para feed, stories, fotos e anexos, não só ao layout.
- Central de segurança com sessões revogáveis, aceite atualizado de Termos e suporte.
- Limite de dez sessões e metadados opacos; nenhum token ou localização na lista.
- E-mail confirmado e ativação etária exigidos em produção para atividade social.
- Integração receptora de sinais etários Ed25519 com desafio vinculado à conta e anti-replay.
- Base restrita de supervisão; menores desabilitados por padrão, sem verificação legal de parentesco.
- Turnstile no cadastro, validado no servidor para domínio e ação; bloqueio em falhas.

### Operação
- Página `/operacao` para responsável elevado: e-mails, backups, suporte e lançamento.
- Fila SMTP persistente e cifrada, até seis tentativas, descarte de links substituídos/expirados.
- Links de confirmação e recuperação em fragmento, removidos da barra de endereço.
- Snapshot consistente de SQLite/mídias em uma instância, arquivo AES-256-GCM e envio S3 opcional.
- Restauração autenticada em pasta separada; sessões/filas invalidadas, manutenção ligada.
- Check de readiness, `security.txt`, reserva de espaço e erros sanitizados com protocolo.
- Revisão de políticas desta versão exigida; evidências ligadas ao domínio e configuração.
- Páginas públicas não anunciam inscrições abertas quando os requisitos estão pendentes.
- Guias de implantação, aferição, recuperação e operação atualizados.

### Verificado
- 183 testes automatizados e 11 grupos de UI por ponte HTTP; oito combinações responsivas.
- Nenhum deploy, integração externa ao vivo, auditoria independente ou APK foi executado.

## Histórico

A base 0.8 preservada contém rede social, painel administrativo, convites, páginas públicas
e código Android/demo legados. A atualização 0.9 se concentra no site real e sua operação;
ela não transforma a demo ou o projeto Android antigo em aplicativo nativo pronto.
