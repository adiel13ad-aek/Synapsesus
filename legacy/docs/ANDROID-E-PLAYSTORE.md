> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Android e Google Play — Synapse 0.5

## Estado real

**Não há APK nem AAB compilado nesta entrega.** Há projeto Java/Gradle, recursos, scripts e workflows. A tentativa local ficou bloqueada pela ausência do SDK/Gradle e falha de download/resolução de nomes dos servidores oficiais. O JDK está disponível, mas ele sozinho não compila um app Android completo.

Não foram executados Android lint, instalação em aparelho, permissões de câmera/microfone no Android ou validação em uma conta Play. Não renomeie ZIP para APK.

## O cliente Android

É híbrido, com a interface Synapse em uma origem fixa. `APP_URL` precisa ser uma origem HTTPS, sem caminho ou credenciais. Vazio produz apenas demo local explicitamente identificada. O servidor não fica dentro do APK.

Há código para seleção múltipla de fotos/vídeo, botão Voltar, exportação de dados, Custom Tabs para sites externos, TLS obrigatório e aceite específico de câmera/microfone para chamadas. Não há bridge JavaScript nativa geral. Os sites externos usam o contexto do navegador, sem receber o cookie da WebView Synapse.

Custom Tabs é uma integração com um navegador compatível do aparelho, não um motor de busca próprio nem acesso irrestrito a conteúdo privado. O suporte a sites, login e permissões depende do navegador/site.

## Gerar o APK no GitHub

Envie os arquivos extraídos mantendo a estrutura. Na raiz do repositório devem estar `.github`, `android`, `web`, `server.py` etc., não apenas o ZIP. Não envie `.env`, `data`, certificados, keystores ou backups.

Abra Actions → **Gerar APK Android** → Run workflow. Informe `app_url` para sua rede real ou deixe vazio para a demo. O job recompõe a demo embarcada, instala SDK 36, compila e executa lint. Somente após conclusão bem-sucedida o artefato **Synapse-Android-v0.5** conterá um APK real.

O workflow foi escrito, mas não executado em sua conta. Qualquer erro deve ser corrigido antes de anunciar o app como compilado. Builds debug usam assinatura de teste; não são o pacote de publicação da loja.

## Gerar no Windows

Instale Android Studio com SDK 36, aceite as licenças e abra a pasta `android`. Alternativamente, com o SDK configurado:

```powershell
cd android
.\GERAR-APK-WINDOWS.ps1 -AppUrl "https://SEU-SERVIDOR"
```

O script baixa e valida o Gradle pelo checksum publicado no servidor oficial. Precisa de internet e JDK compatível. O APK, **depois de um build bem-sucedido**, fica em `android/app/build/outputs/apk/debug/`.

## AAB assinado

Novos apps no Google Play são publicados como Android App Bundle (AAB), não enviando o APK debug desta demonstração.

Android Studio: Build → Generate Signed App Bundle / APK → Android App Bundle. Crie e preserve sua chave de upload e senha. Escolha um identificador de pacote sob seu controle antes do primeiro envio; o exemplo `app.synapse.discovery` não é garantia de disponibilidade nem de marca registrada.

Para assinar no workflow, configure **secrets do repositório**, nunca arquivos públicos:

- `ANDROID_KEYSTORE_BASE64`: conteúdo base64 da sua chave de upload.
- `ANDROID_STORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`.

Marque `signed_release` e informe `app_url`. O arquivo de chave temporário é removido ao final. Não compartilhe as chaves e senhas no chat. Nenhuma chave de publicação foi criada ou recebida nesta entrega.

## Publicação não é automática nem totalmente gratuita

A inscrição normal do Play Console exige titular com pelo menos 18 anos e taxa única de US$ 25. Um responsável adulto deve ser o titular real quando o desenvolvedor é menor, sem falsificar identidade. É preciso cumprir verificações, testes aplicáveis à conta, políticas, declarações e revisão do Google. O código não cria essa conta, não paga a taxa e não garante aprovação.

Prepare capturas reais, descrição, contato, políticas publicadas, exclusão de conta pela web, classificação indicativa, declarações de dados e acesso para revisão. Para uma rede social, é necessária uma operação real de denúncia/moderação e proteção dos usuários, não apenas botões.

O projeto mira API 36. Confira os requisitos de publicação novamente no dia do envio, pois podem mudar. A versão compilada e todas as integrações reais devem ser testadas primeiro.

## Fontes oficiais verificadas na preparação

- Conta, idade e taxa: https://support.google.com/googleplay/android-developer/answer/6112435
- App Bundle: https://developer.android.com/guide/app-bundle
- Assinatura: https://developer.android.com/studio/publish/app-signing
- Requisito de API: https://developer.android.com/google/play/requirements/target-sdk
- Testes de contas pessoais: https://support.google.com/googleplay/android-developer/answer/14151465
- Custom Tabs: https://developer.android.com/develop/ui/views/layout/webapps/overview-of-android-custom-tabs
