# Etapa automatizada em São Paulo (sa-east-1) — Terraform

Roteiro da **Fase 4** do [planejamento](planejamento.md): a mesma arquitetura montada à mão em Ohio ([ohio-manual.md](ohio-manual.md)), agora descrita em Terraform. Nomes e variáveis de ambiente seguem [contratos.md](contratos.md).

Tudo é parametrizado: região (`regiao`, padrão `sa-east-1`) e prefixo dos nomes (`prefixo`, padrão `cafe`) vêm de variáveis; AZs, conta e AMI são descobertas na hora. Não há ID de conta no repositório nem **nenhuma dependência de Ohio**: o ambiente sobe do zero numa conta vazia (e pode ser recriado em outra região só trocando `regiao`).

```
infra/
  bootstrap/            bucket S3 do state (aplicado uma vez, state local)
  modules/              network, alb, data, cluster, service (2x), observability
  envs/sa-east-1/       composição do ambiente (backend, providers, main, outputs)
```

> **Custo**: o NAT Gateway e o ALB cobram por hora desde o primeiro `apply`. Ao terminar, siga [Desligar](#desligar).

## Pré-requisitos

- Terraform >= 1.10 (o backend usa a trava nativa do S3, `use_lockfile`).
- AWS CLI v2 com credenciais que possam criar os recursos (`aws configure` ou `aws configure sso`).
- Docker Desktop rodando (build das imagens).
- Python 3.12 com `pip install -r scripts/requirements.txt` (seed do catálogo).
- Git Bash **aberto na raiz do repositório**.

Em todo terminal novo:

```bash
export MSYS_NO_PATHCONV=1        # Git Bash: não converter argumentos que começam com "/"
export AWS_PAGER=""
export AWS_REGION=sa-east-1      # a mesma região de var.regiao
ENV=infra/envs/sa-east-1
```

---

## 1. Bootstrap do state (uma vez por conta)

Cria o bucket do state remoto (versionado, criptografado, sem acesso público). O nome leva o ID da conta e a região, por isso não fica fixo em nenhum arquivo. O state do próprio bootstrap é local (`infra/bootstrap/terraform.tfstate`, fora do git).

```bash
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
terraform -chdir=infra/bootstrap output -raw bucket_nome; echo
```

## 2. Configurar o ambiente e `init`

```bash
cp $ENV/backend.hcl.example $ENV/backend.hcl              # fora do git
cp $ENV/terraform.tfvars.example $ENV/terraform.tfvars    # fora do git
```

- `backend.hcl`: `bucket` = saída do passo 1; `region` = região do bucket.
- `terraform.tfvars`: `imagem_tag` = hash curto do commit (`git rev-parse --short HEAD`); `llm_modo` (`fake` ou `real`); `llm_base_url` e `model_id` só são exigidos no modo `real`. A chave do LLM **não** vai no tfvars (ver passo 3.2).

```bash
terraform -chdir=$ENV init -backend-config=backend.hcl
```

O `.terraform.lock.hcl` gerado é commitado (fixa as versões do provider).

## 3. Primeiro `apply` (ordem importa só desta vez)

Os serviços ECS precisam de imagens que ainda não existem, e o `chat-api` precisa de um valor no segredo para iniciar. Por isso o primeiro deploy é em etapas.

### 3.1 Rede, dados e cluster (cria os repositórios ECR)

```bash
terraform -chdir=$ENV apply -target=module.network -target=module.data -target=module.cluster
```

Os três módulos vão juntos: só `-target=module.cluster` traria a VPC e as sub-redes privadas (dependências diretas), mas **não** o NAT, as rotas nem as regras dos security groups — as EC2 subiriam sem saída para a internet e não entrariam no cluster. O aviso do Terraform sobre `-target` é esperado.

> IAM é global na conta. Por isso as roles e o instance profile levam a região no nome (`cafe-sa-east-1-...`) e não colidem com as roles criadas à mão em Ohio (`cafe-...`).

### 3.2 Build e push das imagens

A tag tem que ser a mesma de `imagem_tag` no `terraform.tfvars`. Faça commit antes: a tag reflete o `HEAD`.

```bash
TAG=$(git rev-parse --short HEAD)                              # = imagem_tag
REPO_CHAT=$(terraform -chdir=$ENV output -raw ecr_chat_api_url)
REPO_WORKER=$(terraform -chdir=$ENV output -raw ecr_order_worker_url)
ECR_REGISTRY=${REPO_CHAT%%/*}                                  # <conta>.dkr.ecr.<regiao>.amazonaws.com

# Login no ECR gravando o token num config.json temporário, fora do repositório
# (no Windows o gerenciador de credenciais não aceita o token do ECR; ver ohio-manual.md, passo 7).
DOCKER_CFG_DIR="$HOME/.docker-ecr-tf"; mkdir -p "$DOCKER_CFG_DIR"
AUTH=$(printf 'AWS:%s' "$(aws ecr get-login-password)" | base64 -w0)
printf '{"auths":{"%s":{"auth":"%s"}}}' "$ECR_REGISTRY" "$AUTH" > "$DOCKER_CFG_DIR/config.json"; unset AUTH
export DOCKER_CONFIG="$(cygpath -w "$DOCKER_CFG_DIR")"
# (Em Linux/Mac basta: aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REGISTRY)

# --platform linux/amd64: as instâncias são x86_64
docker build --platform linux/amd64 -t $REPO_CHAT:$TAG app/chat-api
docker build --platform linux/amd64 -t $REPO_WORKER:$TAG app/order-worker
docker push $REPO_CHAT:$TAG
docker push $REPO_WORKER:$TAG
```

### 3.3 Valor do segredo (fora do Terraform)

O Terraform cria só o recipiente do segredo; o valor nunca passa por ele (não vai para o state). Grave-o lendo de uma variável de ambiente, sem ecoar a chave nem deixá-la no histórico:

```bash
SEGREDO_ARN=$(terraform -chdir=$ENV output -raw segredo_arn)
read -rs -p "Cole a chave do LLM e tecle Enter: " LLM_CHAVE; echo
aws secretsmanager put-secret-value --secret-id "$SEGREDO_ARN" --secret-string "$LLM_CHAVE" \
  --query VersionStages --output text
unset LLM_CHAVE
```

No modo `fake` ainda é preciso **algum** valor (sem ele a task do `chat-api` não inicia): digite qualquer texto, ex.: `sem-chave`.

### 3.4 Seed do catálogo

```bash
unset DYNAMODB_ENDPOINT_URL      # senão o seed tenta o DynamoDB Local
TABELA_PRODUTOS=$(terraform -chdir=$ENV output -raw tabela_produtos_nome) \
  python scripts/seed.py
```

(`AWS_REGION` já foi exportada no início.) Rodar de novo "reseta" o estoque.

### 3.5 `apply` completo

```bash
terraform -chdir=$ENV apply
```

Cria ALB, serviços, auto scaling e alarmes. Os próximos deploys são só `apply` (com nova `imagem_tag` depois de um novo build/push).

## 4. Validação

```bash
URL=$(terraform -chdir=$ENV output -raw url_alb)
curl -s $URL/health; echo                      # {"status":"ok"}
curl -s $URL/produtos | head -c 300; echo

# Smoke test (health, catálogo, pedido CONFIRMADO e REJEITADO). Exige llm_modo = "fake".
API_URL=$URL bash scripts/smoke-test.sh
```

Os alvos do ALB levam 1 a 2 minutos para ficarem saudáveis depois do primeiro `apply`. Para usar o LLM de verdade: `llm_modo = "real"` (e `llm_base_url`, `model_id`) no `terraform.tfvars`, chave real no segredo (passo 3.3) e `terraform -chdir=$ENV apply`.

Os alarmes publicam no tópico SNS `<prefixo>-alertas` sem assinatura. Para receber e-mail, assine pelo console ou com `aws sns subscribe` (fica fora do state).

## Desligar

```bash
terraform -chdir=$ENV destroy
```

Apaga tudo do ambiente, inclusive imagens do ECR (`force_delete`) e o segredo sem janela de recuperação (dá para recriar no mesmo dia).

O que fica:

- **Bucket do state** (bootstrap), de propósito: tem `force_destroy = false` e guarda o histórico do state. Custo desprezível. Para apagar de vez, esvazie o bucket (todas as versões) e rode `terraform -chdir=infra/bootstrap destroy`.
- Log group do Container Insights (`/aws/ecs/containerinsights/<prefixo>-cluster/performance`), criado pela própria AWS e não pelo Terraform. Pode ser apagado à mão.
- Uma assinatura de e-mail do SNS feita à mão some junto com o tópico.
