> **Guia histórico:** para esta entrega, comece por `ABERTURA-0.9.md`. Configurações, recursos e resultados antigos não substituem os da 0.9.

# Synapse Discovery 0.5

Rede social de descobertas, sem agentes de IA. **Beta técnico para testes privados.**

Esta entrega contém código funcional de servidor e interface. Não inclui servidor contratado, APK compilado, conta Google Play, envio de e-mail contratado, chave de busca ou operação humana de moderação. Não é certificação de segurança ou de conformidade jurídica.

## Começar no Windows

Instale Python 3.10 ou superior. Extraia a pasta inteira e abra `INICIAR-WINDOWS.bat`. Acesse `http://localhost:8000`, crie uma conta e personalize o perfil. O terminal deve ficar aberto. As contas reais são criadas no servidor; o HTML de demonstração não cria contas reais.

Linux/macOS: `sh iniciar-macos-linux.sh`.

Manual:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: . .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Vídeos precisam de **ffmpeg e ffprobe no PATH**. A imagem Docker já prevê esses pacotes. Sem eles, o aplicativo informa a limitação e permite fotos normalmente. Não remova as proteções para aceitar um arquivo inválido.

## O que mudou desde a 0.4

- Galerias com até seis fotos, ordenadas e navegáveis por gesto/botões. Fotos reprocessadas, sem copiar metadados originais.
- Vídeos MP4/WebM/MOV de até 25 MB e 90 segundos. O servidor gera MP4 e miniatura. Um vídeo por publicação. Há uma área de vídeos, sem reprodução automática com áudio.
- Arquivos ainda não publicados ficam restritos à conta que os enviou. Exclusão de post ou conta remove também os arquivos associados. Stories expirados deixam de ser servidos.
- Feed paginado; filtros de vídeos, seguindo e salvos. Mensagens abertas são consultadas a cada três segundos e a atividade a cada cinco segundos. Isso é polling, não WebSockets.
- Web Push opcional: cadastro do dispositivo, permissão do navegador, entrega genérica sem texto de mensagens e revogação da assinatura. Precisa de chaves VAPID e biblioteca de produção. **Não funciona no WebView Android deste projeto; destina-se à PWA/navegadores compatíveis.**
- Chamadas de áudio/vídeo experimentais: convite, aceite, recusa, sinalização autenticada e interface WebRTC. Desativadas por padrão. Precisam de HTTPS/localhost, permissões e TURN para implantação confiável entre redes. **Mídia de chamadas não foi validada de ponta a ponta nesta entrega.**
- Administrador associado ao identificador da conta, verificação de configuração, preparação Docker/HTTPS/Render, backup com manifesto e restauração em pasta nova.
- Cliente Android atualizado para múltiplos arquivos/vídeos, navegação com Custom Tabs e permissão explícita de câmera/microfone. Fonte ainda não compilado aqui.
- Workflow de testes e workflow de APK/AAB assinado, condicionado às chaves privadas do proprietário. Nenhuma chave privada faz parte do projeto.

## Mantido da versão anterior

Cadastro, login, recuperação/confirmação de e-mail, perfil com foto/capa, temas, interesses, publicações, curtidas, comentários, seguir/bloquear, stories, mensagens, coleções privadas, denúncias, moderação manual, exportação e exclusão de conta.

## E-mails e pesquisas

O padrão `MAIL_MODE=file` grava mensagens de teste em `data/outbox`, **não envia e-mails reais**. Configure SMTP para entrega real. Tokens são secretos: não publique a pasta de saída e não compartilhe links de recuperação.

O padrão de busca abre provedores externos. `SEARCH_PROVIDER=brave` e `BRAVE_SEARCH_API_KEY` habilitam o adaptador de resultados dentro do Synapse. A chave fica somente no servidor. Wikipédia é uma pesquisa enciclopédica, não um índice geral da internet. Os adaptadores externos foram testados com respostas controladas, não certificados contra serviços reais nesta execução.

## Dados existentes

As alterações de banco são aditivas. **Faça um backup antes de atualizar** e preserve a pasta `data` da instalação anterior. Não copie dados reais para `web`, `android/assets`, GitHub ou um ZIP de distribuição. Os arquivos da entrega não contêm contas reais.

## Documentos

- `docs/DEPLOY.md`: implantação, custos externos, configuração e acesso do operador.
- `docs/ANDROID-E-PLAYSTORE.md`: gerar APK/AAB e os passos externos de publicação.
- `docs/TESTES.md`: resultados executados e limites do ambiente.
- `docs/SEGURANCA.md`: modelo de segurança e pendências operacionais.
- `docs/ARQUITETURA.md`: módulos, dados e fronteiras de confiança.
- `manage.py`: manutenção local, backup, restauração, limpeza, operador e VAPID.

## Demonstração

Abra `Synapse-Discovery-v0.5-demo.html` em um navegador. É local, com exemplos explícitos; não conecta pessoas. Os recursos que dependem de servidor, serviços externos ou aparelhos não são simulados como se estivessem online.

## Limite do que foi entregue

Não houve compilação Android, implantação pública, envio SMTP real, envio Web Push real, chamada com mídia de ponta a ponta, teste em aparelho físico, auditoria independente, carga de produção ou aprovação da Play Store. Há código e configuração para avançar nessas etapas, não confirmação de conclusão. Antes de receber público aberto, configure e valide os serviços reais e a operação de segurança/moderação.
