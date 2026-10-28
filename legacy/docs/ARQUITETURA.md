> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Arquitetura 0.5

- `server.py`: autenticação, perfis, feed legado, histórias, mensagens, coleções, pesquisa e moderação.
- `features.py`: uploads/galerias/vídeos, mídia autorizada, feed paginado, papéis, configuração, push e sinalização WebRTC.
- `schema.sql`: SQLite e migrações aditivas. Chaves estrangeiras com exclusão em cascata; arquivos removidos explicitamente após a transação.
- `web/app.js`: interface social e fluxos fundamentais.
- `web/features.js`: interface de mídia, vídeos, paginação, permissões push e chamadas opcionais.
- `web/sw.js`: cache só de arquivos públicos da interface e manipuladores push. Não armazena respostas de conta, mensagens, buscas ou mídia dos usuários.
- `manage.py`: operador, chaves VAPID, manutenção, cópia consistente com servidor parado e restauração em destino novo.
- `android/`: cliente híbrido de origem fixa; código-fonte não compilado nesta execução.
- `Dockerfile`, `compose*.yaml`, `render.yaml`: configurações de implantação, não servidores já implantados.

## Escopo de execução

Uma instância, um worker. SQLite e mídia precisam de disco persistente. O processo de entrega push e limpeza usa o mesmo servidor. Não há infraestrutura elástica ou fila distribuída. Para escalar, é necessário redesenhar armazenamento, processamento de mídia, limites de abuso e distribuição dos trabalhos.

## Vídeo

Entrada limitada; armazenamento temporário; validação com ffprobe; processamento com ffmpeg; saída MP4/miniatura; quota por conta/global; associação explícita a post após permissão do proprietário. O servidor pode servir intervalos de bytes para reprodução. Os originais não são preservados. Uma publicação aceita até seis imagens ou um vídeo.

## Comunicação

Mensagens: HTTP com consulta periódica a cada três segundos quando a conversa está visível. Atividade: a cada cinco segundos. Push: serviço opcional do navegador, sem texto privado no payload. Chamadas: convite/aceite HTTP, sinalização por consulta periódica e mídia WebRTC. TURN é externo; não existe um servidor TURN hospedado pelo pacote.

## Pesquisa/navegação

Busca interna no SQLite; adaptadores opcionais Brave/Wikipédia; sem credencial Brave, atalhos para buscadores externos. Web abre outra aba. Android usa Custom Tabs do navegador compatível do aparelho. Não há índice independente de toda a web, proxy para contornar sites, acesso automático a contas externas nem substituição de TLS.
