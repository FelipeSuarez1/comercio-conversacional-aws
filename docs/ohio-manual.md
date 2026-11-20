# Etapa manual em Ohio (us-east-2) — roteiro com AWS CLI

Roteiro da **Fase 2** do [planejamento](planejamento.md): a mesma topologia da [arquitetura](arquitetura.md), montada na **versão C**, comando a comando, sem ferramenta de IaC. Os nomes e variáveis seguem [contratos.md](contratos.md). Cada recurso criado entra na [relação de recursos](ohio-recursos.md) (entregável).

Como ler cada passo: **objetivo** (por que o recurso existe), **comandos** e **verificação**. No fim de cada passo os IDs vão para `infra/ohio/.ids.env`, então dá para fechar o terminal e continuar outro dia.

Os arquivos em `infra/ohio/` (JSON de políticas, task definitions etc.) são só **entradas da CLI**, usadas com `file://`. Eles têm placeholders (`__CONTA__`, `__REGIAO__`...) que a função `renderizar` (passo 0) troca pelos valores reais, gravando uma cópia em `infra/ohio/.render/`. Essa pasta e o `.ids.env` estão no `.gitignore` porque contêm o ID da conta.

> **Custo**: a partir do passo 1 o NAT Gateway já cobra por hora; a partir do passo 9, o ALB também. Ao terminar uma sessão de testes, siga [Desligar para economizar](#desligar-para-economizar).

## Pré-requisitos

- AWS CLI v2 configurada (`aws configure` ou `aws configure sso`) com um usuário/role que possa criar os recursos.
- Docker Desktop rodando (para o build das imagens).
- Python 3.12 com `pip install -r scripts/requirements.txt` (para o seed).
- Git Bash, **aberto na raiz do repositório** (todos os `file://` usam caminho relativo a ela).

---

## Passo 0 — Preparar a sessão (rode em todo terminal novo)

Objetivo: fixar região e prefixo, descobrir a conta sem escrevê-la em arquivo nenhum e contornar três manias do Git Bash no Windows.

```bash
set -o pipefail

# 1) O Git Bash converte argumentos que começam com "/" em caminhos do Windows
#    (/ecs/cafe/chat-api viraria C:/Program Files/Git/ecs/...). Desligamos isso
#    para a sessão toda: nomes de log group, parâmetros SSM e o path do health check começam com "/".
export MSYS_NO_PATHCONV=1

# 2) Sem paginador (less) nas saídas da CLI.
export AWS_PAGER=""

# 3) A CLI no Windows termina as linhas com \r\n. Dentro de $(...) o \r sobra e quebra
#    o próximo comando ("Invalid id: vpc-123\r"). Esta função remove o \r de toda saída.
#    (Para comandos interativos, como "aws ssm start-session", use "command aws ...".)
aws() { command aws "$@" | tr -d '\r'; }

REGIAO=us-east-2
PREFIXO=cafe
export AWS_REGION=$REGIAO AWS_DEFAULT_REGION=$REGIAO

CONTA=$(aws sts get-caller-identity --query Account --output text)
IDS=infra/ohio/.ids.env

# Tags padrão em cada sintaxe que os serviços aceitam
TAGS_KV="Key=Projeto,Value=$PREFIXO Key=Etapa,Value=manual"     # IAM, DynamoDB, ECR, ELB, SNS, CloudWatch, Secrets
TAGS_EC2="{Key=Projeto,Value=$PREFIXO},{Key=Etapa,Value=manual}" # dentro de --tag-specifications
TAGS_ECS="key=Projeto,value=$PREFIXO key=Etapa,value=manual"     # ECS usa minúsculas
TAGS_MAPA="Projeto=$PREFIXO,Etapa=manual"                        # SQS e CloudWatch Logs

# Troca __NOME__ pelo valor da variável NOME e grava em infra/ohio/.render/.
# Uso: renderizar <arquivo em infra/ohio> [nome do arquivo de saída]
# Falha se sobrar algum placeholder (variável ainda não definida).
renderizar() {
  local origem="infra/ohio/$1" destino="infra/ohio/.render/${2:-$1}" nome args=()
  for nome in PREFIXO CONTA REGIAO SEGREDO_ARN FILA_URL AMI_ID SG_ECS USER_DATA_B64 \
              ASG_ARN TG_ARN IMAGEM_CHAT IMAGEM_WORKER LLM_MODO LLM_BASE_URL MODEL_ID SERVICO; do
    [ -n "${!nome:-}" ] && args+=(-e "s|__${nome}__|${!nome}|g")
  done
  mkdir -p infra/ohio/.render
  sed "${args[@]}" "$origem" > "$destino" || return 1
  if grep -o '__[A-Z0-9_]*__' "$destino" | sort -u | grep .; then
    echo "ERRO: placeholders acima sem valor em $destino" >&2; return 1
  fi
  echo "ok: $destino"
}

# Retomando uma sessão? Recarrega os IDs já criados.
[ -f "$IDS" ] && source "$IDS"
echo "Conta: $CONTA | Região: $AWS_REGION | Prefixo: $PREFIXO"
```

Verificação: a última linha mostra a conta e `us-east-2`. Se aparecer erro de credencial, rode `command aws configure` (ou `command aws sso login`) e repita.

> Se um passo for repetido, o `.ids.env` fica com a variável duas vezes; o `source` usa a última, que é a mais nova.

---

## Passo 1 — Rede

Objetivo: isolar a aplicação numa VPC própria em **2 AZs** (alta disponibilidade). As sub-redes públicas recebem só o ALB e o NAT; as instâncias ECS ficam nas privadas, sem IP público, e saem para a internet (ECR, CloudWatch, SQS, API do LLM) pelo NAT. Os endpoints Gateway de S3 e DynamoDB são gratuitos e tiram esse tráfego do NAT (as camadas das imagens do ECR ficam no S3).

```bash
# 2 AZs disponíveis na região (nada de nome fixo)
AZ1=$(aws ec2 describe-availability-zones \
  --filters Name=state,Values=available Name=zone-type,Values=availability-zone \
  --query 'AvailabilityZones[0].ZoneName' --output text)
AZ2=$(aws ec2 describe-availability-zones \
  --filters Name=state,Values=available Name=zone-type,Values=availability-zone \
  --query 'AvailabilityZones[1].ZoneName' --output text)
echo "AZs: $AZ1 $AZ2"

# VPC
VPC_ID=$(aws ec2 create-vpc --cidr-block 10.0.0.0/16 \
  --tag-specifications "ResourceType=vpc,Tags=[{Key=Name,Value=$PREFIXO-vpc},$TAGS_EC2]" \
  --query Vpc.VpcId --output text)
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames '{"Value":true}'

# Sub-redes: públicas (ALB, NAT) e privadas (instâncias ECS)
criar_subrede() {  # uso: criar_subrede <cidr> <az> <nome>
  aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block $1 --availability-zone $2 \
    --tag-specifications "ResourceType=subnet,Tags=[{Key=Name,Value=$3},$TAGS_EC2]" \
    --query Subnet.SubnetId --output text
}
SUBNET_PUB1=$(criar_subrede 10.0.0.0/24  $AZ1 $PREFIXO-publica-1)
SUBNET_PUB2=$(criar_subrede 10.0.1.0/24  $AZ2 $PREFIXO-publica-2)
SUBNET_PRIV1=$(criar_subrede 10.0.10.0/24 $AZ1 $PREFIXO-privada-1)
SUBNET_PRIV2=$(criar_subrede 10.0.11.0/24 $AZ2 $PREFIXO-privada-2)

# Internet Gateway: porta de entrada/saída das sub-redes públicas
IGW_ID=$(aws ec2 create-internet-gateway \
  --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Name,Value=$PREFIXO-igw},$TAGS_EC2]" \
  --query InternetGateway.InternetGatewayId --output text)
aws ec2 attach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID

# NAT Gateway (1 só, na pública da 1a AZ) com IP elástico
EIP_ALLOC=$(aws ec2 allocate-address --domain vpc \
  --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$PREFIXO-nat-eip},$TAGS_EC2]" \
  --query AllocationId --output text)
NAT_ID=$(aws ec2 create-nat-gateway --subnet-id $SUBNET_PUB1 --allocation-id $EIP_ALLOC \
  --tag-specifications "ResourceType=natgateway,Tags=[{Key=Name,Value=$PREFIXO-nat},$TAGS_EC2]" \
  --query NatGateway.NatGatewayId --output text)
aws ec2 wait nat-gateway-available --nat-gateway-ids $NAT_ID   # 1 a 3 minutos

# Tabela de rotas pública: 0.0.0.0/0 -> IGW
RT_PUB=$(aws ec2 create-route-table --vpc-id $VPC_ID \
  --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=$PREFIXO-rt-publica},$TAGS_EC2]" \
  --query RouteTable.RouteTableId --output text)
aws ec2 create-route --route-table-id $RT_PUB --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID
aws ec2 associate-route-table --route-table-id $RT_PUB --subnet-id $SUBNET_PUB1
aws ec2 associate-route-table --route-table-id $RT_PUB --subnet-id $SUBNET_PUB2

# Tabela de rotas privada (uma para as duas AZs, já que há um único NAT): 0.0.0.0/0 -> NAT
RT_PRIV=$(aws ec2 create-route-table --vpc-id $VPC_ID \
  --tag-specifications "ResourceType=route-table,Tags=[{Key=Name,Value=$PREFIXO-rt-privada},$TAGS_EC2]" \
  --query RouteTable.RouteTableId --output text)
aws ec2 create-route --route-table-id $RT_PRIV --destination-cidr-block 0.0.0.0/0 --nat-gateway-id $NAT_ID
aws ec2 associate-route-table --route-table-id $RT_PRIV --subnet-id $SUBNET_PRIV1
aws ec2 associate-route-table --route-table-id $RT_PRIV --subnet-id $SUBNET_PRIV2

# Endpoints Gateway (gratuitos) na tabela privada
VPCE_S3=$(aws ec2 create-vpc-endpoint --vpc-id $VPC_ID --vpc-endpoint-type Gateway \
  --service-name com.amazonaws.$REGIAO.s3 --route-table-ids $RT_PRIV \
  --tag-specifications "ResourceType=vpc-endpoint,Tags=[{Key=Name,Value=$PREFIXO-vpce-s3},$TAGS_EC2]" \
  --query VpcEndpoint.VpcEndpointId --output text)
VPCE_DDB=$(aws ec2 create-vpc-endpoint --vpc-id $VPC_ID --vpc-endpoint-type Gateway \
  --service-name com.amazonaws.$REGIAO.dynamodb --route-table-ids $RT_PRIV \
  --tag-specifications "ResourceType=vpc-endpoint,Tags=[{Key=Name,Value=$PREFIXO-vpce-dynamodb},$TAGS_EC2]" \
  --query VpcEndpoint.VpcEndpointId --output text)

{
  echo "AZ1=$AZ1"; echo "AZ2=$AZ2"; echo "VPC_ID=$VPC_ID"
  echo "SUBNET_PUB1=$SUBNET_PUB1"; echo "SUBNET_PUB2=$SUBNET_PUB2"
  echo "SUBNET_PRIV1=$SUBNET_PRIV1"; echo "SUBNET_PRIV2=$SUBNET_PRIV2"
  echo "IGW_ID=$IGW_ID"; echo "EIP_ALLOC=$EIP_ALLOC"; echo "NAT_ID=$NAT_ID"
  echo "RT_PUB=$RT_PUB"; echo "RT_PRIV=$RT_PRIV"
  echo "VPCE_S3=$VPCE_S3"; echo "VPCE_DDB=$VPCE_DDB"
} >> "$IDS"
```

Verificação: 4 sub-redes em 2 AZs, e a tabela privada com a rota padrão para o NAT e as duas rotas de prefix list (`pl-...`) dos endpoints.

```bash
aws ec2 describe-subnets --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[].[Tags[?Key==`Name`].Value|[0],CidrBlock,AvailabilityZone]' --output table
aws ec2 describe-route-tables --route-table-ids $RT_PRIV \
  --query 'RouteTables[0].Routes[].[DestinationCidrBlock||DestinationPrefixListId,NatGatewayId||GatewayId,State]' --output table
```

---

## Passo 2 — Security groups

Objetivo: menor privilégio na rede. Só o ALB é exposto (porta 80); as instâncias aceitam tráfego **apenas do ALB**, na faixa de portas dinâmicas que o ECS usa no modo `bridge`, e só saem por HTTPS. Removemos a regra de saída padrão ("tudo liberado") dos dois SGs. Não há SSH: o acesso às instâncias é pelo SSM Session Manager.

```bash
SG_ALB=$(aws ec2 create-security-group --vpc-id $VPC_ID --group-name $PREFIXO-alb-sg \
  --description "ALB: HTTP 80 da internet" \
  --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$PREFIXO-alb-sg},$TAGS_EC2]" \
  --query GroupId --output text)
SG_ECS=$(aws ec2 create-security-group --vpc-id $VPC_ID --group-name $PREFIXO-ecs-sg \
  --description "Instancias ECS: portas dinamicas somente a partir do ALB" \
  --tag-specifications "ResourceType=security-group,Tags=[{Key=Name,Value=$PREFIXO-ecs-sg},$TAGS_EC2]" \
  --query GroupId --output text)

# Remove a saída padrão (all traffic para 0.0.0.0/0) dos dois
for SG in $SG_ALB $SG_ECS; do
  aws ec2 revoke-security-group-egress --group-id $SG \
    --ip-permissions 'IpProtocol=-1,IpRanges=[{CidrIp=0.0.0.0/0}]'
done

# cafe-alb-sg: entra 80 da internet; sai só para as portas dinâmicas das instâncias
aws ec2 authorize-security-group-ingress --group-id $SG_ALB \
  --ip-permissions 'IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]'
aws ec2 authorize-security-group-egress --group-id $SG_ALB \
  --ip-permissions "IpProtocol=tcp,FromPort=32768,ToPort=65535,UserIdGroupPairs=[{GroupId=$SG_ECS}]"

# cafe-ecs-sg: entra só do ALB; sai só HTTPS (ECR, ECS, SSM, SQS, CloudWatch, LLM)
aws ec2 authorize-security-group-ingress --group-id $SG_ECS \
  --ip-permissions "IpProtocol=tcp,FromPort=32768,ToPort=65535,UserIdGroupPairs=[{GroupId=$SG_ALB}]"
aws ec2 authorize-security-group-egress --group-id $SG_ECS \
  --ip-permissions 'IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]'

{ echo "SG_ALB=$SG_ALB"; echo "SG_ECS=$SG_ECS"; } >> "$IDS"
```

> Descrições de SG só aceitam ASCII (sem acentos).
> DNS da VPC, metadados da instância (IMDS) e NTP da Amazon não passam pelos SGs, por isso a saída 443 basta.

Verificação: cada SG com exatamente uma regra de entrada e uma de saída.

```bash
aws ec2 describe-security-group-rules --filters Name=group-id,Values=$SG_ALB,$SG_ECS \
  --query 'SecurityGroupRules[].[GroupId,IsEgress,IpProtocol,FromPort,ToPort,CidrIpv4||ReferencedGroupInfo.GroupId]' \
  --output table
```

---

## Passo 3 — IAM

Objetivo: separar as permissões em **três tipos de role**, cada uma com o mínimo necessário:

| Role | Quem assume | Para quê |
|---|---|---|
| `cafe-ecs-instance-role` (+ instance profile) | EC2 | Agente do ECS registrar a instância no cluster; SSM para acesso sem SSH |
| `cafe-ecs-task-execution` | ECS (ao iniciar a task) | Baixar a imagem do ECR, escrever logs, ler **só** o segredo do LLM |
| `cafe-chat-api-task` / `cafe-order-worker-task` | O código dentro do container | Acessar exatamente as tabelas e a fila que cada serviço usa |

As políticas das task roles usam ARNs exatos das tabelas e da fila. Esses ARNs são previsíveis (região + conta + nome), então podem ser criados antes dos recursos. Já o ARN do segredo tem um sufixo aleatório: a política inline da role de execução entra no passo 4.

```bash
# Role da instância + instance profile
aws iam create-role --role-name $PREFIXO-ecs-instance-role \
  --assume-role-policy-document file://infra/ohio/confianca-ec2.json \
  --description "Instancias EC2 do cluster ECS" --tags $TAGS_KV --query Role.Arn --output text
aws iam attach-role-policy --role-name $PREFIXO-ecs-instance-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role
aws iam attach-role-policy --role-name $PREFIXO-ecs-instance-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name $PREFIXO-ecs-instance-profile \
  --tags $TAGS_KV --query InstanceProfile.Arn --output text
aws iam add-role-to-instance-profile --instance-profile-name $PREFIXO-ecs-instance-profile \
  --role-name $PREFIXO-ecs-instance-role

# Role de execução das tasks (a inline do segredo vem no passo 4)
aws iam create-role --role-name $PREFIXO-ecs-task-execution \
  --assume-role-policy-document file://infra/ohio/confianca-ecs-tasks.json \
  --description "Execucao das tasks: ECR, logs e segredo do LLM" --tags $TAGS_KV --query Role.Arn --output text
aws iam attach-role-policy --role-name $PREFIXO-ecs-task-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Task roles (uma por serviço)
renderizar politica-chat-api-task.json
renderizar politica-order-worker-task.json

aws iam create-role --role-name $PREFIXO-chat-api-task \
  --assume-role-policy-document file://infra/ohio/confianca-ecs-tasks.json \
  --description "Permissoes do codigo do chat-api" --tags $TAGS_KV --query Role.Arn --output text
aws iam put-role-policy --role-name $PREFIXO-chat-api-task --policy-name $PREFIXO-chat-api-acesso \
  --policy-document file://infra/ohio/.render/politica-chat-api-task.json

aws iam create-role --role-name $PREFIXO-order-worker-task \
  --assume-role-policy-document file://infra/ohio/confianca-ecs-tasks.json \
  --description "Permissoes do codigo do order-worker" --tags $TAGS_KV --query Role.Arn --output text
aws iam put-role-policy --role-name $PREFIXO-order-worker-task --policy-name $PREFIXO-order-worker-acesso \
  --policy-document file://infra/ohio/.render/politica-order-worker-task.json
```

Nenhum ID novo para gravar: os ARNs das roles são `arn:aws:iam::$CONTA:role/<nome>`.

Verificação: o simulador do IAM mostra o menor privilégio funcionando (`allowed` para o que o worker usa, `implicitDeny` para o resto), mesmo antes de as tabelas existirem.

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::$CONTA:role/$PREFIXO-order-worker-task \
  --action-names dynamodb:UpdateItem dynamodb:DeleteItem dynamodb:Scan \
  --resource-arns arn:aws:dynamodb:$REGIAO:$CONTA:table/$PREFIXO-pedidos \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output table
aws iam list-attached-role-policies --role-name $PREFIXO-ecs-instance-role \
  --query 'AttachedPolicies[].PolicyName' --output text
```

---

## Passo 4 — Secrets Manager

Objetivo: a chave da API do LLM nunca fica em código, imagem, variável comum ou Git. O ECS a lê do Secrets Manager no momento de iniciar a task e a injeta como `LLM_API_KEY`. Criamos o segredo **sem valor** e cada um coloca a chave pelo terminal.

```bash
SEGREDO_ARN=$(aws secretsmanager create-secret --name $PREFIXO/llm-api-key \
  --description "Chave da API do LLM usada pelo chat-api" --tags $TAGS_KV \
  --query ARN --output text)
echo "SEGREDO_ARN=$SEGREDO_ARN" >> "$IDS"

# Agora a role de execução pode ler este segredo (e só ele)
renderizar politica-execucao-segredo.json
aws iam put-role-policy --role-name $PREFIXO-ecs-task-execution --policy-name $PREFIXO-ler-segredo-llm \
  --policy-document file://infra/ohio/.render/politica-execucao-segredo.json
```

Gravar o valor (feito pelo próprio aluno, **não cole a chave direto na linha de comando**, senão ela vai para o `~/.bash_history`):

```bash
# Forma recomendada: a chave é digitada/colada sem aparecer na tela nem no histórico
read -rs -p "Cole a chave do LLM e tecle Enter: " LLM_CHAVE; echo
aws secretsmanager put-secret-value --secret-id "$SEGREDO_ARN" --secret-string "$LLM_CHAVE" \
  --query VersionStages --output text
unset LLM_CHAVE

# Forma literal (só se souber o que está fazendo; apague a linha do histórico depois):
# aws secretsmanager put-secret-value --secret-id "$SEGREDO_ARN" --secret-string '<COLE_A_CHAVE_AQUI>'
```

> O segredo **precisa ter um valor** antes do passo 10: sem ele, a task do `chat-api` nem inicia (o ECS falha ao buscar o segredo). Se ainda não houver chave, grave qualquer texto (ex.: `sem-chave`) e use `LLM_MODO=fake` no passo 10.

Verificação (mostra que existe uma versão `AWSCURRENT`, sem exibir o valor):

```bash
aws secretsmanager describe-secret --secret-id "$SEGREDO_ARN" \
  --query '{Nome:Name,Versoes:VersionIdsToStages}' --output json
```

---

## Passo 5 — DynamoDB + seed

Objetivo: persistência sem servidor para gerenciar. `PAY_PER_REQUEST` cobra por requisição (quase zero no projeto) e não exige dimensionar capacidade. As chaves seguem o contrato: `produto_id`, `pedido_id` e `conversa_id` + `ts`.

```bash
aws dynamodb create-table --table-name $PREFIXO-produtos --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=produto_id,AttributeType=S \
  --key-schema AttributeName=produto_id,KeyType=HASH \
  --tags $TAGS_KV --query TableDescription.TableArn --output text

aws dynamodb create-table --table-name $PREFIXO-pedidos --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=pedido_id,AttributeType=S \
  --key-schema AttributeName=pedido_id,KeyType=HASH \
  --tags $TAGS_KV --query TableDescription.TableArn --output text

aws dynamodb create-table --table-name $PREFIXO-conversas --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=conversa_id,AttributeType=S AttributeName=ts,AttributeType=S \
  --key-schema AttributeName=conversa_id,KeyType=HASH AttributeName=ts,KeyType=RANGE \
  --tags $TAGS_KV --query TableDescription.TableArn --output text

for T in produtos pedidos conversas; do aws dynamodb wait table-exists --table-name $PREFIXO-$T; done
```

Seed do catálogo: o `scripts/seed.py` lê `AWS_REGION` e `TABELA_PRODUTOS` do ambiente (as outras duas só são usadas com `--criar-tabelas`, que **não** usamos aqui porque as tabelas já existem). Ele usa as mesmas credenciais da CLI. Não pode haver `DYNAMODB_ENDPOINT_URL` no ambiente, senão ele tentaria o DynamoDB Local.

```bash
unset DYNAMODB_ENDPOINT_URL
TABELA_PRODUTOS=$PREFIXO-produtos TABELA_PEDIDOS=$PREFIXO-pedidos TABELA_CONVERSAS=$PREFIXO-conversas \
  python scripts/seed.py
```

Nenhum ID novo para gravar (nomes fixos).

Verificação: 10 produtos na tabela.

```bash
aws dynamodb scan --table-name $PREFIXO-produtos --select COUNT --query Count --output text
aws dynamodb describe-table --table-name $PREFIXO-conversas \
  --query 'Table.[TableStatus,BillingModeSummary.BillingMode,KeySchema[].AttributeName]' --output json
```

> Rodar o seed de novo "reseta" o estoque (útil antes de cada demonstração).

---

## Passo 6 — SQS: fila de pedidos + DLQ

Objetivo: desacoplar o chat do processamento do pedido. O `chat-api` só enfileira o `pedido_id`; o worker consome no seu ritmo. Parâmetros do contrato: visibility timeout 60 s (tempo para o worker processar antes de a mensagem reaparecer), long polling 20 s (menos chamadas vazias) e, após **3** recebimentos sem sucesso, a mensagem vai para a DLQ em vez de ficar em loop.

```bash
# DLQ primeiro (a fila principal aponta para ela). Retenção máxima: 14 dias para dar tempo de investigar.
DLQ_URL=$(aws sqs create-queue --queue-name $PREFIXO-pedidos-dlq \
  --attributes MessageRetentionPeriod=1209600 --tags $TAGS_MAPA \
  --query QueueUrl --output text)

# Fila principal: atributos (incluindo a RedrivePolicy, que é um JSON dentro de string) vêm do arquivo
renderizar fila-pedidos-atributos.json
FILA_URL=$(aws sqs create-queue --queue-name $PREFIXO-pedidos \
  --attributes file://infra/ohio/.render/fila-pedidos-atributos.json --tags $TAGS_MAPA \
  --query QueueUrl --output text)

{ echo "DLQ_URL=$DLQ_URL"; echo "FILA_URL=$FILA_URL"; } >> "$IDS"
```

Verificação:

```bash
aws sqs get-queue-attributes --queue-url $FILA_URL \
  --attribute-names VisibilityTimeout ReceiveMessageWaitTimeSeconds RedrivePolicy \
  --query Attributes --output json
```

---

## Passo 7 — ECR: repositórios, build e push

Objetivo: as instâncias precisam baixar as imagens de um registro **na mesma região**. Um repositório por serviço; a tag é o hash curto do commit, então cada imagem é rastreável até o código que a gerou.

```bash
for R in chat-api order-worker; do
  aws ecr create-repository --repository-name $PREFIXO/$R \
    --image-scanning-configuration scanOnPush=true --tags $TAGS_KV \
    --query repository.repositoryUri --output text
done

ECR_REGISTRY=$CONTA.dkr.ecr.$REGIAO.amazonaws.com

# Login no ECR. No Windows, "docker login" costuma falhar ao gravar o token no
# gerenciador de credenciais ("O fragmento de código recebeu dados incorretos"):
# o token do ECR é grande demais para ele. Por isso gravamos o token (válido por 12 h)
# num config.json temporário, fora do repositório. cygpath -w é necessário porque o
# MSYS_NO_PATHCONV=1 impede a conversão automática do caminho para o docker.exe.
DOCKER_CFG_DIR="$HOME/.docker-ecr-$PREFIXO"; mkdir -p "$DOCKER_CFG_DIR"
AUTH=$(printf 'AWS:%s' "$(aws ecr get-login-password)" | base64 -w0)
printf '{"auths":{"%s":{"auth":"%s"}}}' "$ECR_REGISTRY" "$AUTH" > "$DOCKER_CFG_DIR/config.json"; unset AUTH
export DOCKER_CONFIG="$(cygpath -w "$DOCKER_CFG_DIR")"
# (Em Linux/Mac basta: aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REGISTRY)

# Faça commit antes: a tag reflete o HEAD, não alterações locais não commitadas
TAG=$(git rev-parse --short HEAD)
IMAGEM_CHAT=$ECR_REGISTRY/$PREFIXO/chat-api:$TAG
IMAGEM_WORKER=$ECR_REGISTRY/$PREFIXO/order-worker:$TAG

# --platform linux/amd64: as t3.small são x86_64 (evita imagem ARM se alguém usar Mac M1/M2)
docker build --platform linux/amd64 -t $IMAGEM_CHAT app/chat-api
docker build --platform linux/amd64 -t $IMAGEM_WORKER app/order-worker
docker push $IMAGEM_CHAT
docker push $IMAGEM_WORKER

{ echo "TAG=$TAG"; echo "IMAGEM_CHAT=$IMAGEM_CHAT"; echo "IMAGEM_WORKER=$IMAGEM_WORKER"; } >> "$IDS"
```

Verificação:

```bash
for R in chat-api order-worker; do
  aws ecr describe-images --repository-name $PREFIXO/$R \
    --query 'imageDetails[].[imageTags[0],imagePushedAt,imageSizeInBytes]' --output table
done
```

---

## Passo 8 — ECS: cluster, Launch Template, ASG e Capacity Provider

Objetivo: o **primeiro nível de elasticidade** é de tasks (passo 11); este passo monta o **segundo**, o de instâncias. O ASG mantém de 2 a 4 `t3.small` nas sub-redes privadas (uma por AZ no estado base). O Capacity Provider liga o ASG ao cluster: com *managed scaling* o ECS aumenta o ASG quando uma task não cabe; *managed termination protection* impede o ASG de matar uma instância com tasks; *managed draining* drena a instância antes de ela sair.

### 8.1 Cluster com Container Insights

```bash
aws ecs create-cluster --cluster-name $PREFIXO-cluster \
  --settings name=containerInsights,value=enabled --tags $TAGS_ECS \
  --query 'cluster.[clusterName,status]' --output text
```

> Se der erro de *service-linked role* (conta que nunca usou ECS): `aws iam create-service-linked-role --aws-service-name ecs.amazonaws.com` e repita.

### 8.2 Launch Template

AMI ECS-optimized (Amazon Linux 2023) lida do parâmetro público do SSM, sempre a recomendada para a região. IMDSv2 obrigatório; `HttpPutResponseHopLimit = 1` impede que os containers (rede `bridge`, um "salto" a mais) alcancem os metadados e herdem a role da instância: eles usam só a task role. O user data registra a instância no cluster certo.

```bash
# O nome começa com "/": depende do MSYS_NO_PATHCONV=1 do passo 0
AMI_ID=$(aws ssm get-parameter \
  --name /aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id \
  --query Parameter.Value --output text)
echo "AMI: $AMI_ID"

# User data em base64 numa linha só. -w0 é essencial: sem ele o base64 quebra a cada 76
# caracteres e o JSON fica inválido. O tr remove \r caso o arquivo tenha sido salvo com CRLF.
renderizar user-data.sh
USER_DATA_B64=$(tr -d '\r' < infra/ohio/.render/user-data.sh | base64 -w0)

renderizar launch-template.json
LT_ID=$(aws ec2 create-launch-template --launch-template-name $PREFIXO-ecs-lt \
  --version-description "ECS AL2023 t3.small" \
  --launch-template-data file://infra/ohio/.render/launch-template.json \
  --tag-specifications "ResourceType=launch-template,Tags=[$TAGS_EC2]" \
  --query LaunchTemplate.LaunchTemplateId --output text)
```

### 8.3 Auto Scaling Group

`--new-instances-protected-from-scale-in` é pré-requisito do managed termination protection. Health check `EC2`: o ASG troca instâncias com falha de hardware/SO; a saúde da aplicação é cuidada pelo ECS e pelo ALB.

```bash
# \$Latest: o ASG usa sempre a versão mais nova do Launch Template
aws autoscaling create-auto-scaling-group --auto-scaling-group-name $PREFIXO-asg \
  --launch-template "LaunchTemplateId=$LT_ID,Version=\$Latest" \
  --min-size 2 --desired-capacity 2 --max-size 4 \
  --vpc-zone-identifier "$SUBNET_PRIV1,$SUBNET_PRIV2" \
  --health-check-type EC2 \
  --new-instances-protected-from-scale-in \
  --tags "ResourceId=$PREFIXO-asg,ResourceType=auto-scaling-group,Key=Projeto,Value=$PREFIXO,PropagateAtLaunch=false" \
         "ResourceId=$PREFIXO-asg,ResourceType=auto-scaling-group,Key=Etapa,Value=manual,PropagateAtLaunch=false"

# Métricas do grupo (GroupInServiceInstances etc.) no CloudWatch, usadas por um alarme no passo 12
aws autoscaling enable-metrics-collection --auto-scaling-group-name $PREFIXO-asg --granularity 1Minute

ASG_ARN=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $PREFIXO-asg \
  --query 'AutoScalingGroups[0].AutoScalingGroupARN' --output text)
