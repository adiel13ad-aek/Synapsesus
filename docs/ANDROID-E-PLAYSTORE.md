# Android e Google Play — Synapse 0.4

**Situação real:** código Android fornecido; nenhum APK/AAB foi compilado ou instalado neste ambiente. Android SDK e Gradle não estavam disponíveis e o download das ferramentas falhou. O build da nuvem também não foi executado. Este guia é o caminho para a primeira compilação, não um certificado de que ela já passou.

## O que o aplicativo faz

É um cliente Android híbrido com WebView: usa a mesma interface web. Sem `APP_URL` abre a demo local, explicitamente identificada. Para contas reais, precisa de um servidor Synapse em origem HTTPS própria, como `https://synapse.seudominio.com`. Esse endereço é exemplo, não um serviço fornecido.

Há seleção de imagens pelo sistema, integração de voltar e exportação de dados para arquivo. Links externos abrem o navegador do aparelho. Não há acesso irrestrito a outras contas nem navegador universal embutido. Nenhuma permissão de localização, contatos, microfone ou acesso amplo à galeria é declarada.

Configuração: minSdk 26, compileSdk/targetSdk 36; Gradle 8.13, Android Gradle Plugin 8.11.1, JDK 17, AndroidX WebKit 1.14.0. Versões fixadas, não uma alegação de serem as mais recentes. O identificador `app.synapse.discovery` é exemplo; disponibilidade não foi verificada. Escolha um identificador próprio antes de cadastrar o aplicativo na loja.

## Caminho A — gerar APK de teste na nuvem

1. Crie um repositório no GitHub. Envie o CONTEÚDO da pasta `synapse-v0.4`, não o ZIP e não uma pasta externa contendo tudo. O arquivo `.github/workflows/android.yml` deve ficar exatamente nesse caminho na raiz. Confira a pasta oculta `.github` após o envio.
2. Não envie `.env`, `data/`, bancos, mensagens, tokens ou chaves. Um repositório público torna seu código visível para todos. Em repositório privado, confira a franquia e os limites de gastos.
3. Abra **Actions → Gerar APK Android → Run workflow**. Se o GitHub pedir, habilite Actions para esse repositório.
4. Em `app_url`, deixe vazio para testar somente a demo local. Para a rede real, informe sua origem HTTPS, sem caminho, consulta ou barra final. Não use localhost: no celular, localhost seria o próprio telefone.
5. Execute. Somente após a execução terminar com sucesso, abra o artefato **Synapse-Android-debug** e extraia o APK. A pasta prevista é `android/app/build/outputs/apk/debug/app-debug.apk`.
6. Teste em aparelho/emulador. Confira cadastro, login, seletor de fotos, câmera de teclado, voltar, tela pequena, offline, exportação e bloqueio. A aprovação do workflow apenas verifica a compilação; não substitui esses testes.

