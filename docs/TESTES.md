# Testes executados — Synapse Discovery 0.4

Data: 27/10/2026. Estes são testes do código entregue, não certificação de segurança/produção.

## API — 48 testes aprovados

Comando: `python -m pytest tests/test_api.py tests/test_v04.py -q`.

................................................                         [100%]
48 passed in 10.96s

Cobertura: cadastro e consentimento; login e sessão; autorização; posts, imagens, comentários e seguidores; mensagens e políticas de remetente; coleções privadas; exportação/exclusão; confirmação e reset de e-mail com tokens de uso único; revogação de sessão; stories/expiração; notificações; moderação e suspensão. Provedores externos são simulados nos testes que os exercitam.

## Interface — 19 verificações agrupadas aprovadas

Chromium automatizado. O JavaScript foi executado com uma ponte HTTP para a API FastAPI real, porque a navegação direta ao localhost era restrita neste ambiente. Imagens também foram encaminhadas ao servidor de teste. Não foram simulados os endpoints sociais. A demo local foi testada separadamente.

1. Cadastro com e-mail e aceite de termos abre personalização.
2. Foto, capa, bio, site e interesses salvos no perfil real.
3. Publicação de imagem e link real com legenda acessível.
4. Curtida, salvar publicação e comentário persistidos.
5. Edição da própria legenda pela interface.
6. Coleção privada e compartilhamento sem vazamento da anotação.
7. Criar, abrir e pausar story real.
8. Tema escuro, cor e movimento reduzido com persistência na conta.
9. Notificações reais de outra conta e marcação como lidas.
10. Mensagens bidirecionais entre contas reais.
11. Busca social real e atalhos web identificados sem resultados fictícios.
12. HTML inserido em publicações aparece como texto sem executar.
13. Sessão, preferências e coleções preservadas ao reabrir a interface.
14. Sete telas sem rolagem horizontal em 320px.
15. Sete telas sem rolagem horizontal em 390px.
16. Sete telas sem rolagem horizontal em 768px.
17. Sete telas sem rolagem horizontal em 1440px.
18. Demonstração móvel: publicar e curtir localmente.
19. Nenhuma exceção JavaScript não tratada nos fluxos exercitados.

Cada verificação de largura passou pelas telas feed, explorar, coleções, perfil, mensagens, atividade e configurações. As capturas usam somente a demo com exemplos identificados; dados de teste reais não foram publicados. O aviso de armazenamento temporário, específico do contexto sem origem do teste, foi ocultado apenas para as capturas. O aplicativo continua exibindo esse aviso quando necessário.

## Validação adicional

Sintaxe Python e JavaScript, XML Android bem formado e coincidência entre demo autônoma e asset Android. Isso não compila Java nem valida dependências Gradle.

## NÃO verificado

Compilação de APK/AAB; instalação Android físico/emulador; iPhone; instalação PWA; execução do workflow GitHub; assinatura de release; hospedagem pública HTTPS; SMTP real; busca externa autenticada; operação de moderação; testes de carga; acessibilidade com leitores de tela; análise independente de segurança; aprovação Google Play.

Não há APK/AAB nesta entrega. SDK/Gradle estavam ausentes; tentativas de baixar ferramentas falharam no ambiente. A parte nativa exige a primeira compilação e seus testes.