```

### 8.4 Capacity Provider e associação ao cluster

```bash
renderizar capacity-provider.json
aws ecs create-capacity-provider --name $PREFIXO-cp \
  --auto-scaling-group-provider file://infra/ohio/.render/capacity-provider.json \
  --tags $TAGS_ECS --query 'capacityProvider.[name,status]' --output text

# Estratégia padrão do cluster: tudo vai para o cafe-cp
aws ecs put-cluster-capacity-providers --cluster $PREFIXO-cluster \
  --capacity-providers $PREFIXO-cp \
  --default-capacity-provider-strategy capacityProvider=$PREFIXO-cp,weight=1,base=0 \
  --query 'cluster.[capacityProviders,defaultCapacityProviderStrategy]' --output json

{ echo "AMI_ID=$AMI_ID"; echo "LT_ID=$LT_ID"; echo "ASG_ARN=$ASG_ARN"; } >> "$IDS"
```

> O ECS cria sozinho, no ASG, uma política de escala `ECSManagedAutoScalingPolicy-...` (com alarmes `TargetTracking-...`) e um lifecycle hook para o draining. Não mexa neles; somem quando o Capacity Provider é apagado.

Verificação (após ~3 minutos): 2 instâncias `InService` em AZs diferentes, registradas no cluster e online no SSM.

```bash
# A CLI não tem "wait" para Auto Scaling: espera as 2 instâncias se registrarem no cluster
for i in $(seq 1 30); do
  N=$(aws ecs describe-clusters --clusters $PREFIXO-cluster \
    --query 'clusters[0].registeredContainerInstancesCount' --output text)
  [ "$N" -ge 2 ] && break; sleep 10
