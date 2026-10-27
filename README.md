# Synapse Discovery 0.4 — Descobertas que conectam

**Beta funcional para testes privados, não uma rede pronta para lançamento público.**
Atualização de 27/10/2026. Rede social + descoberta da web; sem agentes de IA.

## O que foi entregue

A interface foi reconstruída: feed visual, navegação inferior no celular, cartões com fotos, perfis com capa, temas claro/escuro/sistema, quatro cores de destaque, animações e opção de reduzir movimento. As ilustrações e perfis editoriais são exemplos explicitamente identificados; não representam uma comunidade real.

| Área | Implementação nesta versão |
|---|---|
| Contas | Nome, usuário, e-mail, senha, aceite dos termos; login por usuário/e-mail; logout; confirmação de e-mail; recuperar e trocar senha |
| Perfil | Foto, capa, bio, site, até oito interesses e cor do avatar |
| Social | Seguir, feed, texto + uma foto + um link por post, curtir, salvar, comentar, editar legenda, excluir conteúdo próprio |
| Stories | Texto e imagem opcionais, expiração após 24h, pausa e denúncia; sem vídeo ou métricas de visualização |
| Pesquisa | Busca interna; atalhos Google/Brave/DuckDuckGo; adaptadores opcionais Wikipédia e Brave Search API |
| Coleções | Referências privadas com pasta, título e nota; compartilhar o link não publica a nota |
| Mensagens | Entre contas do mesmo servidor; controle de remetentes e bloqueio; sem criptografia de ponta a ponta |
| Atividade | Notificações internas de curtidas, comentários, seguidores e mensagens; não são push |
| Segurança | Senhas com hash, sessões, proteção CSRF, reencodificação de imagens, denúncias, fila manual de moderação, suspensão |
| Dados | Exportação JSON, exclusão de conta com senha, instruções web públicas |
| Android | Código do aplicativo híbrido, scripts e GitHub Actions para gerar APK. APK/AAB NÃO compilados neste ambiente |

## 1. Ver o design sem instalar

Abra `Synapse-Discovery-v0.4-demo.html` em um navegador. É uma demonstração local: não cria contas reais, não envia e-mails e não conecta dispositivos. Os dados ficam no armazenamento local quando disponível. Quando o navegador bloqueia esse armazenamento, a interface informa que os dados duram somente a sessão. Não use senhas reais na demo.

## 2. Usar contas reais no servidor local

No Windows: instale Python 3.10 ou superior, extraia todo o ZIP e abra `INICIAR-WINDOWS.bat`. Na primeira execução é necessário acesso à internet para instalar dependências. Abra `http://localhost:8000`, clique em Entrar e crie sua conta.

No macOS/Linux:

```sh
sh iniciar-macos-linux.sh
```

Ou manualmente:

```sh
python -m venv .venv
# Ative o ambiente virtual da sua plataforma antes de continuar.
python -m pip install -r requirements.txt
python run.py
```

O banco é `data/synapse.db`; imagens ficam em `data/media`. Fechar o navegador não apaga esses dados. O terminal precisa continuar aberto para o servidor funcionar.

No mesmo Wi-Fi privado:

```bat
INICIAR-WINDOWS.bat --lan
```

No celular abra `http://IP-LOCAL-DO-PC:8000`. Use contas de teste: HTTP na rede não cifra o tráfego. Não redirecione a porta do roteador para a internet. PWA em dispositivos e o cliente Android real precisam de HTTPS; o projeto não inclui hospedagem.

## 3. Configurar e-mail e conta operadora

Copie `.env.example` para `.env`. Reinicie o servidor após editar.

Por padrão, `MAIL_MODE=file`: os links de confirmação e recuperação são gravados em arquivos `.eml` em `data/outbox`. Nada é enviado à caixa de entrada. Esses arquivos são confidenciais; não devem ir ao GitHub nem ao diretório público. Podem ser abertos localmente com um leitor de e-mail ou editor. O link usa `PUBLIC_ORIGIN`; vazio aponta para localhost:8000. Ajuste se usar outra porta.

Para envio real, configure `MAIL_MODE=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_USER`, `SMTP_PASSWORD` e `PUBLIC_ORIGIN=https://seu-dominio`. Porta 465 usa TLS; outras usam STARTTLS. Autenticação e entrega dependem do provedor. E-mail real não foi testado nesta entrega.

