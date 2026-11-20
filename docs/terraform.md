# Etapa automatizada em São Paulo (sa-east-1) — Terraform

Roteiro da **Fase 4** do [planejamento](planejamento.md): a mesma arquitetura montada à mão em Ohio ([ohio-manual.md](ohio-manual.md)), agora descrita em Terraform. Nomes e variáveis de ambiente seguem [contratos.md](contratos.md).

Tudo é parametrizado: região (`regiao`, padrão `sa-east-1`) e prefixo dos nomes (`prefixo`, padrão `cafe`) vêm de variáveis; AZs, conta e AMI são descobertas na hora. Não há ID de conta no repositório nem **nenhuma dependência de Ohio**: o ambiente sobe do zero numa conta vazia (e pode ser recriado em outra região só trocando `regiao`).

**Um único `terraform apply` cria tudo, sem passo manual**: rede, dados, cluster, build e push das imagens, valor do segredo, catálogo inicial, ALB, serviços, auto scaling e alarmes. A ordem sai das dependências entre os recursos (não há `-target`).

```
infra/
  bootstrap/            bucket S3 do state (aplicado uma vez, state local)
  modules/              network, alb, data, cluster, images, service (2x), observability
  envs/sa-east-1/       composição do ambiente (backend, providers, main, outputs)
```

| O que antes era manual | Agora, dentro do `apply` |
|---|---|
| `apply -target` para criar o ECR primeiro | Os serviços dependem do push, que depende do ECR |
| `docker build` / `docker push` | Módulo `images` (provider `kreuzwerker/docker`); tag = hash do código de `app/<serviço>` |
| `put-secret-value` da chave do LLM | `aws_secretsmanager_secret_version` com atributo write-only (o valor não vai para o state) |
| `scripts/seed.py` | 10 itens `aws_dynamodb_table_item` em `modules/data/catalogo.tf` |