done; echo "Instâncias no cluster: $N"
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $PREFIXO-asg \
  --query 'AutoScalingGroups[0].Instances[].[InstanceId,AvailabilityZone,LifecycleState,ProtectedFromScaleIn]' --output table
CIS=$(aws ecs list-container-instances --cluster $PREFIXO-cluster --query 'containerInstanceArns' --output text)
aws ecs describe-container-instances --cluster $PREFIXO-cluster --container-instances $CIS \
  --query 'containerInstances[].[ec2InstanceId,status,agentConnected,registeredResources[?name==`MEMORY`].integerValue|[0]]' --output table
aws ssm describe-instance-information --query 'InstanceInformationList[].[InstanceId,PingStatus]' --output table
aws ecs describe-capacity-providers --capacity-providers $PREFIXO-cp \
  --query 'capacityProviders[0].[status,autoScalingGroupProvider.managedScaling.status,autoScalingGroupProvider.managedTerminationProtection,autoScalingGroupProvider.managedDraining]' --output text
```

Acesso a uma instância sem SSH (requer o *Session Manager plugin* instalado no Windows): `command aws ssm start-session --target <instance-id>`.

---

## Passo 9 — ALB, target group e listener

Objetivo: um ponto de entrada público e estável que distribui as requisições entre as tasks do `chat-api` nas duas AZs e tira de circulação as que falham no `/health`. Target group do tipo `instance`: o ECS registra cada task como *instância + porta dinâmica*. Deregistration delay de 30 s: ao parar uma task, o ALB espera as requisições em andamento terminarem, mas sem segurar o deploy por 5 minutos (o padrão).

```bash
ALB_ARN=$(aws elbv2 create-load-balancer --name $PREFIXO-alb --type application --scheme internet-facing \
  --subnets $SUBNET_PUB1 $SUBNET_PUB2 --security-groups $SG_ALB --tags $TAGS_KV \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)

