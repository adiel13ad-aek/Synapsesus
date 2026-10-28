# Synapse Discovery 1.0 RC1 — verificações e limites

Entrega preparada em 28/10/2026. Esta é uma migração de runtime e persistência, não uma implantação já realizada na conta do proprietário. O identificador RC1 significa candidato de lançamento; não certifica abertura geral.

## Correção 1 — inicialização e diagnóstico

Reproduzido o erro `Cannot read properties of undefined (reading 'map')` quando `/api/state` recebe HTTP 200 com HTML, em vez de JSON. Esse cenário reproduz a imagem relatada; o endereço público da imagem não foi confirmado.

O cliente agora rejeita respostas HTML/JSON inválido, valida as listas do estado antes de substituí-lo e mostra uma mensagem específica. Nenhum estado vazio de demonstração é inventado. O botão Tentar novamente recupera a interface assim que a API volta a responder corretamente.

A suíte Node atual passou em **78 testes**, incluindo **14 novos testes de regressão** de respostas da API.

A execução atual no Chromium passou em **34 verificações de interface**, além das **16 verificações de runtime local**, sem erros JavaScript capturados. Inclui três falhas de inicialização seguidas de recuperação, preservação do feed após atualização inválida e as 18 combinações de página/largura anteriores. Serviços externos e endereço público continuam fora dessa validação.

## Evidências da entrega RC1 original

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


## Atualização de autenticação Supabase — 28/10/2026

- Credenciais delegadas ao Supabase; D1 mantém perfis, sessões e permissões.
- 101 testes automatizados aprovados (inclui 16 testes Supabase e 3 de concorrência).
- 17 verificações adicionais em workerd com D1/R2 locais e Supabase simulado.
- 16 verificações anteriores de execução local continuam passando.
- PBKDF2 foi substituído por uma função que lança erro nos testes Supabase: nenhum fluxo externo o executa.
- Prova local de e-mail, convites, instalação única, CSRF, papéis, MFA e idade preservados.
- Criações e exclusões externas pendentes ficam em fila durável; recuperação consome o token antes de alterar a senha remota.
- Requisições agora usam redirect manual, suportado pelo Worker, rejeitando redirecionamentos.
- GET público de configuração Supabase respondeu 200; isso não valida a chave secreta, envio de e-mail ou autenticação em produção.
- Nenhum deploy remoto foi realizado, nenhuma conta real foi criada e nenhum e-mail real foi enviado.
- Os testes de navegador anteriormente registrados são da revisão anterior de interface; esta atualização não altera o HTML/JS do navegador.

Veja docs/SUPABASE.md para aplicar a migração D1 e cadastrar o segredo remoto.
