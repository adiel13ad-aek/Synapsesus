# Backups e restauração — Synapse 0.9

## Arquitetura e limites

O servidor possui uma fila persistente de trabalhos de backup. Uma rotina no processo
consulta a fila a cada ciclo e pode agendar cópias diárias quando `AUTO_BACKUP_ENABLED=1`.
Ela opera **somente em uma instância e um processo**. Não execute comandos externos que
alterem banco ou mídias ao mesmo tempo que uma captura.

Durante a captura, uma barreira recusa novas solicitações de API/mídias com HTTP 503 e
`Retry-After: 5`, aguarda as solicitações em andamento e copia o banco por SQLite Backup
API. As mídias são congeladas por hardlink ou cópia. Depois a barreira é liberada; compressão,
criptografia e envio externo acontecem fora dessa pausa. Processos externos e múltiplos
workers não participam da barreira e são incompatíveis com essa garantia local.

O arquivo contém banco, mídias e manifesto SHA-256; é criptografado com **AES-256-GCM**.
A chave tem 32 bytes e não está dentro do backup. O formato usa cabeçalho versionado,
nonce aleatório de 12 bytes, ciphertext e tag de 16 bytes. Não altere o arquivo à mão.

O diretório `data/backups` não é servido pela web. O armazenamento local guarda as cópias
mais recentes, com mínimo de duas. A retenção externa é configurada separadamente no
bucket. Defina prazo de retenção e acesso conforme as políticas reais da plataforma.
Backups podem conter dados posteriormente excluídos; não prometa apagamento imediato
de todas as cópias sem uma política e processo compatíveis.

## Configurar

Na primeira instalação, o assistente de produção gera `BACKUP_ENCRYPTION_KEY`. Em uma
atualização, use `python tools/generate_backup_key.py`. Guarde a chave no gerenciador de
segredos e outra cópia protegida fora do servidor. Preserve também `ADMIN_ENCRYPTION_KEY`,
necessária para os segredos administrativos restaurados.

O envio S3 usa `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_PREFIX`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_DEFAULT_REGION`. O endpoint customizado
exige HTTPS. O bucket não deve permitir leitura pública. Configure credencial de menor
privilégio e retenção no provedor. O envio é seguido de HEAD para conferir o tamanho;
isso **não é** teste de restauração ou garantia de durabilidade do fornecedor.

Estados visíveis: `queued`, `running`, `local_only`, `offsite`, `failed`.
“Somente no servidor” não satisfaz o requisito de backup externo. Uma falha pode deixar
uma cópia local válida, mas não é apresentada como sucesso externo. A periodicidade não
substitui um monitor externo: com o servidor fora do ar, a rotina não executa.

## Restaurar sem sobrescrever o ambiente ativo

1. Baixe uma cópia por um canal privado do seu provedor. Não torne o bucket público.
2. Em ambiente separado, instale `requirements-production.txt` e configure a
   `BACKUP_ENCRYPTION_KEY` original por variável de ambiente. Não cole a chave em comandos
   de terminal compartilhados nem no chat; prefira o gerenciador de segredos.
3. Execute, apontando para uma pasta nova:

```sh
python tools/restore_encrypted.py CAMINHO/arquivo.synapsebak --into restauracao-teste
```

A ferramenta autentica o arquivo **antes** de restaurar, usa uma pasta temporária privada,
valida manifesto, caminhos, checksums e integridade SQLite. Rejeita arquivo alterado, chave
incorreta e destino já ocupado. Não troca caminhos do servidor automaticamente.

Após restaurar, sessões, links de confirmação/recuperação, filas de e-mail, desafios de
idade, convites de responsável, assinaturas push e evidências de integração são invalidados.
**Manutenção fica ligada e inscrições fechadas.** Isso evita reenvio de links antigos ou
reabertura automática de um estado anterior. Contas, mídias e configuração social permanecem.

4. Aponte uma instalação isolada para o banco e mídias restaurados. Preserve a chave
   administrativa original. Confirme integridade, acesso administrativo e mídias.
5. Confira pedidos de exclusão, denúncias e decisões ocorridos depois da data da cópia.
   Restauração não recria automaticamente um histórico posterior ao backup.
6. Documente o teste. Somente depois planeje uma troca de ambiente, com servidor parado e
   cópia de segurança do estado atual. Não sobrescreva um banco aberto.

## Recuperação administrativa

Uma chave administrativa errada impede ler os segredos TOTP. Preserve a chave original;
não a regenere para “corrigir” isso. Perda do segundo fator pode ser tratada com códigos
de recuperação já guardados ou, pelo responsável no console confiável, com o comando
existente `python manage.py reset-admin-mfa SEU_USUARIO`. Isso revoga sessões e exige
novo cadastramento do autenticador. Nunca exponha esse console pela web.

## Evidência da entrega

Criptografia, detecção de adulteração, rejeição de chave errada, cópia local de SQLite e
mídias e restauração isolada foram executadas nos testes. Envio S3 foi simulado: nenhum
bucket real foi usado. Veja `RESULTADOS-0.9.md` para a distinção completa.
