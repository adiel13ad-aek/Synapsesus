# Contrato de sinal etário — Synapse 0.9

**Estado:** receptor implementado; nenhum fornecedor externo conectado. Os testes usam
chaves sintéticas temporárias. Este protocolo é específico do projeto, não um padrão
oficial de aferição nem uma integração pronta com qualquer fornecedor comercial.

O objetivo é receber o mínimo necessário: uma faixa etária assinada, sem armazenar
nome civil, documento, fotografia, biometria ou data de nascimento no Synapse. O método
real do fornecedor e sua confiabilidade precisam de avaliação independente. Uma assinatura
válida prova a origem/integridade do sinal de um emissor configurado, não a idade por si só.

## Configuração

- `AGE_PROVIDER_URL`: endpoint HTTPS de início da aferição; não pode conter credenciais ou fragmento.
- `AGE_PROVIDER_ID`: identificador exato do emissor esperado.
- `AGE_PUBLIC_KEY`: chave pública Ed25519 raw32 em base64url.
- `PUBLIC_ORIGIN`: origem HTTPS exata da instalação, sem barra final.

Nunca use a chave privada do emissor no site. Nunca use os emissores sintéticos dos testes
em produção. Um adaptador deve verificar a evidência REAL do fornecedor antes de assinar.
Não implemente assinatura baseada apenas em data informada pelo usuário.

## Fluxo

1. Conta autenticada e e-mail confirmado chama `POST /api/account/age/start` com JSON vazio,
   CSRF e `X-Synapse-Client: web-v09`.
2. O servidor cria um desafio opaco de uso único, vinculado à conta, com validade de 15 minutos.
   Retorna a URL externa com `challenge`, `audience` e `return_url` como parâmetros.
   O desafio não é credencial de login e sua forma hash é o que fica no banco.
3. O fornecedor executa seu método de aferição e o adaptador emite um recibo curto.
4. Redireciona para `return_url#age_receipt=RECIBO`. O receptor remove o fragmento da barra
   de endereço e envia o recibo ao servidor autenticado. Fragmentos não vão no request HTTP
   inicial. O usuário precisa continuar com a conta vinculada ao desafio.
5. O servidor valida assinatura, emissor, origem, faixa, prazos, desafio e uso único.

## Formato exato do recibo

```text
base64url(JSON_UTF8_SEM_PADDING).base64url(ASSINATURA_ED25519_SEM_PADDING)
```

A assinatura cobre os bytes ASCII do **primeiro componente já codificado**. O JSON deve
conter exatamente as chaves abaixo; campos extras são rejeitados:

```json
{
  "v": 1,
  "iss": "identificador-do-emissor-configurado",
  "aud": "https://ORIGEM-EXATA-DO-SYNAPSE",
  "challenge": "desafio-recebido-do-servidor",
  "band": "adult",
  "iat": 0,
  "exp": 180
}
```

Os zeros acima são ilustrativos, **não timestamps válidos**. `iat` e `exp` são segundos
Unix reais, `exp > iat`, validade máxima de 300 segundos. Há tolerância de relógio de
30 segundos para `iat` futuro. A faixa aceita é `under_13`, `13_15`, `16_17` ou `adult`.
A verificação local da faixa tem validade de 30 dias nesta implementação, uma escolha
operacional que precisa ser reavaliada conforme fornecedor e público, não regra legal.

O servidor guarda faixa, identificador do emissor e validade. Não guarda o recibo bruto.
A chave pública e a configuração devem ficar sob controle da operação. Rotacionar emissor,
URL ou chave invalida a evidência de integração usada para liberar inscrições; valide
a nova configuração novamente com conta autorizada.

## Restrições implementadas

Em produção, e-mail e sinal de faixa são exigidos antes de atividade social. Menores de
13 não recebem acesso social nesta versão. Por padrão, todo acesso social de menores
fica desabilitado. Habilitar as faixas 13–17 exige revisão e vínculo de uma conta adulta
confirmada; isso é uma escolha conservadora deste produto, não transcrição de faixa legal.

Receber sinal de menor força perfil privado, desliga mensagens/chamadas e assinaturas
push e converte seguidores existentes em pedidos de aprovação. Conteúdo recomendado e
busca externa ficam restritos. Um adulto vinculado pode pausar atividades sociais e
aprovar seguidores; ele não recebe acesso a conversas ou senha. O vínculo usa e-mail,
senha, declaração de responsabilidade e verificação etária do adulto. **Não comprova
parentesco ou representação legal.** Esse ponto precisa de solução/revisão antes de
receber menores de forma geral. Retirar o vínculo pausa o acesso social, sem bloquear
suporte, exclusão de conta ou denúncias.

## Testes e aceitação do fornecedor

O pacote testa assinatura errada, emissor/origem incorretos, prazo inválido, campos extras,
faixa desconhecida, desafio de outra conta e replay. São testes locais, não testes do
método de aferição. Antes de lançamento, valide fluxo completo, recuperação de falhas,
acessibilidade, minimização de dados, consentimentos, contratos e proteção contra fraude
com o fornecedor escolhido. Não marque o controle de público como concluído só porque
uma assinatura de teste foi aceita.

Referência oficial de contexto, não aprovação do protocolo:
https://www.gov.br/anpd/pt-br/assuntos/eca-digital