O workflow usa runners padrão; o GitHub informa gratuidade de uso desses runners em repositórios públicos, com limites e políticas. Repositórios privados têm franquias e cobrança por excedentes. Não é hospedagem do backend. [GitHub — cobrança e uso](https://docs.github.com/en/actions/concepts/billing-and-usage).

Cada execução usa a assinatura automática de debug do ambiente. Ela pode mudar entre máquinas/execuções; uma atualização instalada pode exigir desinstalar o APK anterior, apagando seus dados locais. Para distribuição estável, use sua própria assinatura de release. Não publique o debug na Play.

## Caminho B — compilar no Windows

Instale Android Studio e, pelo SDK Manager, instale Android SDK Platform 36, Build Tools 35.0.0 e Command-line Tools. Aceite as licenças. O Gradle precisa de JDK 17 compatível; o script tenta localizar o Java do Android Studio. Não envie sua chave de assinatura ao assistente.

Na pasta `android`, execute pelo PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\GERAR-APK-WINDOWS.ps1
```

Isso usa bypass somente no processo invocado para executar o script fornecido; revise o código antes. Para apontar à rede real:

```powershell
powershell -ExecutionPolicy Bypass -File .\GERAR-APK-WINDOWS.ps1 -AppUrl "https://SEU-DOMINIO"
```

O script baixa o Gradle de sua origem oficial e compara o SHA-256, gera o wrapper Gradle e executa `assembleDebug`. Acesso à internet é necessário para SDK/Gradle/dependências. Em macOS/Linux, configure `JAVA_HOME`/`ANDROID_HOME` e execute `sh gerar-apk.sh https://SEU-DOMINIO`.

Em caso de erro, leia o primeiro erro real do Gradle. Não renomeie ZIP/HTML para APK: isso não cria um aplicativo.

## Produzir AAB assinado para a Play

Novos aplicativos na Play são publicados em Android App Bundle (AAB), não com o APK debug. [Android App Bundles](https://developer.android.com/guide/app-bundle).

Depois da compilação inicial, abra a pasta `android` no Android Studio. Configure `APP_URL=https://seu-dominio` em `android/gradle.properties`, escolha um `applicationId` único e confirme a versão. Não coloque segredos nesse arquivo. O backend deve permanecer online.

Use **Build → Generate Signed App Bundle / APK → Android App Bundle**. Crie uma keystore de upload sua, guarde senha/alias com segurança, selecione `release` e gere o AAB. Faça backup privado da keystore e da senha; não comite esses arquivos no GitHub. Habilite o Play App Signing no Console. A cada atualização aumente `versionCode`. [Assinatura oficial](https://developer.android.com/studio/publish/app-signing).

O código não inclui bibliotecas nativas próprias, mas ainda precisa passar pelas verificações de compatibilidade que o Console exigir. API 36 está configurada porque desde 31/08/2026 novos apps comuns de telefone e atualizações precisam mirar Android 16/API 36 ou superior. [Nível de API](https://support.google.com/googleplay/android-developer/answer/11926878).

## A Play Store NÃO é totalmente gratuita

A inscrição normal na conta de desenvolvedor custa **US$ 25, uma vez**, e o titular precisa ter pelo menos **18 anos**. A conta exige verificações de identidade; contas pessoais também podem exigir confirmação de acesso a aparelho Android. Menores precisam de um adulto responsável como titular real da conta, sem falsificar idade ou documentos. A taxa é da conta; não é uma taxa de US$25 por aplicativo. Hospedagem, domínio e e-mail são custos separados e podem ter franquias/limites. [Registro oficial](https://support.google.com/googleplay/android-developer/answer/6112435?hl=pt-BR).

## Roteiro de publicação, depois de terminar a operação

1. Configure e mantenha o servidor HTTPS, e-mail, backups e atendimento. Remova os exemplos para um banco de produção novo com `SEED_DEMO_DATA=0`, ou faça uma migração controlada; não apague dados reais. Troque os rascunhos de políticas por documentos corretos com nome e contato do operador.
2. Cadastre e verifique a conta no Google Play Console. Crie o app com nome, idioma, categoria Social, preço e declarações corretos. Não use marcas/imagens do Instagram ou Google como se houvesse parceria.
3. Prepare ícone, capturas reais do app, descrição, e-mail de suporte, política de privacidade pública e instruções de exclusão de conta acessíveis também pela web. A exclusão deve funcionar tanto no app quanto na web. O projeto tem um ponto de partida em `/delete-account.html`; a página sozinha não substitui um fluxo testado de atendimento e recuperação.
4. Preencha Segurança dos dados, classificação etária, público-alvo, conteúdo gerado por usuários e declarações de segurança infantil. Não marque “nenhum dado coletado”: a rede guarda contas, fotos, posts, mensagens e outros dados. Informe todos os provedores da implantação real. Defina moderação, procedimento e contato responsável, não apenas botões de denúncia.
5. Envie o AAB assinado na faixa de teste. Forneça acesso de avaliação quando o conteúdo exigir login. Não envie suas credenciais pessoais; crie conta de teste apropriada.
6. Para contas pessoais criadas depois de 13/11/2023, faça teste fechado com pelo menos **12 testadores inscritos continuamente por 14 dias**, obtenha feedback e então solicite acesso à produção. Não basta instalar 12 vezes, e cumprir o período não garante aprovação.
7. Corrija os problemas apontados pelos testes e pelo Console. Só envie à produção quando as declarações, os sistemas e o conteúdo estiverem prontos. Aprovação e prazos são decisões do Google.

Fontes oficiais para essas etapas:
- [Testadores e 14 dias](https://support.google.com/googleplay/android-developer/answer/14151465?hl=pt-BR)
- [Exclusão de conta dentro e fora do app](https://support.google.com/googleplay/android-developer/answer/13327111?hl=pt-BR)
- [Segurança dos dados](https://support.google.com/googleplay/android-developer/answer/10787469?hl=pt-BR)
- [Conteúdo gerado por usuários](https://support.google.com/googleplay/android-developer/answer/9876937?hl=pt-BR)
- [Padrões de segurança infantil para apps sociais](https://support.google.com/googleplay/android-developer/answer/14747720?hl=pt-BR)

## Começar sem pagar a taxa da Play

A demo local e o servidor de teste não exigem conta Play. A interface inclui estrutura PWA; uma implantação HTTPS pode permitir instalação pelo navegador conforme o dispositivo, sem publicar na loja. Isso não garante hospedagem gratuita ilimitada.

Para pequenos testes Android fora da loja, a documentação atual também oferece conta de distribuição limitada gratuita para até **20 dispositivos autorizados**, via Android Developer Console. No Brasil, novas regras de verificação de desenvolvedores estão em vigor desde 30/09/2026; siga o fluxo oficial para distribuição, não prometa que todo APK será instalável sem registro. Esse caminho não coloca o aplicativo na Play Store. [Distribuição limitada oficial, consultada em 27/10/2026](https://developer.android.com/developer-verification/guides/limited-distribution).

## Estado de prontidão

O pacote NÃO contém infraestrutura pública, conta Google Play, aprovação da loja, assinatura sua ou serviços de e-mail contratados. APK debug, PWA e AAB assinado são coisas diferentes. Não distribua esta beta como serviço de produção até concluir testes nativos, revisão de segurança/privacidade, proteção contra abuso e os requisitos operacionais.
