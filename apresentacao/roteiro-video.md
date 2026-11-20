# Roteiro do vídeo — Grão (Plataforma de Comércio Conversacional na AWS)

Duração-alvo: **13 min 30 s** (mínimo 10, máximo 15). Uma pessoa por etapa, na ordem obrigatória.

| Etapa | Quem | Tempo | Tela principal |
|---|---|---|---|
| 1. Startup e proposta de valor | Pessoa 1 | 1:30 | Slides da etapa 1 |
| 2. Demonstração real | Pessoa 2 | 2:00 | Página da aplicação no navegador |
| 3. Diagrama de arquitetura | Pessoa 3 | 2:00 | Slide do diagrama |
| 4. Navegação pelo Console AWS | Pessoa 4 | 2:30 | Console AWS em **sa-east-1** |
| 5. Conceitos e decisões | Pessoa 5 | 3:30 | Slides da etapa 5 + trechos do Terraform no VS Code |
| 6. Falhas e recuperação | Pessoa 6 | 2:00 | Slides da etapa 6 + gráficos de evidência |

As falas abaixo são uma base: **falem com as próprias palavras**, sem ler. O professor pode perguntar qualquer parte para qualquer pessoa, então todos devem ler o roteiro inteiro.

---

## Antes de gravar (checklist)

- [ ] Ambiente de São Paulo no ar: abrir `http://cafe-alb-170785092.sa-east-1.elb.amazonaws.com/` e ver a tabela de catálogo carregada.
- [ ] Estoque reposto (o Cerrado Mineiro deve mostrar 50). Se não, peça para rodar o seed de novo.
- [ ] Console AWS logado e com a região **South America (São Paulo) sa-east-1** selecionada.
- [ ] Abrir as abas do console **antes** de gravar (lista na Etapa 4), para não perder tempo carregando.
- [ ] Zoom do navegador em **125%–150%** e do VS Code com fonte ≥ 18. Feche notificações, e-mail e WhatsApp Web.
- [ ] **Nunca** abrir "Retrieve secret value" no Secrets Manager nem mostrar o `.env`, o `terraform.tfvars` ou o terminal com chaves.
- [ ] Gravar em 1080p (OBS ou Teams/Zoom gravando a tela compartilhada). Microfone perto, ambiente silencioso.
- [ ] Ensaio: cronometrar cada etapa uma vez antes da gravação final.

---

## Etapa 1 — Startup e proposta de valor (Pessoa 1, 1:30)

**Na tela:** slides "Capa" → "Problema" → "Solução e diferenciais" → "Modelo de negócio". Troque de slide no ritmo da fala.

**Fala:**

> Somos a **Grão**, uma plataforma de vendas conversacionais para lojas e torrefações de cafés especiais.
>
> O problema: quem compra café especial online encontra um catálogo estático com dezenas de origens, torras e notas sensoriais, e não sabe o que escolher. A loja pequena não tem gente para atender cada cliente, então perde a venda.
>
> A nossa solução é um **vendedor de IA** que conversa em linguagem natural, entende o gosto e o método de preparo do cliente, consulta o catálogo e o **estoque reais** e fecha o pedido ali mesmo, na conversa.
>
> O público são torrefações e cafeterias pequenas e médias que vendem online, e o consumidor de café especial que quer recomendação.
>
> Os diferenciais: atendimento consultivo 24 horas, pedido registrado direto no estoque, sem planilha, e regras comerciais aplicadas automaticamente — por exemplo, 10% de desconto a partir de 3 pacotes.
>
> O modelo de receita é **SaaS**: uma mensalidade por loja mais uma taxa pequena por pedido fechado. Como a infraestrutura escala com a demanda — mais tasks e máquinas só quando há clientes — o custo cresce junto com a receita, o que torna o negócio escalável e economicamente viável.

---

## Etapa 2 — Demonstração real da aplicação (Pessoa 2, 2:00)

**Na tela:** navegador em `http://cafe-alb-170785092.sa-east-1.elb.amazonaws.com/`, zoom 125%. Deixe a conversa e o catálogo visíveis lado a lado.

**Passo a passo (digite estas mensagens):**
1. `Oi! Gosto de café frutado e faço no coado. O que você recomenda?`
2. `Quanto tem em estoque do Etiópia Yirgacheffe?`
3. `Quero 3 pacotes do Etiópia.`
4. Se a IA pedir confirmação: `Pode confirmar.`
5. Aponte o cartão do pedido mudando de **PENDENTE** para **CONFIRMADO** e o estoque do Etiópia caindo de 20 para 17 na tabela (a linha pisca).
6. `E o meu pedido, já foi confirmado?` — a IA consulta o pedido no banco e responde com o status real.

**Fala (enquanto digita e espera):**