# A porta 80 aqui é só obrigatória; o ECS registra cada task com a porta dinâmica dela.
# "/health" começa com "/": depende do MSYS_NO_PATHCONV=1 do passo 0.
TG_ARN=$(aws elbv2 create-target-group --name $PREFIXO-chat-api-tg \
  --protocol HTTP --port 80 --vpc-id $VPC_ID --target-type instance \
  --health-check-protocol HTTP --health-check-path /health --matcher HttpCode=200 \
  --health-check-interval-seconds 15 --healthy-threshold-count 2 --unhealthy-threshold-count 3 \
  --tags $TAGS_KV --query 'TargetGroups[0].TargetGroupArn' --output text)
aws elbv2 modify-target-group-attributes --target-group-arn $TG_ARN \
  --attributes Key=deregistration_delay.timeout_seconds,Value=30

aws elbv2 wait load-balancer-available --load-balancer-arns $ALB_ARN   # 2 a 4 minutos
LISTENER_ARN=$(aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN \
  --query 'Listeners[0].ListenerArn' --output text)

ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)

{ echo "ALB_ARN=$ALB_ARN"; echo "TG_ARN=$TG_ARN"; echo "LISTENER_ARN=$LISTENER_ARN"; echo "ALB_DNS=$ALB_DNS"; } >> "$IDS"
```

Verificação: ALB `active`; ainda sem alvos (eles aparecem no passo 10). Por enquanto, `curl` deve receber **503** do próprio ALB.

```bash
aws elbv2 describe-load-balancers --load-balancer-arns $ALB_ARN --query 'LoadBalancers[0].State.Code' --output text
curl -s -o /dev/null -w "%{http_code}\n" http://$ALB_DNS/health
```

> O ALB encerra conexões ociosas após 60 s (padrão), acima do tempo máximo do LLM (timeout de 20 s + 1 retentativa).

---

## Passo 10 — Log groups, task definitions e os 2 serviços

Objetivo: descrever **como** cada container roda (imagem, CPU/memória, variáveis, segredo, logs) e manter o número desejado de tasks vivas. Os log groups são criados primeiro porque o driver `awslogs` não sobe a task sem eles (a role de execução não tem permissão para criá-los, de propósito).

### 10.1 Log groups (retenção de 7 dias)

```bash
for S in chat-api order-worker; do
  # O nome começa com "/": depende do MSYS_NO_PATHCONV=1 do passo 0
  aws logs create-log-group --log-group-name /ecs/$PREFIXO/$S --tags $TAGS_MAPA
  aws logs put-retention-policy --log-group-name /ecs/$PREFIXO/$S --retention-in-days 7
done
```

### 10.2 Task definitions

Rede `bridge` com `hostPort 0` (porta dinâmica: várias tasks do chat na mesma instância). CPU e memória conforme a [conta de capacidade](arquitetura.md#5-ecs-sobre-ec2-e-capacidade): `memoryReservation` é o que o ECS reserva para posicionar a task; `memory` é o limite rígido (o container é encerrado se passar). Variáveis do contrato, sem os endpoints locais. `LLM_API_KEY` vem do Secrets Manager pelo campo `secrets`.

```bash
LLM_MODO=real                                          # troque para fake em testes de carga e no smoke test
LLM_BASE_URL="https://api.exemplo-de-provedor.com/v1"  # mesmo valor do seu .env
MODEL_ID="nome-do-modelo"                              # mesmo valor do seu .env
{ echo "LLM_MODO=$LLM_MODO"; echo "LLM_BASE_URL=$LLM_BASE_URL"; echo "MODEL_ID=$MODEL_ID"; } >> "$IDS"

