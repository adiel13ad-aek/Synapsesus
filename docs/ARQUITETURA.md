# Arquitetura — Synapse Discovery 0.4

```
Web responsiva / PWA ─┐
                     ├─ HTTPS ─ FastAPI (um processo no piloto)
Android WebView ──────┘             ├─ SQLite: contas/feed/stories/mensagens/coleções
                                   ├─ mídia reencodificada em diretório privado do servidor
                                   ├─ e-mail: arquivo de teste ou SMTP configurado
                                   └─ busca: atalhos externos / Brave / Wikipédia
```

`web/app.js` e `web/style.css` implementam toda a interface. `web/demo-adapter.js` oferece somente o modo local explicitamente identificado. `build_demo.py` embute CSS/JS no HTML e copia a demo para assets Android. O modo servidor não troca silenciosamente para a demo quando há erro.

`server.py` concentra regras e API; `schema.sql` contém as tabelas e índices. A migração aditiva preserva campos da versão 0.3; tabelas legadas de agentes ficam só para compatibilidade de dados. Não há agentes ou chamadas de IA nesta versão.

`android/` contém o cliente de origem fixa. Sem APP_URL ele usa WebViewAssetLoader para servir assets em origem HTTPS local. Com APP_URL ele carrega apenas a origem real da plataforma; sites de pesquisa abrem externamente. Não há JavaScript bridge com acesso nativo arbitrário. Não confunda esse componente com um navegador geral.

O service worker guarda somente o shell estático, não sessões, mensagens, API ou imagens de usuários. Mesmo com interface em cache, contas reais precisam de conexão com o servidor. O arquivo demo separado não é esse cache offline.

## Evolução necessária para produção

Paginação e índices de busca; tarefas de limpeza periódicas; streaming/armazenamento especializado antes de vídeo; notificações push consentidas; controle de abuso; observabilidade; banco gerenciado e backups; envio de e-mail confiável; moderação e políticas operadas. Nenhum serviço de nuvem foi provisionado nesta entrega.