> Esta é a aplicação rodando na AWS em São Paulo, acessada pelo endereço público do load balancer.
>
> Vou pedir uma recomendação. Repare que o vendedor não inventa produtos: ele chama a ferramenta **buscar_produtos**, que consulta a tabela de produtos no DynamoDB, e responde com cafés, preços e notas que existem de verdade no catálogo — o mesmo que aparece aqui à direita.
>
> Agora pergunto o estoque: ele chama a ferramenta **consultar_estoque** e responde com o número real da tabela.
>
> Vou pedir 3 pacotes. A IA chama a ferramenta **criar_pedido**, que calcula o total com o desconto de 10% e grava o pedido como PENDENTE. O pedido vai para uma fila, e um segundo serviço, o worker, baixa o estoque e confirma.
>
> Aqui o pedido passou para **CONFIRMADO**, e o estoque do Etiópia caiu de 20 para 17 na tabela — isso é lido do banco a cada 3 segundos, então prova que a operação foi persistida.
>
> Por fim, pergunto pelo pedido: a IA usa a quarta ferramenta, **consultar_pedido**, e lê o status direto da tabela de pedidos. São quatro ferramentas no total: buscar produtos, consultar estoque, criar pedido e consultar pedido.
>
> Para o cliente, a jornada é: tirar dúvida, receber recomendação e comprar numa única conversa, sem navegar por catálogo.

> Dica: se a resposta da IA demorar, continue falando sobre o que está acontecendo por trás. Pode cortar a espera na edição.

---

## Etapa 3 — Diagrama de arquitetura (Pessoa 3, 2:00)

**Na tela:** slide do diagrama (e o slide "Caminho de uma requisição"). Use o cursor ou o apontador do PowerPoint para seguir cada seta enquanto fala.

**Fala:**

> Este é o diagrama da infraestrutura que criamos. Tudo fica numa **VPC própria**, em **duas zonas de disponibilidade**.
>
> Cada zona tem uma **sub-rede pública** e uma **privada**. Nas públicas ficam o **Application Load Balancer** e um **NAT Gateway**. Nas privadas ficam as instâncias **EC2** do cluster **ECS**, sem IP público.
>
> As instâncias são criadas por um **Auto Scaling Group** de 2 a 4 máquinas t3.small, controlado por um **Capacity Provider** do ECS. Nelas rodam dois serviços: o **chat-api**, de 2 a 8 tasks, e o **order-worker**, de 1 a 4. As imagens Docker dos dois ficam no **ECR**.
>
> O caminho de uma requisição: o cliente faz HTTP na porta 80 do ALB; o ALB repassa para uma task do chat-api numa porta dinâmica da instância; o chat-api lê o catálogo no **DynamoDB** e chama a **API do LLM** por HTTPS, saindo pelo NAT. Essa parte é **síncrona**: o cliente espera a resposta.
>
> Quando a IA cria um pedido, o chat-api grava o pedido como PENDENTE e publica o ID numa fila **SQS**. A partir daí é **assíncrono**: o order-worker consome a fila, baixa o estoque e confirma. Se uma mensagem falhar 3 vezes, ela vai para a **DLQ**.
>
> O acesso ao DynamoDB e ao S3 passa por **VPC endpoints**, sem passar pelo NAT. A chave do LLM fica no **Secrets Manager**, cada componente tem sua **role IAM**, e o **CloudWatch** recebe os logs, as métricas e os 10 alarmes, que notificam um tópico **SNS**.

---

## Etapa 4 — Navegação pelo Console AWS (Pessoa 4, 2:30)

**Na tela:** console AWS em **sa-east-1**. Abra as abas antes, nesta ordem, e passe ~12 s em cada uma. Em cada recurso, mostre **uma configuração concreta** (não só a página inicial).

