# Migrar os dados da versão Python 0.9

A mudança é de armazenamento e execução. O banco SQLite e a pasta de mídia antigos não passam a funcionar no Worker só porque foram enviados ao GitHub. O utilitário abaixo converte uma cópia para **D1 novo e R2 privado**. Ele não altera o banco original nem faz upload.

Se você só usou a demonstração HTML, não há contas reais dessa demonstração para migrar. Faça uma instalação nova. Se já há uma rede funcionando, mantenha a instalação anterior disponível para recuperação e reserve uma janela sem novas publicações.

## 1. Parar e preservar a origem

Pare o servidor Python. Copie o banco SQLite, a pasta `data/media`, as configurações privadas, `ADMIN_ENCRYPTION_KEY` e as chaves de backup para um local privado. Confira que consegue abrir essa cópia com a versão anterior.

Use recursos Cloudflare **novos**, sem contas criadas, e aplique `migrations/0001_initial.sql` pelo comando de migrations. O importador recusa o destino com contas, mas não é uma ferramenta de mesclagem. Não execute contra a instalação ativa.

## 2. Preparar as chaves do 2FA

Contas e senhas são preservadas. A senha usa o hash PBKDF2 anterior; não é preciso conhecer a senha de cada pessoa.

Se alguma conta administrativa tem 2FA habilitado, a proteção do segredo muda de Fernet para AES-256-GCM. Para esta implantação nova, `node scripts/setup.mjs --secrets` gera a nova chave em `.private/first-install-secrets.json`; use o valor `ADMIN_ENCRYPTION_KEY` desse arquivo. Guarde a chave antiga em `.private/legacy-admin-key.txt` e a nova chave de 32 bytes em base64url em `.private/new-admin-key.txt`, **somente o valor, sem `NOME=` nem aspas**. A nova chave deve ser o valor de `ADMIN_ENCRYPTION_KEY` do Worker. Os arquivos não devem ir ao GitHub.

Instale a dependência para essa conversão no seu ambiente Python:

```bash
python -m pip install cryptography==46.0.4
```

A conversão preserva o autenticador ativo, o último contador usado e os hashes dos códigos de recuperação. Códigos de recuperação existentes continuam privados; o utilitário não os revela nem gera outros.

## 3. Criar o pacote privado de migração

Na raiz do projeto novo, substitua os caminhos pelos da cópia antiga:

```bash
python scripts/migrate.py --database "CAMINHO/synapse.db" --media "CAMINHO/media" --output migration-output --server-stopped --legacy-admin-key-file .private/legacy-admin-key.txt --new-admin-key-file .private/new-admin-key.txt
```

Sem 2FA habilitado na origem, omita os dois argumentos de arquivo de chave. `--server-stopped` é sua confirmação de que parou o servidor; o programa não encerra nenhum processo.

O programa confere a integridade do banco, referências de mídia, hashes e contagens, e reproduz o SQL gerado em outro banco temporário. Se encontrar um arquivo ausente, tabela/coluna desconhecida ou chave incorreta, interrompe e remove a saída incompleta. Ele não sobrescreve uma pasta de saída existente.

A saída inclui:

| Arquivo | Uso |
|---|---|
| `migration-output/import.sql` | Dados transformados; contém informações privadas |
| `migration-output/media/` | Cópia das mídias referenciadas pelo banco |
| `migration-output/manifest.json` | Hashes, contagens e registros temporários descartados |

Os dados sociais, mensagens, perfis, permissões e histórico são preservados. Sessões, links de recuperação/confirmação, convites de supervisão, fila antiga de e-mails, concessões administrativas, sinais de chamada, push e evidências de integrações são invalidados. Os convites gerais ficam revogados; cadastros ficam fechados e manutenção ligada. Políticas exigem nova revisão, e usuários precisam aceitar os termos e verificar novamente sua faixa etária no ambiente novo.

Vídeos existentes são copiados para preservar os arquivos, mas isso não habilita o processamento de vídeo no Worker. Não prometa equivalência dos recursos experimentais do Python; confira as limitações da entrega.

## 4. Importar somente em recursos novos

No ambiente autenticado com a Cloudflare, com o binding `DB` apontando ao banco novo:

```bash
npx wrangler d1 execute DB --remote --file=migration-output/import.sql
node scripts/upload-media.mjs --directory migration-output --bucket synapse-media
```

O segundo comando apenas valida as mídias e informa o destino. Para enviá-las explicitamente:

```bash
node scripts/upload-media.mjs --directory migration-output --bucket synapse-media --upload
```

Troque `synapse-media` pelo nome privado configurado. O utilitário confirma o hash antes do envio e usa os mesmos nomes de arquivo. Não habilite acesso público direto ao bucket. Se ocorrer falha durante importação SQL, recrie um **destino novo vazio** e repita a importação; não tente mesclar um estado parcialmente importado com o original. Se o envio de mídias falhar, repetir o comando usa as mesmas chaves e bytes verificados.

## 5. Conferir antes de mudar o endereço

Publique o Worker, configure a nova chave administrativa e os demais serviços e entre com a conta existente. Confirme o 2FA e confira as contagens do manifesto com o banco hospedado. Teste publicações e mídias de contas públicas e privadas, bloqueios, mensagens e atendimento.

Mantenha cadastros fechados até concluir a revisão de políticas e as verificações do ambiente real. Só retire manutenção e troque o endereço divulgado depois de validar a instalação. Guarde a origem e o pacote de migração em local privado por um período de recuperação definido pelo responsável.

## Limites da ferramenta

A reprodução local do SQL não substitui uma restauração em D1/R2 real. Não valida fornecedor etário, entrega de e-mail, DNS, HTTPS, cobranças ou capacidade. Esta migração suporta o esquema 0.9 incluído no pacote; adaptações particulares que acrescentaram tabelas/colunas precisam de revisão específica para evitar perda de dados.