> **Custo**: o NAT Gateway e o ALB cobram por hora desde o primeiro `apply`. Ao terminar, siga [Desligar](#desligar).

## Pré-requisitos

- Terraform >= 1.11 (atributos write-only; o backend usa a trava nativa do S3).
- AWS CLI v2 logada com credenciais que possam criar os recursos (`aws configure` ou `aws configure sso` + `aws sso login`).
- **Docker rodando** (Docker Desktop no Windows/Mac): o `apply` faz o build e o push. No Windows o Terraform usa o named pipe do Docker Desktop sozinho; em outro endereço, defina `docker_host` no `terraform.tfvars`.
- Git Bash **aberto na raiz do repositório** (ou PowerShell; os comandos são os mesmos, só muda o jeito de definir variáveis de ambiente).

Em todo terminal novo (Git Bash):

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
- `terraform.tfvars`: `llm_modo` (`fake` ou `real`); `llm_base_url` e `model_id` só são exigidos no modo `real`. A chave do LLM **não** vai em arquivo nenhum (passo 3).

```bash
terraform -chdir=$ENV init -backend-config=backend.hcl
```

O `.terraform.lock.hcl` é commitado (fixa as versões dos providers `aws` e `docker`).

## 3. Chave do LLM (opcional, só no modo `real`)

A chave entra por variável de ambiente e é gravada no Secrets Manager como valor **write-only**: o Terraform envia à AWS e não guarda nem no plano nem no state. Sem chave, ou com `llm_modo = "fake"`, o segredo recebe o placeholder `modo-fake` (a task do `chat-api` precisa de algum valor para iniciar).

Git Bash (não ecoa nem fica no histórico):

```bash
read -rs -p "Chave do LLM: " TF_VAR_llm_api_key; echo; export TF_VAR_llm_api_key
```

PowerShell:

```powershell
$env:TF_VAR_llm_api_key = Read-Host "Chave do LLM" -MaskInput   # PowerShell 7
```

O segredo só é regravado quando a versão muda: ao trocar `llm_modo` ou ao incrementar `llm_api_key_versao` no `terraform.tfvars` (troca de chave). Nos outros `apply` a variável pode ficar vazia sem apagar a chave gravada.

> Cuidado: o `apply` que **passa para** `llm_modo = "real"` precisa já ter `TF_VAR_llm_api_key` definida. Se esquecer, o segredo fica com o placeholder; defina a variável, incremente `llm_api_key_versao` e rode o `apply` de novo.

### Variáveis opcionais do `terraform.tfvars`

| Variável | Padrão | Para quê |
|---|---|---|
| `email_alertas` | `""` | E-mail assinado no tópico `<prefixo>-alertas`. Vazio = sem assinatura. A AWS manda um e-mail de confirmação; até clicar no link a assinatura fica `PendingConfirmation` |
| `chat_api_cpu_alvo` | `60` | Alvo de CPU média (%) do target tracking do `chat-api` |
| `chat_api_requisicoes_por_task` | `600` | Alvo de requisições por task por minuto (`ALBRequestCountPerTarget`) do `chat-api` |
| `worker_backlog_por_task` | `20` | Alvo de mensagens visíveis na fila por task do `order-worker` |
| `worker_cooldown_saida` | `30` | Cooldown de scale-out do `order-worker` (s) |
| `worker_cooldown_entrada` | `120` | Cooldown de scale-in do `order-worker` (s) |
| `docker_host` | automático | Endereço do Docker usado no build |
| `llm_api_key_versao` | `1` | Incremente para regravar a chave do LLM |

## 4. `apply`

```bash
terraform -chdir=$ENV apply
```

A primeira vez é a mais demorada (NAT, build das imagens, instâncias entrando no cluster). Depois disso:

- Mudou código em `app/chat-api` ou `app/order-worker`: o `apply` refaz só a imagem que mudou (tag nova = hash novo), cria uma revisão da task definition e o ECS faz o rolling deploy. Sem mudança no código, nada é refeito.
- O catálogo é criado uma vez e depois ignorado pelo Terraform (`ignore_changes`): o estoque baixado pelo worker não é "corrigido". Para recarregar os valores iniciais, rode `scripts/seed.py` (opcional, ver [Resetar o estoque](#resetar-o-estoque)).

> IAM é global na conta. Por isso as roles e o instance profile levam a região no nome (`cafe-sa-east-1-...`) e não colidem com as roles criadas à mão em Ohio (`cafe-...`).

### Recriar do zero o ambiente que já existe

A pilha de São Paulo que está no ar foi criada antes desta automação: os itens do catálogo e o valor do segredo foram gravados fora do Terraform (`seed.py` e `put-secret-value`). **Não é preciso importar nada**: o `destroy` apaga a tabela (com os itens) e o segredo (sem janela de recuperação), e o `apply` seguinte cria tudo pelo Terraform.

```bash
# Antes: tirar "imagem_tag" do terraform.tfvars (a variável não existe mais) e
# deixar o Docker rodando (o provider docker é configurado também no destroy).
terraform -chdir=$ENV init -backend-config=backend.hcl -upgrade   # baixa o provider docker
terraform -chdir=$ENV destroy
terraform -chdir=$ENV apply
```

Sem o `destroy`, o `apply` tentaria criar itens que já existem na tabela e uma versão nova por cima do segredo gravado à mão; o caminho previsto é destruir e recriar.

## Escala das tasks

| Serviço | Políticas de target tracking | Cooldown saída / entrada |
|---|---|---|
| `chat-api` (2 a 8 tasks) | CPU média 60% **e** `ALBRequestCountPerTarget` 600 req/task/min | 60 s / 120 s |
| `order-worker` (1 a 4 tasks) | Mensagens visíveis na fila ÷ tasks rodando, alvo 20 | 30 s / 120 s |

Com duas políticas no mesmo serviço, o Application Auto Scaling escala para fora quando **qualquer uma** pede e só escala para dentro quando **todas** permitem. A de requisições usa como `resource_label` os sufixos dos ARNs do ALB e do target group (`app/<alb>/<id>/targetgroup/<tg>/<id>`). Ela cobre o caso que a CPU não enxerga: uma conversa real fica 1 a 3 s esperando o LLM, com a task ociosa, então a CPU fica baixa mesmo com o chat cheio. O alvo de 600 req/task/min (10 req/s por task) foi calibrado no ensaio da versão B ([evidencias.md](evidencias.md)): o primeiro valor, 1500, não disparou com ~70 req/s de requisições leves em 3 tasks (~1 400 por task), enquanto a CPU ficava entre 10% e 37%.

No worker o alvo caiu de 100 (Ohio) para 20 mensagens por task e o scale-out ficou com 30 s: no ensaio, a escala de 1 → 4 chegou só depois da fila vazia, por causa do atraso das métricas do SQS. Com alvo menor o primeiro passo de escala vem mais cedo; o scale-in continua com 120 s para não oscilar.

## Alarmes

Os 10 alarmes publicam no tópico SNS `<prefixo>-alertas` (assinatura de e-mail por `email_alertas`). Limiares calibrados com os números dos ensaios de [evidencias.md](evidencias.md):

| Alarme | Condição | Por quê |
|---|---|---|
| `cafe-chat-api-tasks-abaixo`, `cafe-order-worker-tasks-abaixo` | desejado − rodando > 0 por 5 min | Tasks novas ficaram até ~3 min pendentes no scale-out (imagem baixando, espera por EC2 nova) e a reposição de task/instância levou 1 a 1,5 min; 5 min separa isso de falta real de capacidade |
| `cafe-cluster-CPUReservation-alta`, `cafe-cluster-MemoryReservation-alta` | > 85% por 5 min | A reserva de memória ficou no teto ~3 min até o Capacity Provider subir EC2 nova; passar de 5 min indica ASG no máximo ou instância que não sobe |
| `cafe-asg-instancias-abaixo` | InService < `asg_min` por 3 min | A EC2 terminada foi reposta em 1 a 1,5 min; acima de 3 min o ASG não está repondo |
| `cafe-alb-5xx` | 5XX (tasks + ALB) > 1% das respostas por 2 min, com ≥ 20 req/min | Saturando o chat (CPU até 337%) a taxa de erro foi 0,04% (38 em 103 969); 1% é ~25× isso e pega task quebrada ou ALB sem alvo saudável. O piso de 20 req/min evita alarme por um erro isolado com pouco tráfego |
| `cafe-tg-hosts-nao-saudaveis` | UnHealthyHostCount > 0 por 3 min | Com task parada ou EC2 perdida o alvo foi trocado em ~1 min sem erro no ALB; 3 min indica alvo preso falhando no `/health` |
| `cafe-fila-mensagem-antiga` | mensagem mais antiga > 10 min por 2 min | 6000 pedidos foram consumidos por um worker em ~5 min (1300 a 1800/min); o dobro disso é worker parado, falhando ou no máximo |
| `cafe-dlq-com-mensagens` | DLQ > 0 | Qualquer pedido que falhou 3 vezes precisa de análise (demonstrado com a mensagem inválida) |
| `cafe-erros-no-log` | ≥ 1 linha de erro no minuto | Os testes de carga não geraram nenhuma; só a mensagem inválida da DLQ. Metric filter com o padrão de termos `?ERROR ?CRITICAL`: casa com qualquer linha que contenha um dos termos, no log em texto ou em JSON (`"level":"ERROR"`, `"nivel":"ERROR"`) |

## IAM

- **Task roles** (`chat-api`, `order-worker`): só as ações usadas, cada uma nos ARNs das tabelas e da fila (ver [arquitetura.md](arquitetura.md)).
- **Execução das tasks**: política própria em vez da `AmazonECSTaskExecutionRolePolicy` (que libera ECR e logs em `*`). Pull só nos 2 repositórios do projeto, logs só nos log groups `/ecs/<prefixo>/*`, `GetSecretValue` só no segredo do LLM. A única ação em `*` é `ecr:GetAuthorizationToken`, que não aceita restrição por recurso.
- **Instâncias**: `AmazonEC2ContainerServiceforEC2Role` + `AmazonSSMManagedInstanceCore`, as gerenciadas que a AWS indica para o agente do ECS e o SSM. Várias ações delas (`ecs:DiscoverPollEndpoint`, `ssm:UpdateInstanceInformation` etc.) não aceitam restrição por recurso; a exceção fica nessa role, que os containers não herdam (IMDSv2 com hop limit 1).

## 5. Validação

```bash
URL=$(terraform -chdir=$ENV output -raw url_alb)
curl -s $URL/health; echo                      # {"status":"ok"}
curl -s $URL/produtos | head -c 300; echo

# Smoke test (health, catálogo, pedido CONFIRMADO e REJEITADO). Exige llm_modo = "fake".
API_URL=$URL bash scripts/smoke-test.sh

terraform -chdir=$ENV output imagens            # repositorio:tag enviados ao ECR
```

Os alvos do ALB levam 1 a 2 minutos para ficarem saudáveis depois do primeiro `apply`. Para usar o LLM de verdade: `llm_modo = "real"` (e `llm_base_url`, `model_id`) no `terraform.tfvars`, chave em `TF_VAR_llm_api_key` (passo 3) e `terraform -chdir=$ENV apply`.

Os alarmes publicam no tópico SNS `<prefixo>-alertas`. Para receber e-mail, defina `email_alertas` no `terraform.tfvars` e confirme pelo link que a AWS envia ([Alarmes](#alarmes)).

### Resetar o estoque

Depois de uma demonstração (ex.: `scripts/enfileirar-pedidos.py`), volta o catálogo aos valores iniciais. Exige Python com `pip install -r scripts/requirements.txt`:

```bash
unset DYNAMODB_ENDPOINT_URL      # senão o seed tenta o DynamoDB Local
TABELA_PRODUTOS=$(terraform -chdir=$ENV output -raw tabela_produtos_nome) \
  python scripts/seed.py
```

Os dados de `scripts/seed.py` e de `infra/modules/data/catalogo.tf` são os mesmos: ao mudar o catálogo, mude os dois.

## Desligar

```bash
terraform -chdir=$ENV destroy
```

Com o Docker rodando (o Terraform consulta as imagens locais ao montar o plano). Apaga tudo do ambiente, inclusive imagens do ECR (`force_delete`), itens do catálogo e o segredo sem janela de recuperação (dá para recriar no mesmo dia).

O que fica:

- **Bucket do state** (bootstrap), de propósito: tem `force_destroy = false` e guarda o histórico do state. Custo desprezível. Para apagar de vez, esvazie o bucket (todas as versões) e rode `terraform -chdir=infra/bootstrap destroy`.
- Imagens locais `<conta>.dkr.ecr.<regiao>.amazonaws.com/cafe/*` no Docker da máquina (`keep_locally`). Apague com `docker image rm` se quiser.
- Log group do Container Insights (`/aws/ecs/containerinsights/<prefixo>-cluster/performance`), criado pela própria AWS e não pelo Terraform. Pode ser apagado à mão.
- Nada do SNS: a assinatura de `email_alertas` é apagada com o tópico.