| # | Onde clicar | O que mostrar | O que falar (curto) |
|---|---|---|---|
| 1 | VPC → Your VPCs → `cafe-vpc` → aba **Resource map** | 4 sub-redes em 2 AZs, 2 tabelas de rota, IGW, NAT | "Rede isolada: públicas com rota para o Internet Gateway, privadas com rota para o NAT." |
| 2 | VPC → Security groups → `cafe-ecs-sg` → **Inbound rules** | Portas 32768–65535 com origem `cafe-alb-sg` | "As instâncias só aceitam tráfego vindo do security group do ALB." |
| 3 | EC2 → Load balancers → `cafe-alb` → **Listeners**; depois Target groups → `cafe-chat-api-tg` → **Targets** | Listener 80; 2 targets *healthy* em portas altas, health check `/health` | "O ALB distribui entre as tasks e só manda tráfego para quem passa no health check." |
| 4 | ECS → Clusters → `cafe-cluster` → **Services** | `cafe-chat-api` 2/2 e `cafe-order-worker` 1/1 | "Dois serviços no mesmo cluster, cada um com sua escala." |
| 5 | Serviço `cafe-chat-api` → aba **Configuration and networking** / **Service auto scaling** | Duas políticas: CPU 60% e 600 requisições por task no ALB; mín. 2, máx. 8 | "Primeiro nível de elasticidade: número de tasks. Sobe se qualquer política pedir." |
| 6 | Cluster → aba **Infrastructure** | Capacity provider `cafe-cp`, target 100%, instâncias registradas | "Segundo nível: o Capacity Provider pede mais EC2 quando as tasks não cabem." |
| 7 | EC2 → Auto Scaling groups → `cafe-asg` | Mín. 2, máx. 4, 2 AZs, *scale-in protection* | "O ASG cria as máquinas a partir do launch template com a AMI otimizada para ECS." |
| 8 | ECR → Repositories → `cafe/chat-api` | Imagem com a tag do commit | "As imagens que o ECS baixa ao iniciar uma task." |
| 9 | DynamoDB → Tables → `cafe-pedidos` → **Explore items** | O pedido criado na demonstração, com status CONFIRMADO. Se houver vários pedidos, em **Scan** filtre por `pedido_id` (o ID aparece no cartão do pedido na página) | "Persistência: o pedido que acabamos de criar está aqui." |
| 10 | SQS → `cafe-pedidos` → aba **Dead-letter queue** | DLQ `cafe-pedidos-dlq`, *maximum receives* 3 | "Fila desacopla o pedido do processamento; falhou 3 vezes, vai para a DLQ." |
| 11 | IAM → Roles → buscar `cafe-sa-east-1` | 4 roles: instância, execução, chat-api-task, order-worker-task | "Cada componente só tem a permissão de que precisa." |
| 12 | Secrets Manager → `cafe/llm-api-key` (**não** clicar em *Retrieve*) | Só a página de detalhes | "A chave do LLM fica aqui e é injetada na task pela role de execução; nunca está no código." |
| 13 | CloudWatch → Alarms → All alarms | Lista de alarmes `cafe-*` | "Alarmes para tasks abaixo do desejado, reserva do cluster, ASG, erros 5xx, fila e DLQ." |
| 14 | CloudWatch → Log groups → `/ecs/cafe/order-worker` → stream mais recente | Linha JSON do pedido confirmado, com `pedido_id` e `conversa_id` | "Logs estruturados em JSON: o mesmo `conversa_id` aparece no chat e no worker, então dá para seguir um pedido de ponta a ponta." |

> Se faltar tempo, junte os itens 4–6 numa passada só e pule o 14.

---

## Etapa 5 — Conceitos, decisões de design e integração (Pessoa 5, 3:30)

**Na tela:** 4 slides da etapa 5 (um por tema). Em cada tema, mostre um trecho no VS Code por ~10 s (arquivos indicados).

**Rede e comunicação** — mostrar `infra/modules/network/main.tf` (regras dos security groups)

> A entrada é só pela porta 80 do ALB. O security group do ALB só pode sair para o das instâncias, e o das instâncias só aceita as portas dinâmicas 32768 a 65535 vindas do ALB — é um encadeamento de security groups, sem liberar nada por IP. As instâncias estão em sub-redes privadas: para sair à internet, só HTTPS 443 pelo NAT, que usamos para o LLM, a fila e o ECR. DynamoDB e S3 usam endpoints gateway, que são gratuitos e não passam pelo NAT.

**Containers e elasticidade** — mostrar `infra/envs/sa-east-1/main.tf` (bloco do `chat_api` com cpu, memória e `escala_cpu_alvo`)

> Cada serviço é uma imagem Docker no ECR. A rede é *bridge* com porta de host dinâmica, então várias tasks do chat cabem na mesma instância, e o ALB registra cada uma na sua porta. Reservamos CPU e memória por task — o chat reserva 384 MB — e é essa reserva que o ECS usa para decidir onde a task cabe.
>
> A elasticidade tem dois níveis. Nas tasks: o chat tem duas políticas, CPU média de 60% e 600 requisições por task no ALB — sobe quando qualquer uma pede e só desce quando as duas permitem. O worker escala pela quantidade de mensagens na fila por task, com alvo 20 e reação em 30 segundos, porque as métricas do SQS chegam com atraso. Nas instâncias: quando uma task não cabe, ela fica pendente, e o Capacity Provider aumenta o Auto Scaling Group. No teste de carga em São Paulo, o chat foi de 2 para 8 tasks, a 8ª não coube e o ASG subiu de 2 para 4 instâncias; depois, sem carga, tudo voltou para 2 com drenagem gerenciada. Os health checks são dois: o ALB testa `/health` no chat, e o worker tem um heartbeat que o ECS verifica.

