> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Relatórios de testes

O relatório desta entrega é **[TESTES-v0.8.md](TESTES-v0.8.md)**.

O conteúdo abaixo é histórico da versão 0.7 e não descreve uma publicação ao vivo.

# Synapse Discovery 0.7 — verificações desta entrega

Executadas em 27/10/2026. O código foi testado localmente; não há implantação pública, instalação Android, certificação jurídica ou auditoria independente.

## Suíte automatizada de API e componentes

```sh
python -m pytest -q --junitxml=test-results/junit.xml
```

**114 testes aprovados.** Incluem as regressões existentes de contas, permissões, uploads, vídeo, coleções, mensagens e backup, mais controles administrativos, autenticação em duas etapas, abertura controlada e isolamento da área pública.

Verificações novas: visitante e conta comum não acessam dados de gestão; senha, CSRF, expiração e bloqueio administrativo; vetor conhecido TOTP, segredo cifrado, rejeição de reuso e recuperação de uso único; obrigatoriedade de MFA em produção inclusive nos endpoints antigos; validação de Host/origem; suspensão com revogação de sessões; proteção da última conta responsável; permissões reduzidas dos moderadores; ocultação/restauração de post e mídia; somente a mensagem denunciada aparece na moderação; pausa de uploads; manutenção preserva denúncias; fechamento de cadastros; documentos públicos escapam HTML; o cadastro registra o hash do texto de Termos publicado; checklist bloqueia a abertura incompleta e permite abertura somente com as condições registradas; declarações não são transferidas para outra origem; limpeza de exemplos preserva contas reais; nenhuma promoção pelo perfil público; limite de tentativas durável; paginação; logout; limite de corpo sem Content-Length.

O teste de abertura usa configuração SMTP e declarações **simuladas, somente no ambiente de teste**. Ele comprova a lógica de bloqueio/liberação, não entrega real de e-mail, HTTPS público ou revisão de políticas.

Evidências: `test-results/api-v07.txt`, `test-results/junit.xml`.

## Navegador e servidor HTTP real

```sh
python tests/browser_v07.py
```

**13 grupos de verificações aprovados**, incluindo login/configuração TOTP, códigos de recuperação, suspensão, ocultação/restauração, fila de denúncias, cadastros fechados com aviso público, edição de políticas, checklist, histórico, link público de privacidade, bloqueio manual e ausência de erros JavaScript não tratados nos percursos exercitados.

**73 combinações de layout verificadas:** 9 telas administrativas em 5 larguras (320, 390, 768, 1440 e 1920 pixels) e 7 telas sociais em 4 larguras (320, 390, 768 e 1440 pixels). A página não apresentou rolagem horizontal global. Tabelas e navegação podem rolar dentro de suas próprias áreas.

Método: Chromium recebe o HTML por `set_content`, porque a política do navegador do ambiente bloqueia navegação local. Uma ponte de fetch/mídia encaminha as requisições por HTTP real para um subprocesso Uvicorn com o backend e um SQLite temporário. As APIs não são simuladas. Cada navegador de teste usa um cliente HTTP independente para cookies. Isso **não valida o comportamento nativo de cookies Secure/SameSite, o carregamento CSP em uma navegação real ou o proxy de uma hospedagem**; as respostas e seus cabeçalhos têm verificações separadas na suíte de API.

São contas e conteúdos fictícios de teste, removidos com a pasta temporária. A confirmação inicial do e-mail administrativo é preparada no banco como fixture; não é teste SMTP. O teste calcula códigos TOTP como um autenticador, sem utilizar o telefone do usuário. As capturas do painel mostram essas contas de teste, não um site já em produção.

Evidências: `test-results/browser-v07.json`, `test-results/browser-v07.log`, capturas `test-results/admin-*.png`.

## Verificações adicionais

- Sintaxe Python dos arquivos alterados e sintaxe JavaScript de admin/app/features verificadas.
- CSS e demonstração reconstruídos; o asset de demonstração Android é igual ao HTML empacotado, conforme teste automatizado. Isso não é compilação de APK.
- Migração adiciona tabelas administrativas sem excluir as tabelas sociais; nenhuma migração dos dados reais do usuário foi executada.
- Pacote distribuído exclui `.env`, bancos, arquivos de recuperação de e-mail, chaves privadas, backups, caches e ambientes virtuais.

## Não executado ou não comprovado

Não houve hospedagem pública, execução de GitHub Actions, construção Docker, emissão de certificado, teste HTTPS real, entrega SMTP, validação Brave/Web Push/TURN, chamadas com mídia real, teste em aparelho físico, instalador Windows executado no Windows, compilação APK/AAB, auditoria de acessibilidade completa, auditoria independente de segurança, teste de carga, medição de capacidade ou operação de moderação real.

As declarações da aba Lançamento precisam ser preenchidas com verificações realmente realizadas pelo responsável no ambiente final. Não há garantia de ausência de vulnerabilidades nem de adequação jurídica. Comece com um piloto controlado e não anuncie um número de usuários suportados sem medi-lo.
