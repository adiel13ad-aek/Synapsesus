# 1.0.0-rc.1 — correção 1 de inicialização

- Rejeita respostas HTML e JSON inválido em rotas de API, inclusive com HTTP 200.
- Confere as listas do estado antes de substituir dados válidos da interface. Não simula uma rede funcional com dados vazios.
- Corrige a tela de erro e a recuperação pelo botão Tentar novamente; remove a orientação genérica de iniciar um servidor local.
- Atualiza o cache da interface, acrescenta testes de regressão e amplia o guia de configuração de e-mail, Turnstile e diagnóstico da hospedagem.
- Esta correção não publica um Worker nem cria uma integração etária comercial.

# 1.0.0-rc.1 — Cloudflare

Migração da base 0.9 para Worker JavaScript com D1 e R2 privado, preservando a interface e os principais contratos da API. A versão Python permanece em legacy/.

- Instalação do primeiro responsável por token privado de uso único; nenhum administrador ou senha predefinidos.
- Senhas compatíveis com PBKDF2 anterior; sessões e limites persistentes; 2FA cifrado em AES-GCM e bloqueio contra reutilização de códigos.
- Imagens JPEG/PNG decodificadas e reencodificadas sem EXIF/comentários; validação de chunks PNG, limites de pixels e quotas atômicas. Exclusões com repetição durável.
- Fila criptografada de e-mail com envio por API, tentativas e idempotência; cron e disparo após enfileiramento.
- Perfis privados, aprovação de seguidores, bloqueios, suporte e moderação aplicados pela API.
- Scripts de migração preservam dados sociais e convertem 2FA; invalidam sessões e comprovantes antigos e deixam cadastro fechado.
- GitHub/Workers Builds com validação automatizada e migrations antes do deploy; GitHub Actions opcional com publicação manual.
- Guias de publicação, migração e evidências incluídos. Nenhuma alteração remota foi efetuada.

Consulte docs/RESULTADOS-1.0.md para diferenças de recursos e validações ainda necessárias. RC1 não representa certificação de produção nem garante que a comunidade possa abrir antes da configuração real.
