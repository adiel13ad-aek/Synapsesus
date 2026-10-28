# Synapse Discovery 1.0 — candidato de lançamento para Cloudflare

Aplicação social com interface inspirada no Instagram, adaptada de Python/SQLite local para **Cloudflare Workers + D1 + R2 privado**, com implantação pelo GitHub. O pacote contém código e ferramentas; não cria recursos na sua conta nem comprova uma instalação pública.

**Comece pelo [guia Cloudflare](docs/CLOUDFLARE.md).** Se já há contas e publicações na instalação Python, siga primeiro [a migração](docs/MIGRACAO.md). O código anterior permanece em `legacy/`.

## Antes de publicar

- O serviço correto é **Workers**, não um upload da pasta `web` no Pages. O Worker executa a API, autoriza mídias privadas e serve a interface no mesmo endereço.
- Cadastros gerais começam fechados. Contatos, políticas, e-mail, Turnstile, aferição externa de idade e conta administrativa precisam ser configurados e validados no seu ambiente.
- A integração etária recebe comprovantes assinados de um fornecedor compatível. O código não descobre a idade sozinho. Contas de menores continuam sem acesso social nesta migração.
- Recursos que dependiam do servidor Python, como processamento FFmpeg, chamadas experimentais e push, não são automaticamente equivalentes no Worker. Confira `docs/RESULTADOS-1.0.md` incluído na entrega; a versão Python foi preservada.
- Não há promessa de hospedagem gratuita. Esta aplicação pode exigir Workers Paid e R2 habilitado; confira preços e limites na sua conta antes de criar recursos.

## Desenvolvimento local

Requer Node.js 24 e npm. Python 3.10+ é necessário apenas para migrar a instalação anterior.

```bash
npm ci
node scripts/setup.mjs --local-secrets
npm run db:local
npm run dev
```

Abra `http://localhost:8787`. O modo local usa dados locais do Wrangler; não representa e-mail entregue nem teste de produção. A configuração `.dev.vars` gerada contém segredos locais e não deve ir ao repositório. Para confirmar o e-mail de teste, execute `node scripts/local-mail.mjs` e abra o link mostrado somente no seu terminal. Esse leitor nunca acessa o banco remoto nem envia mensagens.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `src/` | API do Worker, autenticação, administração e autorização |
| `web/` | Interface pública e painéis |
| `migrations/` | Esquema D1 versionado |
| `wrangler.jsonc` | Configuração pública de recursos e origem |
| `scripts/` | Configuração, validação e migração offline |
| `tests/` | Verificações automatizadas da versão nativa |
| `legacy/` | Projeto Python anterior, mantido para recuperação |

## Comandos de verificação

```bash
npm run build
npm test
npm run test:runtime
npx wrangler deploy --dry-run
```

O build executa a validação, a suíte automatizada e o teste no runtime local dos Workers. Os comandos individuais são úteis para diagnóstico. O último comando empacota o Worker sem publicá-lo. Esses comandos não verificam o domínio real, a chegada de e-mails, custos, capacidade sob carga ou adequação dos documentos da operação.

Não envie `.dev.vars`, `.private/`, `.env`, bancos, mídias privadas, backups nem a pasta de migração ao GitHub. Preserve as chaves administrativas em local privado separado.

## Teste opcional de interface

Instale o navegador de teste com `npx playwright-core install chromium` e execute `npm run test:browser`. Ele cria somente um banco e um bucket temporários locais, usa contas fictícias e descarta tudo ao terminar. Não envia e-mail real.
