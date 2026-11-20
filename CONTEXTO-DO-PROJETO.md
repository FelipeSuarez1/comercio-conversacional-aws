# Contexto do projeto — para quem for continuar

Documento de passagem de bastão, escrito em 20/11/2026 (~16:30). Resume tudo o que foi decidido, feito e testado até aqui, o que falta e o que fazer se algo der errado. Leia isto primeiro; os detalhes técnicos estão nos arquivos linkados.

---

## 1. O projeto em uma frase

**Grão**: uma loja online de cafés especiais em que o cliente compra **conversando com um vendedor de IA**. A IA consulta o catálogo e o estoque reais no banco, fecha o pedido e acompanha o status. Por trás, uma arquitetura AWS (ECS sobre EC2) que escala sozinha, aguenta falhas e é recriada do zero com um único `terraform apply`.

Disciplina: CLOUD 101 (Insper), projeto semestral "Plataforma de Comércio Conversacional na AWS".

- **Etapa 1 (manual):** ambiente montado à mão com AWS CLI em **Ohio (us-east-2)**. Passo a passo em [docs/ohio-manual.md](docs/ohio-manual.md).
- **Etapa 2 (Terraform):** o mesmo ambiente recriado com Terraform em **São Paulo (sa-east-1)**. Ver [docs/terraform.md](docs/terraform.md).

## 2. Status atual

**Conceito B concluído, testado e no GitHub.** Falta só **gravar, editar e entregar o vídeo** (entrega na noite de 20/11).

| Item | Situação |
|---|---|
| Código (app + Terraform), docs e evidências | Prontos, no GitHub (repositório privado do Felipe) |
| São Paulo (Terraform) | **No ar**, com a IA real funcionando |
| Ohio (manual) | **No ar**, com tudo de B aplicado |
| Roteiro do vídeo | [apresentacao/roteiro-video.md](apresentacao/roteiro-video.md), passo a passo por pessoa |
| Apresentação | [apresentacao/apresentacao-video.pptx](apresentacao/apresentacao-video.pptx), 19 slides, com os nomes |
| Estoque para a demo | Reposto (Etiópia Yirgacheffe = 20, Cerrado Mineiro = 50, Panamá Geisha = 2) |

## 3. Links

| O quê | Endereço |
|---|---|
| **Aplicação (São Paulo) — a usada no vídeo** | http://cafe-alb-170785092.sa-east-1.elb.amazonaws.com/ |
| Aplicação (Ohio) | http://cafe-alb-1875866830.us-east-2.elb.amazonaws.com/ |
| Repositório | github.com/FelipeSuarez1/comercio-conversacional-aws (privado) |
| Portal de login da AWS (só o Felipe tem acesso) | https://d-9067f848eb.awsapps.com/start |

A página é pública: qualquer pessoa com o link conversa com o vendedor, vê o catálogo ao vivo e faz pedidos. Não precisa de login. Cada mensagem gasta crédito da chave da IA.

## 4. O vídeo (o que falta fazer)

Requisitos do PDF de entrega ("Instruções de Entrega — Vídeo do Projeto Final"):
- 10 a 15 minutos, 6 etapas **nesta ordem**, todos os integrantes narram.
- A IA precisa consultar e alterar dados **de verdade** na demonstração.
- O Terraform no GitHub precisa ser **totalmente funcional, sem intervenção manual**.
- **Não expor credenciais** (chave da IA, ID da conta AWS, tokens).

| Etapa | Quem | Tempo | Slides |
|---|---|---|---|
| 1. Startup e proposta de valor | Felipe Suarez | 1:30 | 1–4 |
| 2. Demonstração real | David Chung | 2:00 | 5 + navegador |
| 3. Diagrama de arquitetura | Luiz Pinheiro | 2:00 | 6–8 |
| 4. Console AWS | Lenny Wajcberg (narra) + Felipe (compartilha o console) | 2:30 | 9 + console |
| 5. Conceitos e decisões | Ricardo Peano | 3:30 | 10–15 + VS Code |
| 6. Falhas e recuperação de desastres | Fernando Mentone | 2:00 | 16–19 |

Tudo o que cada um fala e mostra está no [roteiro](apresentacao/roteiro-video.md), incluindo a seção "Como gravar (Teams)".

**Gravação:** reunião no Teams com conta do Insper, câmeras ligadas, cada um compartilha a própria janela na sua vez. O Teams salva em MP4 (chat da reunião → gravação → Download, de preferência por quem iniciou a gravação). Para cortar e juntar: Clipchamp (vem no Windows 11), exportar em 1080p.

