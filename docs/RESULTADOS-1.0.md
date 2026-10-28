# Synapse Discovery 1.0 RC1 — verificações e limites

Entrega preparada em 28/10/2026. Esta é uma migração de runtime e persistência, não uma implantação já realizada na conta do proprietário. O identificador RC1 significa candidato de lançamento; não certifica abertura geral.

## Evidências desta entrega

- **64 testes automatizados passaram**: autenticação, convites concorrentes, recuperação de senha de uso único, suspensão, exportação/exclusão, 2FA e recuperação, permissões de moderação, privacidade de perfis/mídias/mensagens, suporte, aferição assinada, fila de e-mail, migração e processamento de imagens.
- **16 verificações no runtime workerd/Miniflare passaram**, usando as implementações locais de D1 e R2: assets, servidor, instalação inicial, PBKDF2 de 600 mil iterações, login, sessão/CSRF, publicação, imagem JPEG reencodificada, acesso privado e bloqueio administrativo.
- **Interface Chromium validada**: login e publicação pelo navegador; confirmação de e-mail a partir da fila LOCAL; matrícula TOTP e abertura do painel; oito áreas administrativas (usuários, publicações, denúncias, convites, crescimento, configurações, lançamento e sistema). Nenhum erro de JavaScript foi capturado.
- **18 combinações de página/largura**: rede, apresentação, instalação, segurança, operação e administração; 360, 768 e 1440 pixels; sem rolagem horizontal da página.
- Empacotamento com Wrangler `--dry-run` concluído. Nenhum upload/deploy remoto foi executado.

Os testes Node usam SQLite real e criptografia real. R2 e Resend são simulados nos testes unitários indicados; o teste workerd usa D1/R2 locais. O emissor etário usado em testes é fictício. A confirmação local obtém um link criptografado da fila; não comprova entrega de e-mail.

Os testes de navegador usaram HTTP local, Chromium 153 e contas fictícias. Não houve navegador HTTPS do domínio final, dispositivo físico, envio Resend real, desafio Turnstile real, aferidor etário comercial, restauração na conta Cloudflare, teste de carga de produção ou auditoria independente. O ambiente de execução exigiu um ajuste externo de detecção de interfaces de rede para iniciar as ferramentas; esse ajuste não integra o aplicativo entregue.

## Comparação com o pacote Python 0.9

| Área | Edição Cloudflare RC1 |
|---|---|
| Contas, perfis, fotos, galerias, stories de foto/texto | Implementados no Worker e D1/R2 |
| Curtidas, comentários, mensagens, coleções e busca social | Implementados; permissões e perfis privados aplicados no servidor |
| Administração, 2FA, denúncias e suporte | Implementados; mensagens não denunciadas não têm leitura geral no painel |
| Persistência | D1 para registros; bucket R2 privado para mídias; sem banco ativo no filesystem efêmero |
| E-mail | Fila criptografada e envio pela API HTTPS do Resend; SMTP antigo não é usado |
| Aferição etária | Contrato Ed25519 preservado; depende de fornecedor/adaptador real. Menores sem acesso social |
| Vídeos novos e transcodificação FFmpeg | Desativados nesta edição; arquivos antigos são preservados pela migração |
| Chamadas e notificações push | Desativadas; recursos antigos continuam no código Python arquivado |
| Pesquisa web dentro do app | Não migrada; atalhos para buscadores permanecem |
| Backup criptografado agendado do Python | Não migrado. Usar D1 Time Travel, exportações e cópia R2; cópia externa não é agendada pelo pacote |
| Android | Fonte anterior preservada em legacy; nenhum APK/AAB novo compilado |

O pacote mantém `legacy/` para consulta e recuperação. Não substitua uma instalação ativa sem cópia e sem executar a migração descrita no guia. Não é uma atualização compatível por simples substituição de `server.py`.

## Configurações que continuam sendo do proprietário

D1 e R2 reais, domínio/origem HTTPS, secrets exclusivos, remetente Resend autorizado, Turnstile do domínio, aferidor etário compatível, responsável e canais de atendimento, políticas revisadas, testes de restauração e operação. A checklist separa configuração, evidência técnica e declaração do responsável; não declara conformidade jurídica nem entrega na caixa postal por conta própria.

A configuração de CPU do pacote pressupõe Workers Paid. Nada foi contratado, cobrado ou publicado por esta entrega. Limites por padrão: fotos JPEG/PNG até 3 MB e 4 megapixels; 100 MiB por usuário e 5 GiB de mídias totais. `USER_MEDIA_LIMIT_BYTES` e `SITE_MEDIA_LIMIT_BYTES` podem ser definidos pelo operador conforme capacidade e custos. Esses tetos de aplicação não são tetos de cobrança da Cloudflare.

## Reproduzir

```bash
npm ci
npm run build
```

O build executa sintaxe/configuração, testes automatizados e workerd local, sem tocar recursos remotos.

Para interface:

```bash
npx playwright-core install chromium
npm run test:browser
```

O teste de navegador cria recursos locais temporários. Um Chromium já instalado pode ser indicado em `CHROMIUM_EXECUTABLE`. A reprodução depende das bibliotecas do sistema e da disponibilidade de download do navegador. Consulte README para uso local e `CLOUDFLARE.md` para publicação.