renderizar taskdef-chat-api.json
renderizar taskdef-order-worker.json
aws ecs register-task-definition --cli-input-json file://infra/ohio/.render/taskdef-chat-api.json \
  --query 'taskDefinition.[family,revision]' --output text
aws ecs register-task-definition --cli-input-json file://infra/ohio/.render/taskdef-order-worker.json \
  --query 'taskDefinition.[family,revision]' --output text
```

O worker tem `healthCheck` próprio (`python healthcheck.py`, o mesmo do Dockerfile): falha se o loop de consumo não gravar o heartbeat há mais de 60 s, e o ECS substitui a task. `startPeriod` de 30 s dá tempo de o processo subir.

### 10.3 Serviços

Os dois usam o Capacity Provider; posicionamento `spread` por AZ (as 2 tasks do chat ficam em AZs diferentes) e depois `binpack` por memória (concentra o resto e facilita liberar instâncias no scale-in). Deploy com 100%/200%: as tasks novas sobem antes das antigas saírem; o *circuit breaker* desfaz sozinho um deploy que não estabiliza. O `chat-api` tem 60 s de carência antes de o health check do ALB contar.

```bash
renderizar servico-chat-api.json
renderizar servico-order-worker.json
aws ecs create-service --cli-input-json file://infra/ohio/.render/servico-chat-api.json \
  --query 'service.[serviceName,status]' --output text
aws ecs create-service --cli-input-json file://infra/ohio/.render/servico-order-worker.json \
  --query 'service.[serviceName,status]' --output text

aws ecs wait services-stable --cluster $PREFIXO-cluster --services $PREFIXO-chat-api $PREFIXO-order-worker
```

Verificação: 2 + 1 tasks `RUNNING`, as do chat em AZs diferentes, worker `HEALTHY` e 2 alvos `healthy` no target group.

```bash
aws ecs describe-services --cluster $PREFIXO-cluster --services $PREFIXO-chat-api $PREFIXO-order-worker \
  --query 'services[].[serviceName,desiredCount,runningCount,deployments[0].rolloutState]' --output table
TASKS=$(aws ecs list-tasks --cluster $PREFIXO-cluster --query 'taskArns' --output text)
aws ecs describe-tasks --cluster $PREFIXO-cluster --tasks $TASKS \
  --query 'tasks[].[group,lastStatus,healthStatus,availabilityZone]' --output table
aws elbv2 describe-target-health --target-group-arn $TG_ARN \
  --query 'TargetHealthDescriptions[].[Target.Id,Target.Port,TargetHealth.State]' --output table
```

Se uma task não subir, o motivo aparece nos eventos do serviço e nas tasks paradas:

```bash
aws ecs describe-services --cluster $PREFIXO-cluster --services $PREFIXO-chat-api \
  --query 'services[0].events[0:5].message' --output text
STOP=$(aws ecs list-tasks --cluster $PREFIXO-cluster --desired-status STOPPED --query 'taskArns' --output text)
[ -n "$STOP" ] && aws ecs describe-tasks --cluster $PREFIXO-cluster --tasks $STOP \
  --query 'tasks[].[group,stoppedReason,containers[0].reason]' --output text
aws logs tail /ecs/$PREFIXO/chat-api --since 10m
```

---

## Passo 11 — Auto scaling das tasks

Objetivo: o **primeiro nível de elasticidade**. O Application Auto Scaling ajusta o `desiredCount` de cada serviço. Se as tasks novas não couberem nas instâncias, ficam em `PROVISIONING` e o Capacity Provider do passo 8 sobe mais EC2.

- **chat-api** (2 a 8 tasks): target tracking em CPU média de 60% (medida em relação às 256 unidades reservadas por task). O máximo de 8 foi escolhido de propósito: 8 × 384 MiB + 4 × 192 MiB = 3840 MiB, mais do que as 2 instâncias oferecem (~3826 MiB), então a carga máxima obriga o Capacity Provider a subir a 3ª EC2.
- **chat-api, segunda política**: target tracking em **requisições por task no ALB** (`ALBRequestCountPerTarget`, alvo 600 por minuto). Com duas políticas, o serviço escala para cima quando *qualquer uma* pede e só reduz quando *as duas* permitem. A CPU cobre conversas pesadas (chamadas à IA); as requisições cobrem picos de tráfego leve, que sobem a CPU devagar.
- **order-worker** (1 a 4 tasks): target tracking em **mensagens visíveis na fila por task** (alvo 20, scale-out com cooldown de 30 s), com uma métrica calculada (`visiveis / tasks`) que junta `ApproximateNumberOfMessagesVisible` do SQS e `RunningTaskCount` do Container Insights. CPU não serve para o worker: ele passa quase todo o tempo esperando o long polling e a CPU fica baixa mesmo com fila cheia.

```bash
# chat-api: 2 a 8 tasks, CPU 60%
aws application-autoscaling register-scalable-target --service-namespace ecs   --scalable-dimension ecs:service:DesiredCount   --resource-id service/$PREFIXO-cluster/$PREFIXO-chat-api --min-capacity 2 --max-capacity 8
aws application-autoscaling put-scaling-policy --service-namespace ecs   --scalable-dimension ecs:service:DesiredCount   --resource-id service/$PREFIXO-cluster/$PREFIXO-chat-api   --policy-name $PREFIXO-chat-api-cpu60 --policy-type TargetTrackingScaling   --target-tracking-scaling-policy-configuration file://infra/ohio/escala-cpu-60.json   --query PolicyARN --output text

# chat-api: 600 requisições por task por minuto no ALB.
# O rótulo é "app/<alb>/<id>/targetgroup/<tg>/<id>" (o final dos dois ARNs).
ROTULO_ALB_TG="${ALB_ARN#*:loadbalancer/}/${TG_ARN##*:}"
sed "s#__ROTULO_ALB_TG__#$ROTULO_ALB_TG#" infra/ohio/escala-chat-requisicoes.json > infra/ohio/.render/escala-chat-requisicoes.json
aws application-autoscaling put-scaling-policy --service-namespace ecs   --scalable-dimension ecs:service:DesiredCount   --resource-id service/$PREFIXO-cluster/$PREFIXO-chat-api   --policy-name $PREFIXO-chat-api-requisicoes --policy-type TargetTrackingScaling   --target-tracking-scaling-policy-configuration file://infra/ohio/.render/escala-chat-requisicoes.json   --query PolicyARN --output text

# order-worker: 1 a 4 tasks, 20 mensagens na fila por task
renderizar escala-worker-fila.json
aws application-autoscaling register-scalable-target --service-namespace ecs   --scalable-dimension ecs:service:DesiredCount   --resource-id service/$PREFIXO-cluster/$PREFIXO-order-worker --min-capacity 1 --max-capacity 4
aws application-autoscaling put-scaling-policy --service-namespace ecs   --scalable-dimension ecs:service:DesiredCount   --resource-id service/$PREFIXO-cluster/$PREFIXO-order-worker   --policy-name $PREFIXO-order-worker-fila --policy-type TargetTrackingScaling   --target-tracking-scaling-policy-configuration file://infra/ohio/.render/escala-worker-fila.json   --query PolicyARN --output text
```

As métricas do SQS chegam ao CloudWatch com 1 a 5 minutos de atraso, então o worker reage à fila com esse atraso (no ensaio, 1 task drenou 6000 mensagens em ~3 min, e as tasks extras subiram quando a fila já estava quase vazia). Por isso o alvo caiu de 100 (versão C) para 20 e o cooldown de scale-out de 60 s para 30 s: com o mesmo atraso de métrica, cada leitura pede mais tasks e a reação vem mais cedo. Para a demonstração, mostre o histórico de atividades.

Nenhum ID novo para gravar (identificados pelo `resource-id`). A política cria sozinha dois alarmes `TargetTracking-service/...` (alta e baixa); não os apague.

Verificação:

```bash
aws application-autoscaling describe-scalable-targets --service-namespace ecs \
  --query 'ScalableTargets[].[ResourceId,MinCapacity,MaxCapacity]' --output table
aws application-autoscaling describe-scaling-policies --service-namespace ecs \
  --query 'ScalingPolicies[].[PolicyName,TargetTrackingScalingPolicyConfiguration.TargetValue]' --output table
```

---

## Passo 12 — Observabilidade: SNS e alarmes

Objetivo: saber que algo quebrou **antes** do cliente avisar. Os log groups (passo 10) e o Container Insights (passo 8) já estão ligados; aqui criamos o tópico de notificação e um alarme por item exigido.

### 12.1 Tópico SNS com e-mail

```bash
TOPICO_ARN=$(aws sns create-topic --name $PREFIXO-alertas --tags $TAGS_KV --query TopicArn --output text)
echo "TOPICO_ARN=$TOPICO_ARN" >> "$IDS"