**Demo (Etapa 2), mensagens exatas:**
1. `Oi! Gosto de café frutado e faço no coado. O que você recomenda?`
2. `Quanto tem em estoque do Etiópia Yirgacheffe?`
3. `Quero 3 pacotes do Etiópia.` (se pedir confirmação: `Pode confirmar.`)
4. Mostrar o cartão do pedido indo de PENDENTE para CONFIRMADO e o Etiópia caindo de 20 para 17.
5. `E o meu pedido, já foi confirmado?`

> **Ninguém deve fazer compras de teste depois da reposição do estoque**, senão os números da demo mudam.

### Se o Felipe não puder participar à noite

- As etapas 1, 2, 3, 5 e 6 **não dependem de acesso à AWS**: a página é pública e o resto é PPT e código. Outra pessoa assume a fala da Etapa 1.
- A **Etapa 4 (console AWS)** só o Felipe consegue mostrar ao vivo, porque só ele tem login na conta. Alternativas, em ordem de preferência:
  1. O Felipe grava antes só a navegação do console (compartilhando a tela, ~2:30), seguindo a tabela da Etapa 4, e o Lenny narra por cima na edição.
  2. Se não houver gravação, usar prints do console (o Felipe tira e manda) e o Lenny narra sobre eles. Os gráficos em [docs/evidencias/](docs/evidencias/) também servem de apoio.
- **Ninguém além do Felipe deve receber a senha ou a chave da IA.** Nunca colar chaves no chat do grupo.

## 5. Arquitetura (resumo)

- **chat-api** (FastAPI, Python) atrás de um **ALB** público. Fala com uma API de LLM externa (compatível com OpenAI) usando *tool calling* com 4 ferramentas: `buscar_produtos`, `consultar_estoque`, `criar_pedido`, `consultar_pedido`. Serve também a página do chat em `/`.
- **DynamoDB**: tabelas `cafe-produtos`, `cafe-pedidos`, `cafe-conversas`.
- **SQS** `cafe-pedidos` com **DLQ** (`cafe-pedidos-dlq`, após 3 tentativas, visibilidade 60 s).
- **order-worker**: consome a fila e baixa o estoque numa transação condicional (idempotente, estoque nunca negativo); marca o pedido CONFIRMADO ou REJEITADO.
- **ECS sobre EC2**: ASG de 2 a 4 `t3.small` com **Capacity Provider** (managed scaling, managed draining, proteção de scale-in). Rede *bridge* com porta dinâmica.
- **VPC** em 2 AZs: ALB e 1 NAT nas sub-redes públicas, instâncias nas privadas. Endpoints gateway para DynamoDB e S3.
- **Segurança:** chave do LLM no **Secrets Manager**; IAM com role de instância, de execução e uma por serviço, todas restritas aos recursos exatos.
- **Observabilidade:** logs JSON no CloudWatch (com `conversa_id` e `pedido_id`), Container Insights e 10 alarmes publicando num tópico SNS.

Detalhes e diagrama em [docs/arquitetura.md](docs/arquitetura.md).

### O que mudou de C para B (o que faz ser B)

1. **Terraform realmente automático**: um único `terraform apply` faz o build e o push das imagens Docker, carrega o catálogo e cria o segredo. No C, isso eram passos à mão.
2. **4 tools em vez de 2** (`consultar_estoque` e `consultar_pedido` novas).
3. **Escala melhor**: o chat escala por CPU 60% **e** por requisições no ALB (600 por task/min); o worker usa alvo de 20 mensagens por task e reage em 30 s (antes, 100).
4. **Logs JSON correlacionados** entre chat, fila e worker.
5. **Alarmes calibrados** com os testes de carga (ex.: 5xx em % das respostas, não em contagem fixa) e SNS com e-mail opcional.
6. **IAM mais restrito** (role de execução só com as 2 imagens, os log groups e o segredo).

A tabela completa C × B está em [docs/planejamento.md](docs/planejamento.md).

## 6. Resultados que vão no vídeo

Detalhes, horários e gráficos em [docs/evidencias.md](docs/evidencias.md).

| Teste | Ohio (manual) | São Paulo (Terraform) |
|---|---|---|
| Chat escala por CPU | 2 → 8 tasks | 2 → 8 tasks |
| Worker escala pela fila | 1 → 4 | 1 → 4 em ~4 min (antes ~6) |
| EC2 pelo Capacity Provider | 2 → 3 | 2 → 4, e volta a 2 com drenagem |
| Derrubar uma task | 60/60 respostas ok | 60/60 ok |
| Perder uma instância | volta em ~1,5 min | volta em ~1 min |
| Mensagem inválida → DLQ + alarme | sim | sim |
| Escala por requisições (B) | configurada | 3 → 6 tasks com CPU < 40% |
| Destroy + apply único do zero (B) | — | 89 recursos removidos em 6 min; 89 recriados em 2 min 46 s, sem erro |