**Dados, mensageria e segurança** — mostrar `app/order-worker/processador.py` (a `TransactWriteItems` com condição)

> A conversa é síncrona, o processamento do pedido é assíncrono. Isso protege o cliente: se o worker estiver lento ou fora, o pedido fica na fila e é processado depois. A fila tem visibilidade de 60 segundos: se o worker cair no meio, a mensagem volta e é retentada. Como pode chegar duplicada, o worker é idempotente: baixa o estoque e confirma o pedido numa única transação, com a condição de o pedido ainda estar PENDENTE e de haver estoque — o estoque nunca fica negativo. Depois de 3 falhas, a mensagem vai para a DLQ.
>
> Na segurança, separamos três tipos de role: a da instância, que só registra a máquina no cluster; a de execução, que baixa só as nossas duas imagens, escreve só nos nossos log groups e lê só o segredo do LLM; e uma role por serviço, com acesso só às tabelas e à fila de que ele precisa. Nenhuma política usa recurso curinga, exceto o token do ECR, que a AWS não permite restringir.
>
> Os logs são JSON, uma linha por evento, com `conversa_id` e `pedido_id`: o mesmo identificador aparece no chat, na fila e no worker.

**Terraform e decisões** — mostrar `infra/envs/sa-east-1/backend.tf` e a lista de módulos em `infra/modules/`

> A etapa 1 foi feita à mão em Ohio; a etapa 2 recria tudo em São Paulo com Terraform, sem depender de Ohio. O estado fica num bucket S3 versionado com lock, criado por um bootstrap. O código é dividido em 7 módulos — rede, ALB, dados, imagens, cluster, serviço, que é reutilizado pelos dois serviços, e observabilidade — e a região e o prefixo são variáveis. Um único `terraform apply` sobe tudo do zero sem passo manual: ele mesmo faz o build e o push das imagens Docker, carrega o catálogo no DynamoDB e grava a chave do LLM no Secrets Manager, recebida como variável efêmera, que não fica no estado. Nada fica fixo: as zonas e a AMI vêm de data sources, e os nomes IAM levam a região, porque IAM é global na conta.
>
> Os compromissos: usamos um NAT só, que é mais barato mas é ponto único de falha de saída; t3.small, que é suficiente para o MVP; e DynamoDB sob demanda, que custa quase zero parado.

---

## Etapa 6 — Falhas, riscos e recuperação de desastres (Pessoa 6, 2:00)

**Na tela:** slide da matriz de falhas → gráficos de `docs/evidencias.md` (instâncias e tasks) → slide "Alta disponibilidade ≠ recuperação de desastres".

**Fala:**

> Quando a plataforma falha, quais são os riscos e como recuperamos?
>
> **Task do chat cai:** o ECS repõe sozinho. Testamos parando uma task: o ALB continuou respondendo 60 de 60 requisições, porque havia outra task em outra zona. Detectamos pelo alarme de tasks abaixo do desejado.
>
> **Perda de uma instância EC2:** o Auto Scaling Group repõe a máquina e o ECS recoloca as tasks. No teste, voltou ao normal em cerca de 1 minuto, sem perda de dados, porque os dados ficam no DynamoDB, fora das instâncias.
>
> **Pedido com erro:** vai para a DLQ após 3 tentativas e dispara um alarme; o cliente não perde o pedido, e a operação investiga pelos logs no CloudWatch.
>
> **Queda de uma zona inteira:** as tasks estão espalhadas nas duas zonas, então o serviço continua — mas o NAT está numa zona só, então perderíamos a saída para o LLM. A melhoria é um NAT por zona.
>
> **Falha de dados ou da região:** o DynamoDB já é replicado entre zonas pela AWS, mas não ativamos backup contínuo. Se a região inteira cair, o Terraform recria tudo em outra região em cerca de 15 a 20 minutos, mas os dados não iriam junto.
>
> Então, a resposta objetiva: hoje temos **alta disponibilidade dentro da região** — sobrevivemos a falha de task, de instância e, parcialmente, de zona, sem intervenção. Isso **não é** uma estratégia completa de recuperação de desastres. Para uma startup real, as prioridades seriam: backup contínuo do DynamoDB, um NAT por zona, alarmes com notificação para a equipe de plantão e, depois, réplica dos dados em outra região com Global Tables, definindo metas de tempo e de perda de dados aceitáveis.

---

## Depois de gravar

- Confira se nenhuma chave, token ou o ID da conta aparece legível no vídeo (barra de busca do console, URLs, terminal).
- Exportar em MP4. Se for link, deixar público para quem tem o link (sem pedir permissão).
- Avisar para desligar o ambiente de São Paulo (`terraform destroy`) e o de Ohio.