EMAIL_ALERTAS="<SEU_EMAIL>"   # troque pelo e-mail do grupo; NÃO grave no repositório
aws sns subscribe --topic-arn $TOPICO_ARN --protocol email --notification-endpoint "$EMAIL_ALERTAS"
```

Abra o e-mail "AWS Notification - Subscription Confirmation" e clique em **Confirm subscription**.

### 12.2 Alarmes

Dimensões do ALB e do target group no CloudWatch são o final dos ARNs:

```bash
ALB_DIM=${ALB_ARN##*:loadbalancer/}   # app/cafe-alb/<id>
TG_DIM=${TG_ARN##*:}                  # targetgroup/cafe-chat-api-tg/<id>
COMUM="--alarm-actions $TOPICO_ARN --tags $TAGS_KV"
```

**Tasks abaixo do desejado** (um por serviço). Métrica calculada `DesiredTaskCount - RunningTaskCount` do Container Insights; dispara se faltar task por 3 minutos seguidos (um scale-out normal resolve antes disso, a menos que precise de EC2 nova).

```bash
for S in chat-api order-worker; do
  SERVICO=$PREFIXO-$S renderizar alarme-tasks-abaixo.json alarme-tasks-$S.json
  aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-$S-tasks-abaixo \
    --alarm-description "Servico $S com menos tasks rodando que o desejado" \
    --metrics file://infra/ohio/.render/alarme-tasks-$S.json \
    --comparison-operator GreaterThanThreshold --threshold 0 \
    --evaluation-periods 3 --datapoints-to-alarm 3 --treat-missing-data notBreaching $COMUM
done
```

**Reserva de CPU e de memória do cluster > 85%**: o cluster está quase sem espaço para novas tasks (se o ASG já estiver no máximo, o scale-out para).

```bash
for M in CPUReservation MemoryReservation; do
  aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-cluster-$M-alta \
    --alarm-description "$M do cluster acima de 85%" \
    --namespace AWS/ECS --metric-name $M --dimensions Name=ClusterName,Value=$PREFIXO-cluster \
    --statistic Maximum --period 60 --evaluation-periods 5 \
    --comparison-operator GreaterThanThreshold --threshold 85 --treat-missing-data notBreaching $COMUM
done
```

**Instâncias em serviço < 2** (mínimo do ASG; depende do `enable-metrics-collection` do passo 8):

```bash
aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-asg-instancias-abaixo \
  --alarm-description "Menos de 2 instancias InService no ASG" \
  --namespace AWS/AutoScaling --metric-name GroupInServiceInstances \
  --dimensions Name=AutoScalingGroupName,Value=$PREFIXO-asg \
  --statistic Minimum --period 60 --evaluation-periods 2 \
  --comparison-operator LessThanThreshold --threshold 2 --treat-missing-data notBreaching $COMUM
```

**ALB: erros 5XX das tasks e alvos não saudáveis**:

```bash
aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-alb-5xx \
  --alarm-description "5 ou mais respostas 5XX das tasks em 1 minuto" \
  --namespace AWS/ApplicationELB --metric-name HTTPCode_Target_5XX_Count \
  --dimensions Name=LoadBalancer,Value=$ALB_DIM \
  --statistic Sum --period 60 --evaluation-periods 1 \
  --comparison-operator GreaterThanOrEqualToThreshold --threshold 5 --treat-missing-data notBreaching $COMUM

aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-tg-hosts-nao-saudaveis \
  --alarm-description "Algum alvo do chat-api falhando no /health" \
  --namespace AWS/ApplicationELB --metric-name UnHealthyHostCount \
  --dimensions Name=TargetGroup,Value=$TG_DIM Name=LoadBalancer,Value=$ALB_DIM \
  --statistic Maximum --period 60 --evaluation-periods 2 \
  --comparison-operator GreaterThanThreshold --threshold 0 --treat-missing-data notBreaching $COMUM
```

**Fila: mensagem mais antiga > 5 min** (worker parado ou lento) e **DLQ com mensagens**:

```bash
aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-fila-mensagem-antiga \
  --alarm-description "Pedido esperando ha mais de 5 minutos na fila" \
  --namespace AWS/SQS --metric-name ApproximateAgeOfOldestMessage \
  --dimensions Name=QueueName,Value=$PREFIXO-pedidos \
  --statistic Maximum --period 60 --evaluation-periods 1 \
  --comparison-operator GreaterThanThreshold --threshold 300 --treat-missing-data notBreaching $COMUM

aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-dlq-com-mensagens \
  --alarm-description "Mensagem caiu na DLQ de pedidos" \
  --namespace AWS/SQS --metric-name ApproximateNumberOfMessagesVisible \
  --dimensions Name=QueueName,Value=$PREFIXO-pedidos-dlq \
  --statistic Maximum --period 60 --evaluation-periods 1 \
  --comparison-operator GreaterThanThreshold --threshold 0 --treat-missing-data notBreaching $COMUM
```

**Erros nos logs da aplicação**: um *metric filter* em cada log group conta as linhas com `ERROR` (o nível vem no formato de log dos dois serviços) numa métrica própria `Cafe/ErrosNoLog`; um alarme olha a soma.

```bash
for S in chat-api order-worker; do
  aws logs put-metric-filter --log-group-name /ecs/$PREFIXO/$S --filter-name $PREFIXO-$S-erros \
    --filter-pattern 'ERROR' \
    --metric-transformations metricName=ErrosNoLog,metricNamespace=Cafe,metricValue=1,defaultValue=0
done

aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-erros-no-log \
  --alarm-description "Linha com ERROR nos logs do chat-api ou do order-worker" \
  --namespace Cafe --metric-name ErrosNoLog \
  --statistic Sum --period 60 --evaluation-periods 1 \
  --comparison-operator GreaterThanThreshold --threshold 0 --treat-missing-data notBreaching $COMUM
```

Verificação: 10 alarmes `cafe-*` (podem começar em `INSUFFICIENT_DATA` por alguns minutos), assinatura confirmada e Container Insights ligado.

```bash
aws cloudwatch describe-alarms --alarm-name-prefix $PREFIXO- \
  --query 'MetricAlarms[].[AlarmName,StateValue]' --output table
aws sns list-subscriptions-by-topic --topic-arn $TOPICO_ARN \
  --query 'Subscriptions[].SubscriptionArn' --output text    # "PendingConfirmation" = falta clicar no e-mail
aws ecs describe-clusters --clusters $PREFIXO-cluster --include SETTINGS \
  --query 'clusters[0].settings' --output text

# Teste do caminho alarme -> SNS -> e-mail, sem quebrar nada:
aws cloudwatch set-alarm-state --alarm-name $PREFIXO-dlq-com-mensagens \
  --state-value ALARM --state-reason "Teste manual da notificacao"
```

### Upgrade para B: limiares calibrados e imagens novas

Os limiares acima são os da versão C. Depois dos testes de carga ([evidencias.md](evidencias.md)), os alarmes foram recalibrados com os mesmos valores do Terraform (justificativa por alarme em [terraform.md](terraform.md#alarmes)):

| Alarme | Versão C | Versão B |
|---|---|---|
| `*-tasks-abaixo` | 3 min | 5 min (o scale-in e a reposição de task levam até ~3 min) |
| `asg-instancias-abaixo` | 2 min | 3 min |
| `tg-hosts-nao-saudaveis` | 2 min | 3 min |
| `alb-5xx` | ≥ 5 respostas 5XX em 1 min | > 1% das respostas por 2 min, só com ≥ 20 requisições/min (métrica calculada) |
| `fila-mensagem-antiga` | > 300 s | > 600 s por 2 min |
| Filtro `erros` do log | `ERROR` | `?ERROR ?CRITICAL` (casa as linhas JSON com `"nivel": "ERROR"`) |

Para alterar um alarme existente, basta repetir o `put-metric-alarm` com o mesmo nome e os valores novos (ele sobrescreve). Exemplo do `alb-5xx`:

```bash
LB=${ALB_ARN#*:loadbalancer/}
M() { echo "{\"Id\":\"$1\",\"ReturnData\":false,\"MetricStat\":{\"Metric\":{\"Namespace\":\"AWS/ApplicationELB\",\"MetricName\":\"$2\",\"Dimensions\":[{\"Name\":\"LoadBalancer\",\"Value\":\"$LB\"}]},\"Period\":60,\"Stat\":\"Sum\"}}"; }
aws cloudwatch put-metric-alarm --alarm-name $PREFIXO-alb-5xx \
  --alarm-description "Mais de 1% das respostas do ALB com 5XX por 2 min" \
  --comparison-operator GreaterThanThreshold --threshold 1 --evaluation-periods 2 --datapoints-to-alarm 2 \
  --treat-missing-data notBreaching --alarm-actions $TOPICO_ARN \
  --metrics "[$(M requisicoes RequestCount),$(M erros_task HTTPCode_Target_5XX_Count),$(M erros_alb HTTPCode_ELB_5XX_Count),
    {\"Id\":\"total\",\"Expression\":\"FILL(requisicoes, 0) + FILL(erros_alb, 0)\",\"ReturnData\":false},
    {\"Id\":\"taxa_5xx\",\"Expression\":\"IF(total >= 20, 100 * (FILL(erros_task, 0) + FILL(erros_alb, 0)) / total, 0)\",\"Label\":\"Respostas 5XX (%)\",\"ReturnData\":true}]"
aws logs put-metric-filter --log-group-name /ecs/$PREFIXO/order-worker --filter-name $PREFIXO-order-worker-erros \
  --filter-pattern '?ERROR ?CRITICAL' \
  --metric-transformations metricName=ErrosNoLog,metricNamespace=Cafe,metricValue=1,defaultValue=0
```

Imagens da versão B (tools `consultar_estoque`/`consultar_pedido` e logs JSON): repita o build e push do passo 7 com o novo `TAG`, registre uma revisão nova de cada task definition trocando só o `image` e rode `aws ecs update-service --task-definition <família>:<revisão nova>`. O ECS faz o rolling update sem derrubar o ALB.

---

## Teste final

```bash
echo "Aplicação: http://$ALB_DNS   |   Swagger: http://$ALB_DNS/docs"
curl -s http://$ALB_DNS/health; echo          # {"status":"ok"}
curl -s http://$ALB_DNS/produtos | head -c 300; echo
```

O `scripts/smoke-test.sh` aceita a URL base pela variável `API_URL`. Ele foi escrito para o **LLM em modo `fake`** (as frases de compra são fixas), então troque o modo do `chat-api` antes e volte depois:

```bash
# 1) chat-api em modo fake (nova revisão da task definition + deploy)
LLM_MODO=fake renderizar taskdef-chat-api.json
aws ecs register-task-definition --cli-input-json file://infra/ohio/.render/taskdef-chat-api.json \
  --query 'taskDefinition.revision' --output text
aws ecs update-service --cluster $PREFIXO-cluster --service $PREFIXO-chat-api \
  --task-definition $PREFIXO-chat-api --query 'service.taskDefinition' --output text
aws ecs wait services-stable --cluster $PREFIXO-cluster --services $PREFIXO-chat-api

# 2) smoke test contra o ALB: health, catálogo, pedido CONFIRMADO e pedido REJEITADO
API_URL=http://$ALB_DNS bash scripts/smoke-test.sh

# 3) de volta ao modo real (LLM_MODO=real veio do .ids.env)
renderizar taskdef-chat-api.json
aws ecs register-task-definition --cli-input-json file://infra/ohio/.render/taskdef-chat-api.json \
  --query 'taskDefinition.revision' --output text
aws ecs update-service --cluster $PREFIXO-cluster --service $PREFIXO-chat-api \
  --task-definition $PREFIXO-chat-api --query 'service.taskDefinition' --output text
```

Com o LLM real, teste a jornada pelo Swagger (`/docs` → `POST /chat`). Para conferir o pedido no banco:

```bash
aws dynamodb scan --table-name $PREFIXO-pedidos \
  --query 'Items[].[pedido_id.S,status.S,total_centavos.N]' --output table
```

O smoke test baixa o estoque; rode o seed (passo 5) para resetar.

---

## Demonstrações

Comandos de apoio ao roteiro da [Fase 3](planejamento.md#fase-3--roteiro-de-demonstração-usado-nas-duas-etapas). Acompanhe pelo console (ECS → cluster → Tasks / Infrastructure) ou com os `describe` abaixo.

```bash
# Estado rápido: tasks por serviço e instâncias do ASG
aws ecs describe-services --cluster $PREFIXO-cluster --services $PREFIXO-chat-api $PREFIXO-order-worker \
  --query 'services[].[serviceName,desiredCount,runningCount,pendingCount]' --output table
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $PREFIXO-asg \
  --query 'AutoScalingGroups[0].[DesiredCapacity,length(Instances)]' --output text
```

**Escala automática do chat-api e das EC2** (`scripts/carga.py`, só biblioteca padrão; bate em `GET /produtos`, que não chama o LLM). Duas cargas em paralelo (60 + 150 conexões, 10 min) levaram, no ensaio, o chat de 2 → 8 tasks; a 7ª ficou `PROVISIONING` e o ASG subiu de 2 → 3 instâncias. Sem carga, tudo volta ao base em ~15 min (scale-in das tasks, managed draining e término da EC2 extra).

```bash
ALB=http://$(aws elbv2 describe-load-balancers --names $PREFIXO-alb --query 'LoadBalancers[0].DNSName' --output text)
python scripts/carga.py $ALB --duracao 600 --concorrencia 60 &
python scripts/carga.py $ALB --duracao 600 --concorrencia 150
```

**Escala do order-worker pela fila** (`scripts/enfileirar-pedidos.py`, precisa de `boto3`): grava N pedidos `PENDENTE` e publica todos na fila, sem passar pelo LLM. Depois da demo, rode o seed de novo para restaurar o estoque.

```bash
TABELA_PEDIDOS=$PREFIXO-pedidos TABELA_PRODUTOS=$PREFIXO-produtos FILA_PEDIDOS_URL=$FILA_URL   python scripts/enfileirar-pedidos.py 6000
aws application-autoscaling describe-scaling-activities --service-namespace ecs   --resource-id service/$PREFIXO-cluster/$PREFIXO-order-worker --max-items 4   --query 'ScalingActivities[].[StartTime,StatusCode,Description]' --output table
```

**Escalar tasks manualmente** (alternativa rápida à carga; se não couber, tasks em `PROVISIONING` e o Capacity Provider sobe EC2). O auto scaling traz o número de volta ao mínimo depois de alguns minutos sem carga.

```bash
aws ecs update-service --cluster $PREFIXO-cluster --service $PREFIXO-chat-api --desired-count 8 --query 'service.desiredCount'
aws ecs update-service --cluster $PREFIXO-cluster --service $PREFIXO-order-worker --desired-count 4 --query 'service.desiredCount'
aws autoscaling describe-scaling-activities --auto-scaling-group-name $PREFIXO-asg --max-items 3 \
  --query 'Activities[].[StartTime,StatusCode,Description]' --output table
```

**Task defeituosa** (`stop-task`): o serviço repõe a task; o ALB continua respondendo pela outra.

```bash
TASK=$(aws ecs list-tasks --cluster $PREFIXO-cluster --service-name $PREFIXO-chat-api --query 'taskArns[0]' --output text)
aws ecs stop-task --cluster $PREFIXO-cluster --task $TASK --reason "Demo: task defeituosa" --query 'task.lastStatus'
aws ecs describe-services --cluster $PREFIXO-cluster --services $PREFIXO-chat-api --query 'services[0].events[0:4].message' --output text
```

**Instância perdida**: terminar uma EC2 direto (a proteção de scale-in não impede isso). O ASG repõe, o ECS recoloca as tasks, os dados no DynamoDB ficam intactos e o alarme `cafe-asg-instancias-abaixo` dispara.

```bash
INST=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $PREFIXO-asg \
  --query 'AutoScalingGroups[0].Instances[0].InstanceId' --output text)
aws ec2 terminate-instances --instance-ids $INST --query 'TerminatingInstances[0].CurrentState.Name' --output text
```

**Drenagem**: acontece sozinha no scale-in (managed draining). Para mostrar sob comando, coloque uma instância em `DRAINING` e veja as tasks migrarem:

```bash
CI=$(aws ecs list-container-instances --cluster $PREFIXO-cluster --query 'containerInstanceArns[0]' --output text)
aws ecs update-container-instances-state --cluster $PREFIXO-cluster --container-instances $CI --status DRAINING \
  --query 'containerInstances[0].status' --output text
CIS=$(aws ecs list-container-instances --cluster $PREFIXO-cluster --query 'containerInstanceArns' --output text)
aws ecs describe-container-instances --cluster $PREFIXO-cluster --container-instances $CIS \
  --query 'containerInstances[].[ec2InstanceId,status,runningTasksCount,pendingTasksCount]' --output table
# Para devolver a instância ao serviço:
aws ecs update-container-instances-state --cluster $PREFIXO-cluster --container-instances $CI --status ACTIVE \
  --query 'containerInstances[0].status' --output text
```

**DLQ** (o `scripts/enviar-mensagem-invalida.sh` é só para o ambiente local; na AWS use a CLI): em 3 a 4 minutos a mensagem chega à DLQ e disparam `cafe-dlq-com-mensagens` e `cafe-erros-no-log`.

```bash
aws sqs send-message --queue-url $FILA_URL --message-body 'isto nao e um pedido valido {' --query MessageId --output text
aws sqs get-queue-attributes --queue-url $DLQ_URL --attribute-names ApproximateNumberOfMessages \
  --query Attributes.ApproximateNumberOfMessages --output text
```

---

## Desligar para economizar

O ambiente só precisa estar no ar para testes e para a validação com o professor.

### (a) Pausa barata (volta em ~5 minutos)

Zera tasks e instâncias, mas mantém todo o resto. **Continuam cobrando**: o **NAT Gateway** (por hora, o item mais caro), o **ALB** (por hora) e os **IPv4 públicos** (o EIP do NAT e os IPs do ALB). Somados, ficam na casa de US$ 1,50–2,00 por dia; confira na calculadora da AWS. DynamoDB on-demand, SQS, ECR, segredo, logs e alarmes custam centavos. Para pausas longas, prefira a desmontagem completa.

```bash
# Silencia os alarmes (senão "instancias abaixo" e "tasks abaixo" mandam e-mail)
ALARMES=$(aws cloudwatch describe-alarms --alarm-name-prefix $PREFIXO- --query 'MetricAlarms[].AlarmName' --output text)
aws cloudwatch disable-alarm-actions --alarm-names $ALARMES

# Tasks a zero (o mínimo do auto scaling também, senão ele traz as tasks de volta)
for S in chat-api:8 order-worker:4; do
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount --resource-id service/$PREFIXO-cluster/$PREFIXO-${S%%:*} \
    --min-capacity 0 --max-capacity ${S##*:}
  aws ecs update-service --cluster $PREFIXO-cluster --service $PREFIXO-${S%%:*} --desired-count 0 --query 'service.desiredCount'
done
aws ecs wait services-stable --cluster $PREFIXO-cluster --services $PREFIXO-chat-api $PREFIXO-order-worker

# Instâncias a zero. Sem tasks, o ECS tira a proteção de scale-in e o ASG termina as EC2.
aws autoscaling update-auto-scaling-group --auto-scaling-group-name $PREFIXO-asg --min-size 0 --desired-capacity 0
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names $PREFIXO-asg \
  --query 'AutoScalingGroups[0].Instances[].[InstanceId,LifecycleState,ProtectedFromScaleIn]' --output table
```

Se depois de alguns minutos alguma instância continuar `InService` com `ProtectedFromScaleIn = True`, remova a proteção:

```bash
aws autoscaling set-instance-protection --auto-scaling-group-name $PREFIXO-asg \
  --no-protected-from-scale-in --instance-ids <id1> <id2>
```

Para religar:

```bash
aws autoscaling update-auto-scaling-group --auto-scaling-group-name $PREFIXO-asg --min-size 2 --desired-capacity 2
# Espera as 2 instâncias se registrarem no cluster (a CLI não tem "wait" para Auto Scaling)
for i in $(seq 1 30); do
  N=$(aws ecs describe-clusters --clusters $PREFIXO-cluster \
    --query 'clusters[0].registeredContainerInstancesCount' --output text)
  [ "$N" -ge 2 ] && break; sleep 10
done; echo "Instâncias no cluster: $N"
for S in chat-api:2:8 order-worker:1:4; do
  IFS=: read NOME MIN MAX <<< "$S"
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount --resource-id service/$PREFIXO-cluster/$PREFIXO-$NOME \
    --min-capacity $MIN --max-capacity $MAX
  aws ecs update-service --cluster $PREFIXO-cluster --service $PREFIXO-$NOME --desired-count $MIN --query 'service.desiredCount'
done
aws ecs wait services-stable --cluster $PREFIXO-cluster --services $PREFIXO-chat-api $PREFIXO-order-worker
ALARMES=$(aws cloudwatch describe-alarms --alarm-name-prefix $PREFIXO- --query 'MetricAlarms[].AlarmName' --output text)
aws cloudwatch enable-alarm-actions --alarm-names $ALARMES
```

### (b) Desmontagem completa (ordem reversa das dependências)

Apaga tudo que foi criado. Rode bloco a bloco, conferindo a saída; alguns recursos levam minutos para sumir e o passo seguinte depende disso. Antes, rode o passo 0 para recarregar as variáveis.

```bash
# D1. Alarmes e SNS (apagar o tópico remove a assinatura)
ALARMES=$(aws cloudwatch describe-alarms --alarm-name-prefix $PREFIXO- --query 'MetricAlarms[].AlarmName' --output text)
aws cloudwatch delete-alarms --alarm-names $ALARMES
aws sns delete-topic --topic-arn $TOPICO_ARN

# D2. Auto scaling das tasks (remove as políticas e seus alarmes TargetTracking-*)
for S in chat-api order-worker; do
  aws application-autoscaling deregister-scalable-target --service-namespace ecs \
    --scalable-dimension ecs:service:DesiredCount --resource-id service/$PREFIXO-cluster/$PREFIXO-$S
done

# D3. Serviços
for S in chat-api order-worker; do
  aws ecs delete-service --cluster $PREFIXO-cluster --service $PREFIXO-$S --force --query 'service.status' --output text
done
aws ecs wait services-inactive --cluster $PREFIXO-cluster --services $PREFIXO-chat-api $PREFIXO-order-worker

# D4. Task definitions (todas as revisões)
for F in chat-api order-worker; do
  for TD in $(aws ecs list-task-definitions --family-prefix $PREFIXO-$F --query 'taskDefinitionArns' --output text); do
    aws ecs deregister-task-definition --task-definition $TD --query 'taskDefinition.status' --output text
  done
done
# Opcional: some de vez com as INACTIVE
# aws ecs delete-task-definitions --task-definitions $(aws ecs list-task-definitions --status INACTIVE --family-prefix $PREFIXO- --query 'taskDefinitionArns' --output text)

# D5. ALB (o target group só pode ser apagado depois do listener/ALB)
aws elbv2 delete-listener --listener-arn $LISTENER_ARN
aws elbv2 delete-load-balancer --load-balancer-arn $ALB_ARN
aws elbv2 wait load-balancers-deleted --load-balancer-arns $ALB_ARN
aws elbv2 delete-target-group --target-group-arn $TG_ARN

# D6. Capacity Provider -> ASG -> cluster -> Launch Template
aws ecs put-cluster-capacity-providers --cluster $PREFIXO-cluster \
  --capacity-providers '[]' --default-capacity-provider-strategy '[]' --query 'cluster.capacityProviders'
aws ecs delete-capacity-provider --capacity-provider $PREFIXO-cp --query 'capacityProvider.[status,updateStatus]' --output text
# repita até aparecer INACTIVE (ou nada):
aws ecs describe-capacity-providers --capacity-providers $PREFIXO-cp --query 'capacityProviders[0].[status,updateStatus]' --output text

aws autoscaling delete-auto-scaling-group --auto-scaling-group-name $PREFIXO-asg --force-delete
aws autoscaling wait group-not-exists --auto-scaling-group-names $PREFIXO-asg
for CI in $(aws ecs list-container-instances --cluster $PREFIXO-cluster --query 'containerInstanceArns' --output text); do
  aws ecs deregister-container-instance --cluster $PREFIXO-cluster --container-instance $CI --force --query 'containerInstance.status' --output text
done
aws ecs delete-cluster --cluster $PREFIXO-cluster --query 'cluster.status' --output text
aws ec2 delete-launch-template --launch-template-id $LT_ID --query 'LaunchTemplate.LaunchTemplateName' --output text

# D7. Logs (apaga junto os metric filters)
for S in chat-api order-worker; do aws logs delete-log-group --log-group-name /ecs/$PREFIXO/$S; done

# D8. ECR (--force apaga as imagens junto)
for R in chat-api order-worker; do
  aws ecr delete-repository --repository-name $PREFIXO/$R --force --query 'repository.repositoryName' --output text
done

# D9. SQS
aws sqs delete-queue --queue-url $FILA_URL
aws sqs delete-queue --queue-url $DLQ_URL

# D10. DynamoDB
for T in produtos pedidos conversas; do
  aws dynamodb delete-table --table-name $PREFIXO-$T --query 'TableDescription.TableStatus' --output text
  aws dynamodb wait table-not-exists --table-name $PREFIXO-$T
done

# D11. Segredo. Com janela de recuperação (mínimo 7 dias) o nome fica reservado e um
# create-secret com o mesmo nome falha até lá (use restore-secret para reaproveitar).
# --force-delete-without-recovery apaga na hora e NÃO tem volta.
aws secretsmanager delete-secret --secret-id "$SEGREDO_ARN" --recovery-window-in-days 7 --query DeletionDate --output text
# aws secretsmanager delete-secret --secret-id "$SEGREDO_ARN" --force-delete-without-recovery

# D12. IAM: inline -> gerenciadas -> instance profile -> roles
aws iam delete-role-policy --role-name $PREFIXO-chat-api-task --policy-name $PREFIXO-chat-api-acesso
aws iam delete-role-policy --role-name $PREFIXO-order-worker-task --policy-name $PREFIXO-order-worker-acesso
aws iam delete-role-policy --role-name $PREFIXO-ecs-task-execution --policy-name $PREFIXO-ler-segredo-llm
aws iam detach-role-policy --role-name $PREFIXO-ecs-task-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam detach-role-policy --role-name $PREFIXO-ecs-instance-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role
aws iam detach-role-policy --role-name $PREFIXO-ecs-instance-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam remove-role-from-instance-profile --instance-profile-name $PREFIXO-ecs-instance-profile \
  --role-name $PREFIXO-ecs-instance-role
aws iam delete-instance-profile --instance-profile-name $PREFIXO-ecs-instance-profile
for R in ecs-instance-role ecs-task-execution chat-api-task order-worker-task; do
  aws iam delete-role --role-name $PREFIXO-$R
done

# D13. Rede
aws ec2 delete-vpc-endpoints --vpc-endpoint-ids $VPCE_S3 $VPCE_DDB
aws ec2 delete-nat-gateway --nat-gateway-id $NAT_ID --query NatGatewayId --output text
aws ec2 wait nat-gateway-deleted --nat-gateway-ids $NAT_ID
#   (se o seu CLI não tiver esse waiter, repita até "deleted":
#    aws ec2 describe-nat-gateways --nat-gateway-ids $NAT_ID --query 'NatGateways[0].State' --output text)
aws ec2 release-address --allocation-id $EIP_ALLOC
aws ec2 detach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID
aws ec2 delete-internet-gateway --internet-gateway-id $IGW_ID
# Subnets: se der DependencyViolation, as interfaces de rede do ALB/NAT ainda estão sendo
# liberadas; espere 1 a 2 minutos e repita.
for SN in $SUBNET_PUB1 $SUBNET_PUB2 $SUBNET_PRIV1 $SUBNET_PRIV2; do aws ec2 delete-subnet --subnet-id $SN; done
aws ec2 delete-route-table --route-table-id $RT_PUB
aws ec2 delete-route-table --route-table-id $RT_PRIV
# Os dois SGs se referenciam: primeiro remova as regras cruzadas, depois apague
aws ec2 revoke-security-group-egress --group-id $SG_ALB \
  --ip-permissions "IpProtocol=tcp,FromPort=32768,ToPort=65535,UserIdGroupPairs=[{GroupId=$SG_ECS}]"
aws ec2 revoke-security-group-ingress --group-id $SG_ECS \
  --ip-permissions "IpProtocol=tcp,FromPort=32768,ToPort=65535,UserIdGroupPairs=[{GroupId=$SG_ALB}]"
aws ec2 delete-security-group --group-id $SG_ALB
aws ec2 delete-security-group --group-id $SG_ECS
aws ec2 delete-vpc --vpc-id $VPC_ID

# D14. Conferência final e limpeza local
aws resourcegroupstaggingapi get-resources --tag-filters Key=Projeto,Values=$PREFIXO \
  --query 'ResourceTagMappingList[].ResourceARN' --output text
#   (pode listar por alguns minutos recursos recém-apagados; o segredo aparece até o fim da janela)
rm -f "$IDS"; rm -rf infra/ohio/.render
```
