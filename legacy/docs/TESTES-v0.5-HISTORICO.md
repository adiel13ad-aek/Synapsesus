> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Testes executados — Synapse Discovery 0.5

Data: 27/10/2026. Testes do código entregue, não certificação de segurança, escala, publicação ou funcionamento em aparelhos físicos.

## API e administração — 76 testes aprovados

Comando: `python -m pytest -q --junitxml=test-results/junit.xml`.
Resultado da execução final: **76 passed in 17.37s**. O relatório XML está em `test-results/junit.xml`.

Mantidos os 48 testes de cadastro, autenticação, autorização, perfis, publicações, imagens, curtidas, comentários, seguidores, mensagens, coleções, exportação/exclusão, confirmação e recuperação de e-mail, stories, notificações e moderação. Acrescentados 28 testes para galerias, vídeos reais processados pelo FFmpeg, mídia privada antes da publicação, limites, exclusão de arquivos, paginação, papéis de operador, bloqueio de configuração incompleta de produção, restrições de push, sinalização de chamadas e backup/restauração.

A restauração foi exercitada em pasta temporária com banco e mídia reais de teste, incluindo invalidação de sessões e rejeição de caminhos inseguros. O vídeo foi gerado localmente e realmente transcodificado; verificados miniatura, acesso e resposta HTTP Range.

Entregas SMTP, busca externa e gateway de push foram simuladas nos testes que as exercitam. O teste de sinalização de chamadas NÃO representa uma chamada de áudio/vídeo concluída.

## Interface — 9 verificações agrupadas aprovadas

Comando: `python tests/browser_v05.py` após `python build_demo.py`.

1. Cadastro, login automático e personalização pela interface real.
2. Envio real de duas fotos, publicação e navegação do carrossel.
3. Curtida e comentário preservados após atualização da galeria.
4. Upload, transcodificação, miniatura e carregamento do vídeo no feed dedicado.
5. Tema e movimento reduzido persistidos; push não configurado informado sem falsa ativação.
6. Segunda conta independente no layout móvel.
7. Mensagens bidirecionais entre dois contextos de navegador e contas independentes, com atualização periódica.
8. 28 combinações sem rolagem horizontal: sete telas em 320, 390, 768 e 1440 pixels.
9. Nenhum erro JavaScript não tratado nos percursos exercitados.

O JavaScript rodou em Chromium com uma ponte de transporte para o FastAPI TestClient e SQLite temporário real. A navegação HTTP direta era restrita neste ambiente; o transporte foi adaptado, não os endpoints sociais. O arquivo HTML foi carregado no documento de teste e o modo servidor ativado. Formulários multipart, autorização, persistência e processamento de mídia passaram pela implementação real do servidor.

As sete telas são feed, explorar, coleções, perfil, mensagens, atividade e configurações. Isso não é uma auditoria completa de acessibilidade nem um teste de todos os aparelhos. Capturas `synapse-1440.png` e `synapse-390.png` usam exemplos identificados da demonstração; `video-mobile.png` mostra dados artificiais de teste.

O relatório estruturado está em `test-results/browser-results.json`. O teste não simula nem valida captura de câmera/microfone. Chamadas estão desativadas nesse percurso de navegador.

## Verificações adicionais

Sintaxe Python e JavaScript; XML Android bem formado; consistência da demo autônoma com o asset Android; arquivos estáticos e contatos das páginas públicas; integridade do ZIP de distribuição. Essas verificações não compilam Java, não validam Gradle nem executam containers.

## Não executado ou não concluído

- Compilação APK/AAB, assinatura, instalação Android físico/emulador, iOS ou aplicativo nativo de computador.
- Execução dos workflows GitHub e build Docker/Compose.
- Implantação pública HTTPS e instalação PWA em dispositivo real.
- Envio e recebimento SMTP real, resultados de pesquisa com provedor externo ao vivo, entrega real de Web Push.
- Chamada WebRTC com transmissão real entre aparelhos/redes e serviço TURN. Uma tentativa exploratória não concluiu a conexão e não está contabilizada como teste aprovado.
- Push Android nativo, chamadas em segundo plano ou chamadas em grupo.
- Testes de grande carga, revisão independente de segurança, operação de moderação ou aprovação Google Play.

## Bloqueios encontrados

SDK Android e Gradle ausentes. Tentativas de obter as ferramentas falharam por restrições de download/resolução de rede. Não foi produzido APK ou AAB. A integração de hospedagem sugerida não está conectada; nenhum servidor, domínio, serviço pago ou conta de loja foi criado. As configurações e o código disponibilizados não substituem essa execução externa.