Confirmação de e-mail e reset têm tokens aleatórios, de uso único e com validade. A conta pode interagir antes da confirmação nesta beta. Não há autenticação de dois fatores nem alteração de e-mail pela interface.

Para moderação: primeiro cadastre e proteja a conta que administrará o piloto. Depois coloque seu nome de usuário em `ADMIN_HANDLES`, sem @, e reinicie. A seção aparece em Configurações. Não configure nomes ainda disponíveis: outra pessoa poderia cadastrá-los. Denúncias não são julgadas automaticamente; alguém precisa revisar a fila. O painel permite descartar a denúncia, remover conteúdo ou suspender perfil conforme o tipo.

## 4. Pesquisa e navegação

O padrão `SEARCH_PROVIDER=external` não faz chamadas pagas: oferece links de busca externa. Sites abrem no navegador/aba externa, não num navegador universal embutido.

Para resultados web estruturados, configure `SEARCH_PROVIDER=brave` e `BRAVE_SEARCH_API_KEY` apenas no servidor. Consultas são enviadas ao provedor; verifique preço e termos antes de ativar. O adaptador de Wikipédia é enciclopédico, não cobre toda a web. Os testes automatizados de provedores usam respostas simuladas; não comprovam conectividade nem saldo de uma conta real.

## 5. Android e Google Play

Leia `docs/ANDROID-E-PLAYSTORE.md`. O projeto está em `android/`, e o fluxo em `.github/workflows/android.yml`.

**Não há APK ou AAB compilado no ZIP.** O ambiente de criação não tinha Android SDK/Gradle e o download das ferramentas falhou por resolução de DNS. A parte Android não foi executada em emulador ou aparelho. Scripts e fontes foram preparados, mas ainda podem exigir correções após a primeira compilação.

Sem `APP_URL`, o APK de teste exibirá a demo local. Com `APP_URL` configurado para o seu servidor HTTPS, o cliente carregará a rede real. Não inclui um backend dentro do telefone. O build release é bloqueado sem URL. A Play recebe AAB assinado; o APK debug não é o arquivo de publicação.

## 6. Atualizar da versão 0.3

1. Pare o servidor antigo. Faça backup integral da pasta `data` e de `.env` em lugar privado.
2. Extraia a 0.4 em uma pasta nova. Copie os dados antigos somente com ambos os servidores parados. Preserve banco, arquivos auxiliares SQLite se existirem e mídia juntos.
3. Revise `.env` com o exemplo novo e inicie. A migração é aditiva. Nunca rode dois servidores diferentes sobre o mesmo banco.
4. Contas antigas continuam entrando por usuário, mas sem e-mail cadastrado não têm recuperação automática. Uma migração assistida de e-mail deve ser feita pelo operador; não invente endereços.

Os testes não constituem uma garantia de recuperação de qualquer banco alterado manualmente. Guarde o backup antes da migração.

## 7. Testes e limites

Foram executados 48 testes automatizados de API e 19 verificações agrupadas de interface em Chromium. Estas incluem sete telas nas larguras 320, 390, 768 e 1440 px. O navegador usou uma ponte HTTP para o servidor real do teste; não foi um teste de instalação PWA/Android ou HTTPS de produção. Detalhes em `docs/TESTES.md`.

O feed carrega até 100 posts por consulta, até 500 perfis e até 500 referências da conta. Mensagens são consultadas periodicamente. SQLite e limites de taxa locais atendem apenas um piloto pequeno em um processo. Não há upload de vídeos, Reels, carrosséis, chamadas, push, login social, verificação de identidade ou operação de moderação automática.

Antes do lançamento público faltam hospedagem HTTPS operada, domínio/configuração, e-mail confiável, backups e restauração testados, paginação e testes de carga, proteção contra abuso, revisão de segurança e privacidade, políticas finais com contato real e validação do Android. Não é correto chamar esta entrega de “100% completa”.

## Documentação

- `docs/ANDROID-E-PLAYSTORE.md`: gerar APK, AAB, custos e requisitos oficiais.
- `docs/SEGURANCA.md`: limites e controles do piloto.
- `docs/ARQUITETURA.md`: estrutura e evolução técnica.
- `docs/TESTES.md`: escopo realmente verificado.
- `web/privacy.html`, `web/terms.html`, `web/safety.html`, `web/delete-account.html`: páginas públicas de rascunho, a revisar antes do lançamento.

Não publique `.env`, `data/`, e-mails de recuperação, dados reais ou chaves de assinatura no repositório.
