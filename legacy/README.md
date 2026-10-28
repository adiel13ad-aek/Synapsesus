# Synapse Discovery 0.9 — preparação de abertura pública

Rede social e descoberta da web, sem agentes de IA. Esta versão adiciona privacidade,
ativação protegida de contas, suporte e ferramentas de recuperação. **É código testado
localmente, não uma hospedagem implantada nem uma certificação de produção.**

## Comece aqui

- **`docs/ABERTURA-0.9.md`**: primeira implantação, atualização e o que ainda depende do responsável.
- **`docs/RECUPERACAO-0.9.md`**: backups criptografados, armazenamento externo e restauração.
- **`docs/INTEGRACAO-IDADE.md`**: contrato técnico para um fornecedor externo de aferição; não há fornecedor conectado.
- **`docs/SEGURANCA-0.9.md`**: controles, limitações e operação humana necessária.
- **`docs/RESULTADOS-0.9.md`**: testes efetivamente executados e o que não foi validado.

Estes documentos prevalecem sobre guias históricos de versões anteriores presentes em `docs/`.

## Executar apenas para testar no computador

Instale Python 3.10 ou superior e execute `INICIAR-WINDOWS.bat` (Windows), ou
`sh iniciar-macos-linux.sh` (Linux/macOS). Acesse `http://localhost:8000`.
Use dados fictícios e senhas exclusivas. O modo local grava e-mails em `data/outbox`;
não envia mensagens reais e não exige aferição etária por padrão.

Para testar todas as dependências operacionais manualmente:

```sh
python -m venv .venv
# Ative o ambiente virtual antes de continuar.
python -m pip install -r requirements-production.txt
python run.py
```

Crie um responsável local com `CONFIGURAR-ADMIN-WINDOWS.bat` ou
`python configurar_admin.py`. Depois de entrar, abra `/admin` e configure o segundo fator.

| Caminho | Função |
|---|---|
| `/` | Rede social real, conectada ao servidor |
| `/bem-vindo` | Apresentação pública para divulgação |
| `/conta/seguranca` | Privacidade, seguidores, sessões e suporte do usuário |
| `/admin` | Usuários, conteúdo, denúncias, configurações e lançamento |
| `/operacao` | E-mails, backups, suporte e diagnóstico para o responsável |
| `/api/ready` | Verificação mínima de banco e reserva de espaço |

## O que mudou

Perfis privados com aprovação de seguidores, remoção de seguidores e proteção das mídias;
revogação de sessões; aceite da versão atual de Termos; proteção de cadastro com Turnstile;
receptor de comprovantes etários assinados; base de supervisão com acesso de menores
desabilitado por padrão; suporte e recursos privados; fila persistente de e-mail com
criptografia, expiração e novas tentativas; backups AES-GCM com fotografia consistente
do SQLite e mídias, envio opcional para armazenamento S3 privado e ferramenta de restauração.

A abertura geral é bloqueada no servidor enquanto houver pendências. O endereço de
apresentação também deixa de anunciar inscrições abertas quando as condições deixam de
ser atendidas. Existem controles automáticos e **declarações do operador**, identificados
separadamente. Nenhum campo marcado certifica conformidade ou garante ausência de falhas.

## Limites importantes

O ambiente de produção continua exigindo configuração real de HTTPS, disco persistente,
e-mail, antiautomação, aferição etária e cópia externa. A assinatura etária valida um emissor
configurado, não mede a confiabilidade do método dele. A supervisão não comprova parentesco.
As mensagens não têm criptografia de ponta a ponta. Não há escala distribuída: **uma instância,
um processo e SQLite**. Não rode vários workers sobre o mesmo banco/volume.

O cadastro geral não é liberado por um HTML no Cloudflare. Este servidor precisa estar em
uma hospedagem compatível, com API, banco e mídias. Não houve implantação, contratação ou
alteração no repositório do usuário nesta entrega.

A pasta `android/` e a demo 0.8 são referências legadas, não aplicativos compilados nem
implementações nativas dos controles 0.9. O escopo atualizado desta entrega é o site real.

## Testar e contribuir

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Os testes usam bancos temporários, contas fictícias e serviços simulados quando indicados.
Leia `docs/RESULTADOS-0.9.md` antes de interpretar uma aprovação como teste externo.

**Nunca publique** `.env`, `.env.production.local`, `.backup-key.local`, `data/`, bancos,
backups, e-mails, chaves privadas ou senhas. Preserve suas chaves e dados ao atualizar.
