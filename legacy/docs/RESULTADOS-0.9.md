# Synapse Discovery 0.9 — resultados da entrega

## Resultado final executado

- **183 testes automatizados aprovados**, sem falhas, em 53,71 segundos nesta execução.
- **11 grupos de verificações de interface aprovados**, incluindo oito combinações de
  tela/largura (Central de segurança e Operação em 320, 390, 768 e 1440 pixels).
- Nenhum erro JavaScript não tratado foi registrado nesse roteiro de interface.
- Compilação sintática dos módulos Python e checagem de sintaxe dos três scripts JavaScript
  alterados aprovadas (`py_compile` e `node --check`).

A suíte original 0.8 tinha 142 testes; eles passaram antes das alterações. Foram adicionados
41 testes nesta entrega. Algumas expectativas antigas foram atualizadas para refletir
mudanças intencionais: versão do cache, links de e-mail em fragmento, novo contato de segurança
no diagnóstico e requisitos adicionais de abertura. Não foram removidas verificações para
fingir sucesso: os ramos de negação e um fluxo completo de abertura com evidências SINTÉTICAS
estão cobertos.

Os tempos são medições desta execução local, não estimativas de uso público ou SLA.

## Executado de fato localmente

Cadastro e autenticação; privacidade de perfil/feeds/stories/mídias; aprovação e remoção de
seguidores; sessões opacas e revogação; aceite de Termos; assinatura Ed25519, vinculação
à conta e rejeição de replay; restrições por faixa e supervisão; suporte privado e resposta;
criptografia da fila SMTP e política de tentativas; geração AES-GCM, rejeição de chave
errada/adulteração, fotografia de SQLite e mídias e restauração com sessões invalidadas;
barreira temporária de backup; permissão de operador; checks de saúde e estado público;
recusa de inscrições quando controles deixam de ser atendidos.

A suíte também preserva os testes existentes, incluindo cadastro, publicação, imagens,
processamento de vídeo, mensagens, moderação, MFA, convites e isolamento de rotas privadas.
Os testes de filas executam criptografia de verdade, mas o transporte SMTP é simulado.

## Interface: método exato

HTML/CSS/JavaScript reais foram executados em Chromium headless, com Uvicorn e SQLite
locais temporários. Este ambiente bloqueou navegação direta do Chromium para localhost
com `ERR_BLOCKED_BY_ADMINISTRATOR`. Por isso, o teste usou uma **ponte HTTP explícita**:
o navegador recebe a interface e as requisições chegam ao servidor por um cliente HTTP.
A ponte mantém os cookies da sessão no cliente, não valida cookies do navegador real.

O roteiro cobriu: salvar privacidade; aprovar seguidor; enviar suporte; encerrar outra
sessão real; responder como operador; exibir a resposta ao titular; testar e-mail em modo
arquivo com aviso verdadeiro; executar um backup local pelo worker do aplicativo;
redimensionamento; acesso administrativo negado a visitante; cadastro pela interface.

Isso **não valida** CSP em navegação direta, HTTPS/TLS público, comportamento de cookies
nos navegadores reais, service worker de produção, acessibilidade completa ou aparelhos.
As capturas mostram contas sintéticas e um ambiente de desenvolvimento, não usuários reais.

## Serviços simulados e limites

| Componente | Evidência obtida | Ainda não demonstrado |
|---|---|---|
| E-mail | Fila, criptografia, expiração e tentativas | Envio e entrega em caixa real |
| Turnstile | Conferência de token/hostname/ação com resposta simulada | Desafio completo no domínio público |
| Idade | Recibos assinados por chave sintética; rejeição de entradas inválidas | Método de aferição real, fornecedor/adaptador e fraude |
| Responsável | Fluxo de convite, declaração, pausa e permissões | Parentesco/representação legal efetivamente comprovados |
| Backups | Cópia, criptografia e restauração locais reais | Envio/recuperação em bucket real e durabilidade do provedor |
| Abertura | Ramo de sucesso com configuração e evidências sintéticas | Instalação pública pronta e operada |
| Navegador | Fluxos funcionais por ponte HTTP | HTTPS/cookies/CSP reais e aparelhos físicos |

Nenhuma hospedagem foi criada ou alterada. Não houve auditoria independente, pentest,
ensaio de carga de produção, verificação automática de vulnerabilidades de dependências,
certificação jurídica, compilação Android ou publicação em loja. A configuração Docker
está no código, mas não foi construído/testado um contêiner de produção nesta entrega.

## Ambiente da execução

Python 3.13.5; FastAPI 0.128.2; Starlette 0.50.0; Uvicorn 0.48.0; HTTPX 0.28.1;
cryptography 46.0.4; Pillow 12.3.0; python-multipart 0.0.29; pytest 9.0.2;
Playwright 1.57.0; FFmpeg 7.1.5; boto3 1.43.18. O workflow do repositório usa Python 3.12,
mas não foi executado na conta GitHub do usuário. Teste essa combinação na implantação.

## Reproduzir

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q --junitxml=test-results/v09/junit.xml
python tests/browser_v09.py
```

O roteiro de navegador exige Chromium em `/usr/bin/chromium` e o pacote Playwright.
`requirements-dev.txt` inclui pytest e HTTPX; instale Playwright separadamente para o
roteiro de UI. Em outro sistema, ajuste o caminho do navegador ou use o Chromium
fornecido pelo Playwright. Não rode testes com banco ou credenciais de produção.

Evidências no pacote: `test-results/v09/api.txt`, `junit.xml`, `browser-report.json`,
`browser.txt` e capturas; `baseline-v08.txt` registra a execução anterior às mudanças.