## 7. Operações comuns (exigem o login AWS do Felipe)

Pré-requisitos no computador: AWS CLI logada (`aws sso login`), Terraform 1.17, Docker Desktop aberto (para o `apply`) e Python. Comandos em Git Bash, a partir da pasta do repositório.

**Repor o estoque para a demo** (volta todos os cafés aos valores iniciais):
```bash
AWS_REGION=sa-east-1 TABELA_PRODUTOS=cafe-produtos TABELA_PEDIDOS=cafe-pedidos TABELA_CONVERSAS=cafe-conversas python scripts/seed.py
```
Precisa de `boto3` instalado (`pip install boto3`).

**Chat responde "Nosso vendedor está indisponível"**: a chave da IA está errada ou faltando no segredo.
1. Console AWS → região São Paulo → Secrets Manager → `cafe/llm-api-key` → Retrieve secret value → Edit → aba Plaintext → colar só a chave → Save.
2. Reiniciar o chat para ele ler a chave nova:
```bash
aws ecs update-service --region sa-east-1 --cluster cafe-cluster --service cafe-chat-api --force-new-deployment
```
Leva 2 a 3 minutos.

**Recriar São Paulo do zero** (só se algo quebrar de vez; o link do ALB muda e é preciso colar a chave de novo depois):
```bash
export MSYS_NO_PATHCONV=1
terraform -chdir=infra/envs/sa-east-1 init -backend-config=backend.hcl
terraform -chdir=infra/envs/sa-east-1 destroy
terraform -chdir=infra/envs/sa-east-1 apply
```
Os arquivos `backend.hcl` e `terraform.tfvars` existem só no computador do Felipe (não vão para o Git); há modelos `.example` na mesma pasta.

## 8. Depois da entrega (importante, custa dinheiro)

Os dois ambientes estão ligados. O NAT Gateway, o ALB e as EC2 cobram por hora.
1. **São Paulo:** `terraform -chdir=infra/envs/sa-east-1 destroy` (o destroy foi corrigido e roda limpo em ~6 min).
2. **Ohio:** pausar (tasks e ASG a zero) ou desmontar, conforme a seção "Desligar para economizar" do [ohio-manual.md](docs/ohio-manual.md).
3. Conferir no console (Billing) que não sobrou nada cobrando.

## 9. Problemas encontrados e como foram resolvidos

Bom saber caso o professor pergunte:

- **Destroy travava** com os serviços ECS presos em DRAINING: o Terraform apagava a rota de internet e a regra de saída HTTPS antes dos serviços, e os agentes ECS perdiam a conexão. Corrigido com dependências explícitas em `infra/modules/network/outputs.tf`.
- **Build das imagens pelo provider Docker** falhava no Docker Desktop do Windows; trocado por `docker build` chamado pelo próprio `apply` (módulo `infra/modules/images`).
- **Escala por requisições com alvo 1500** não disparava no teste; recalibrada para 600 req/task/min, que representa melhor uma conversa real (a task fica esperando a IA com a CPU baixa).
- **Worker escala com atraso**: as métricas do SQS chegam ao CloudWatch com 1 a 5 min de atraso. O alvo menor (20) e o cooldown de 30 s melhoraram, mas esse limite é da AWS.
- **Nomes IAM colidiam entre regiões** (IAM é global): os nomes levam a região (`cafe-sa-east-1-...`).

## 10. Regras do grupo

- Commits no repositório **no nome do Felipe**.
- **Nunca** mostrar ou enviar: a chave da IA, o ID da conta AWS (canto superior direito do console), o `terraform.tfvars`, o `.env`, nem clicar em "Retrieve secret value" durante a gravação.
- Se mudar algo no código, atualizar a documentação junto.

## 11. Onde está cada coisa

| Pasta/arquivo | Conteúdo |
|---|---|
| `app/chat-api/` | API do chat, tools, página web (`pagina.py`), testes |
| `app/order-worker/` | Worker da fila, processamento do pedido, testes |
| `infra/envs/sa-east-1/` | Ambiente Terraform de São Paulo |
| `infra/modules/` | 7 módulos: network, alb, data, images, cluster, service, observability |
| `infra/ohio/` | JSONs usados na montagem manual de Ohio |
| `scripts/` | `seed.py` (catálogo), `carga.py` (teste de carga HTTP), `enfileirar-pedidos.py` (carga na fila), `smoke-test.sh` |
| `docs/` | Arquitetura, planejamento, contratos, manual de Ohio, Terraform, recursos e evidências |
| `apresentacao/` | Roteiro do vídeo e PPT |
| `docker-compose.yml` | Roda tudo localmente, sem AWS (IA em modo `fake`) |
