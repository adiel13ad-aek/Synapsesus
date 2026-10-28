> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Synapse Discovery 0.8 — testes executados e limites

## Estado da entrega

Pacote de código para preparar lançamento controlado. Não implantado em contas do usuário; nenhum domínio, servidor, SMTP, Google Search Console ou serviço pago foi configurado de verdade. Não é certificação de segurança, conformidade legal, capacidade de tráfego ou disponibilidade.

## Suíte automatizada de servidor

**142 testes passaram**, incluindo 28 testes/casos novos da 0.8. Comando:

```bash
python -m pytest -q --junitxml=test-results/junit-v08.xml
```

Evidências: `test-results/api-v08.txt` e `test-results/junit-v08.xml`.

Foram testados os fluxos já existentes e as novas páginas públicas, proteção de metadados contra injeção, URL canônica derivada da configuração e não do Host, verificação do Google também na página inicial, sitemap restrito, indexação desligada por padrão, convites, permissões, transação de consumo de vagas, limites, expiração, revogação, suspensão de cadastros em manutenção, mensagens de novas contas restritas a perfis seguidos e métricas sem exportar e-mails dos membros.

A concorrência de consumo de um convite foi testada com quatro conexões locais. Isso **não** é teste de carga da plataforma. A configuração do verificador público foi testada com respostas locais/simuladas, incluindo rejeição de demo HTML e servidor de desenvolvimento. Um resultado positivo simulado não comprova uma implantação real.

A suíte também cobre processamento de vídeo e backups/restauração herdados. Usa bancos temporários e dados fictícios. Nenhum banco real do usuário foi migrado ou restaurado nesta entrega.

## Interface no navegador

**9 grupos de verificações passaram**, com **16 combinações de tela/largura**, sem rolagem horizontal da página. Os textos e capturas usam contas fictícias explicitamente de teste.

- 12 combinações: Bem-vindo, Como funciona e Ajuda em 320, 390, 768 e 1440 px.
- 4 combinações: Convites e Crescimento em 390 e 1440 px.

Fluxos: perguntas expansíveis; criação do convite pelo painel; cadastro com o código enquanto inscrições gerais estão fechadas; verificação da preferência de mensagens; publicação autenticada no backend; métricas refletindo o membro e post criados; revogação pela interface; ausência de erros JavaScript não tratados.

Evidência: `test-results/v08/browser-report.json`. Script: `tests/browser_v08.py`.

### Limitação importante do ambiente de navegador

A navegação direta do Chromium foi bloqueada por política do ambiente. O teste inseriu HTML/CSS/JavaScript reais na página e usou uma ponte HTTP para um servidor Uvicorn/SQLite temporário. Os cookies ficaram no cliente HTTP da ponte. O código do convite foi inserido na memória do cliente de teste, em vez de navegar realmente ao fragmento do link.

Portanto, esse teste **não valida** cookies nativos do navegador, HTTPS real, a aplicação da política CSP na navegação original, abertura direta do link completo de convite, funcionamento do domínio ou SMTP. Esses itens precisam ser repetidos na hospedagem, inclusive em outro navegador/dispositivo. Os testes não usam respostas de API fictícias para simular cadastro bem-sucedido: a ponte executa as operações no servidor local.

## Verificações adicionais

Os módulos Python alterados foram compilados sintaticamente; os arquivos JavaScript modificados passaram em `node --check`; os arquivos YAML foram analisados. A demo e o asset Android foram regenerados, e sua igualdade é verificada na suíte. Não houve compilação APK/AAB, build Docker nem execução de GitHub Actions.

O assistente interativo de configuração foi revisado e verificado sintaticamente, mas não foi usado com credenciais reais. O exportador de apresentação estática foi testado localmente; nenhum deploy no Cloudflare Pages ocorreu.

## O que ainda impede chamar de “100% pronto”

1. Hospedagem pública, domínio/HTTPS e armazenamento persistente ainda precisam ser implantados e validados.
2. Confirmação/recuperação de conta por e-mail real precisam de SMTP e testes de entrega.
3. Aferição de idade, vínculo ao responsável e supervisão parental completos não estão implementados. A declaração de avaliação de público no painel não substitui essas funções ou revisão adequada.
4. Políticas e contatos precisam refletir a operação real; é necessário alguém atender denúncias, suporte e incidentes.
5. O backup externo periódico não está agendado. O utilitário atual exige janela de parada; a opção `--server-stopped` é uma confirmação, não um comando que para o servidor.
6. Busca externa autenticada, Web Push e transmissão de chamadas permanecem sem validação ao vivo. Chamadas permanecem desativadas por padrão; não anuncie esses recursos como concluídos.
7. Não há auditoria independente, teste de carga, certificação de acessibilidade, teste em aparelho físico ou infraestrutura de múltiplas instâncias. Mensagens não têm criptografia de ponta a ponta.

As métricas de Crescimento são agregados do banco: não representam visitantes únicos, retenção ou pessoas online. Os 100% que aparecem na captura pertencem a **uma conta fictícia que publicou um post**, não a resultados de uma comunidade real.

## Próxima validação que deve ser feita pelo responsável

Após publicar, execute `tools/check_public.py` no seu próprio endereço e faça o percurso real de convite → cadastro → e-mail → publicação → comentário por outra conta → denúncia → moderação → exclusão de conta de teste. Faça também restauração do backup fora do servidor ativo. Só registre as verificações no painel depois de realmente realizá-las.
