# Titanic Survival API — Documento Técnico de Decisões

## 1. Contexto do Case

O case original ([github.com/CaioMar/case_software_engineer](https://github.com/CaioMar/case_software_engineer)) solicita a construção de uma API serverless na AWS que:

- Exponha o endpoint `/sobreviventes` via **API Gateway**
- Use **Lambda em Python** para executar inferência com um modelo Random Forest pré-treinado (`model.pkl`)
- Persista cada predição em **DynamoDB**
- Seja provisionada inteiramente via **Terraform**
- Seja documentada com **OpenAPI 3.0**
- Suporte operações **POST, GET e DELETE**

---

## 2. Arquitetura Geral

```
Cliente HTTP
    │
    ▼
API Gateway v1 (REST)
  └─ OpenAPI 3.0 com x-amazon-apigateway-integration
    │
    ▼
Lambda (Python 3.9, 1024 MB)
  ├─ handler.py        ← dispatcher de rotas
  ├─ preprocessing.py  ← feature engineering
  └─ model.pkl         ← Random Forest (carregado 1x no init)
    │
    ▼
DynamoDB (PAY_PER_REQUEST)
  └─ titanic-{env}-sobreviventes
```

---

## 3. Decisões Técnicas e Justificativas

### 3.1 Lambda via Container Image (ECR) em vez de ZIP

**O que foi feito:** o Lambda é deployado como imagem Docker armazenada no ECR, e não como arquivo `.zip`.

**Por quê:**

O limite do Lambda para pacote ZIP é **50 MB comprimido / 250 MB descomprimido**. A stack de ML (`scikit-learn + pandas + numpy`) ocupa ~400 MB descomprimida — inviabilizando o ZIP mesmo com limpeza agressiva de arquivos.

A imagem de container resolve isso:
- Limite de **10 GB** para imagens ECR
- A base `public.ecr.aws/lambda/python:3.9` é a imagem oficial da AWS para Lambda, garantindo compatibilidade binária com o ambiente de execução
- O `docker buildx build --platform linux/amd64` garante que os binários compilados (extensões C do numpy/scikit-learn) sejam para a arquitetura correta, independente do SO do desenvolvedor (Windows, macOS ARM)
- O Terraform detecta mudanças nos arquivos fonte via `filesha256()` e aciona rebuild automaticamente

> O `build_package.sh` existe como alternativa (ZIP via Docker), mas foi descartado em produção exatamente por esse limite de tamanho.

---

### 3.2 Fixação do numpy em `1.24.4`

**O que foi feito:** `requirements.txt` tem `numpy==1.24.4` explícito.

**Por quê:**

`scikit-learn==1.1.3` foi compilado com as headers do numpy 1.x. O numpy 2.0 (lançado em 2024) mudou o tamanho interno da struct `dtype` de 88 para 96 bytes. Sem a fixação, o pip resolvia `numpy>=2.0`, gerando em runtime:

```
ValueError: numpy.dtype size changed, may indicate binary incompatibility.
Expected 96 from C header, got 88 from PyObject
```

A versão `1.24.4` é a última 1.x compatível com `scikit-learn==1.1.3` e `pandas==1.5.3`. Respeita as constraints de ABI sem exigir upgrade do scikit-learn.

---

### 3.3 Memória Lambda: 1024 MB

**O que foi feito:** `memory_size = 1024` no `lambda.tf`.

**Por quê:**

Na AWS, **CPU é alocada proporcionalmente à memória**. Com 512 MB o Lambda recebia CPU insuficiente para carregar scikit-learn + numpy + model.pkl dentro do **timeout de 10 segundos do INIT phase** (fase de inicialização do container, separada do timeout da função). O CloudWatch confirmou:

```
INIT_REPORT Init Duration: 10000.23 ms  Phase: init  Status: timeout
```

Com 1024 MB (dobro de CPU) o init passou a completar em ~3-4 segundos. O modelo fica carregado em memória entre invocações (warm start), então o custo adicional só incide no cold start.

---

### 3.4 Terraform como IaC

**O que foi feito:** toda a infraestrutura (ECR, Lambda, IAM, DynamoDB, API Gateway) está em Terraform.

**Por quê:**

- **Reprodutibilidade:** qualquer pessoa com credenciais AWS consegue replicar o ambiente exato com `terraform apply`
- **Versionamento:** mudanças de infra são rastreadas no git como código
- **Atomicidade:** o `terraform destroy` remove todos os recursos sem deixar lixo na conta
- **Parametrização:** `variables.tf` permite deploy em múltiplas regiões/ambientes via `-var`

A alternativa seria AWS CDK (TypeScript/Python), mas Terraform é mais universal em squads multidisciplinares e não exige conhecimento de uma linguagem específica para ler o plano.

---

### 3.5 API Gateway v1 com import de OpenAPI

**O que foi feito:** o API Gateway é criado via `body = templatefile("openapi.yaml")`, com as integrações AWS declaradas no próprio spec (`x-amazon-apigateway-integration`).

#### O que é OpenAPI?

OpenAPI (anteriormente chamado de Swagger) é um padrão para descrever APIs REST em YAML ou JSON. O arquivo descreve cada rota, quais parâmetros ela aceita, quais respostas ela retorna e quais schemas de dados estão envolvidos. É independente de linguagem e de plataforma — funciona como um contrato formal entre quem expõe e quem consome a API.

Um trecho típico:

```yaml
paths:
  /sobreviventes:
    post:
      summary: Create survival prediction
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/PassengerInput"   # ← referência ao schema definido abaixo
      responses:
        "201":
          description: Prediction created
```

Isso define: "existe uma rota POST /sobreviventes, que espera um JSON no formato PassengerInput e retorna 201 em caso de sucesso". O schema `PassengerInput` fica declarado na seção `components/schemas` e pode ser reutilizado em múltiplos endpoints via `$ref`.

#### O que é `x-amazon-apigateway-integration`?

O prefixo `x-` em YAML/OpenAPI indica uma **extensão customizada** — um campo que não faz parte do padrão OpenAPI mas é interpretado por uma ferramenta específica. A AWS definiu suas próprias extensões para que o API Gateway consiga ler um spec OpenAPI e já saber para onde encaminhar cada requisição.

Sem essa extensão, o OpenAPI apenas documenta a API. Com ela, o próprio arquivo vira a configuração do roteamento:

```yaml
x-amazon-apigateway-integration:
  httpMethod: POST      # método usado para chamar o backend (sempre POST para Lambda)
  type: aws_proxy       # modo de integração
  uri: "${lambda_invoke_arn}"  # ARN do Lambda que vai processar a requisição
```

Cada campo:

- **`type: aws_proxy`** — modo "Lambda Proxy". O API Gateway repassa a requisição HTTP inteira para o Lambda como um evento JSON (método, path, headers, body, pathParameters), sem transformações. O Lambda é responsável por montar a resposta completa (statusCode, headers, body). É o modo mais simples e mais usado.

- **`httpMethod: POST`** — o método HTTP que o API Gateway usa internamente para invocar o Lambda. **Sempre `POST`**, independente do método da rota pública (`GET`, `DELETE`, etc.). Isso é uma peculiaridade da AWS: a invocação do Lambda pelo Gateway é sempre via POST — o método da rota pública é apenas o que o cliente externo vê.

- **`uri`** — o endereço de invocação do Lambda no formato ARN. No arquivo está como `${lambda_invoke_arn}`, que é uma variável de template do Terraform substituída em tempo de `apply` pelo ARN real da função criada.

#### Por que colocar a integração dentro do OpenAPI em vez de configurar separadamente no Terraform?

A abordagem alternativa seria criar cada rota no Terraform com recursos separados (`aws_api_gateway_resource`, `aws_api_gateway_method`, `aws_api_gateway_integration`), que rapidamente gera dezenas de blocos HCL para poucos endpoints.

Ao declarar tudo no OpenAPI:
- O arquivo é a **fonte única de verdade** — contrato e roteamento vivem juntos
- O Terraform faz um único `aws_api_gateway_rest_api` com `body = templatefile(...)`, que importa o spec completo de uma vez
- Mudanças no contrato (novo campo, novo endpoint) são feitas em um só lugar

O trigger de redeployment via `sha1(body)` garante que qualquer alteração no OpenAPI dispara automaticamente um novo deployment no Gateway:

```hcl
resource "aws_api_gateway_deployment" "main" {
  triggers = {
    redeployment = sha1(aws_api_gateway_rest_api.main.body)
  }
}
```

**Por quê v1 (REST) e não v2 (HTTP API):**

A API v2 é mais barata e tem menor latência, mas o suporte a import de spec OpenAPI completo com `x-amazon-apigateway-integration` é mais maduro e documentado na v1. Para um case com foco em clareza arquitetural, a v1 é a escolha mais explícita.

---

### 3.6 Lambda não é um servidor HTTP — API Gateway é

**O que acontece:** o Lambda não escuta porta, não recebe conexão TCP e não sabe o que é GET ou POST. Quem desempenha o papel de servidor HTTP é o **API Gateway**. O Lambda é apenas uma função que recebe um dicionário Python e retorna outro.

**Fluxo completo de uma requisição:**

```
Cliente (curl / Bruno / browser)
    │
    │  HTTP real: GET /sobreviventes?limit=10
    │  (conexão TCP → TLS → HTTP/1.1)
    │
    ▼
API Gateway v1 (servidor HTTP gerenciado pela AWS)
    │
    │  1. Aceita a conexão TCP/TLS (porta 443)
    │  2. Parseia a requisição HTTP: método, path, headers, query string, body
    │  3. Consulta a tabela de rotas (importada do openapi.yaml)
    │  4. Encontra o match: GET + /sobreviventes → Lambda X (aws_proxy)
    │  5. Serializa TUDO sobre a requisição num JSON padronizado ("event")
    │  6. Invoca o Lambda via AWS SDK (chamada síncrona, sempre via POST interno)
    │
    ▼
Lambda (função Python pura, sem socket, sem porta)
    │
    │  def lambda_handler(event, context):
    │      event = {
    │          "httpMethod": "GET",              ← string, não um verbo HTTP real
    │          "resource": "/sobreviventes",     ← template da rota
    │          "path": "/sobreviventes",         ← path real requisitado
    │          "queryStringParameters": {"limit": "10"},
    │          "pathParameters": null,
    │          "headers": {"Content-Type": "application/json", ...},
    │          "body": null
    │      }
    │
    │  Retorna um dict:
    │      return {
    │          "statusCode": 200,
    │          "headers": {"Content-Type": "application/json"},
    │          "body": "{\"items\": [...], \"count\": 5}"
    │      }
    │
    ▼
API Gateway
    │
    │  Converte o dict de volta em resposta HTTP:
    │  HTTP/1.1 200 OK
    │  Content-Type: application/json
    │  {"items": [...], "count": 5}
    │
    ▼
Cliente recebe a resposta HTTP convencional
```

**O ponto crítico: Lambda Proxy Integration (`type: aws_proxy`)**

Quando o `openapi.yaml` declara `type: aws_proxy`, está dizendo ao API Gateway: "empacote 100% do request HTTP num JSON padronizado e envie ao Lambda sem transformação". Na volta, o Lambda deve retornar um dict com `statusCode`, `headers` e `body` — e o Gateway converte de volta em HTTP.

Sem essa integração, o Lambda receberia apenas o body (ou um subconjunto configurável). Com `aws_proxy`, ele recebe tudo: método, headers, query string, path parameters, body. Isso dá ao Lambda autonomia total para decidir o que fazer — ao custo de ter que montar a resposta HTTP completa manualmente.

**Por que `httpMethod: POST` no integration, mesmo em rotas GET/DELETE?**

O campo `httpMethod` dentro de `x-amazon-apigateway-integration` é o método que o API Gateway usa **internamente** para chamar o backend Lambda via AWS SDK. Isso é sempre `POST`, independente de o cliente ter feito `GET`, `DELETE` ou qualquer outro verbo. É uma peculiaridade da AWS: a invocação de Lambda pelo Gateway é uma chamada de API interna (não HTTP público), e a AWS escolheu POST como o verbo fixo para essa invocação. O método do cliente chega ao Lambda como `event["httpMethod"]` — uma string dentro do JSON, não um verbo TCP.

**Como o handler distingue GET de POST na mesma rota:**

O dispatch é feito manualmente pelo dicionário `ROUTES`, combinando `httpMethod` + `resource` — ambos são apenas strings extraídas do event JSON:

```python
ROUTES = {
    ("POST",   "/sobreviventes"):      post_sobreviventes,
    ("GET",    "/sobreviventes"):      get_sobreviventes,
    ("GET",    "/sobreviventes/{id}"): get_sobrevivente_by_id,
    ("DELETE", "/sobreviventes/{id}"): delete_sobrevivente,
}

def lambda_handler(event, _context):
    method   = event["httpMethod"]    # "GET" — uma string, não um verbo HTTP real
    resource = event["resource"]      # "/sobreviventes/{id}" — template, não path real
    handler_fn = ROUTES.get((method, resource))
```

O Lambda não "sabe" o que é HTTP. Ele recebe um `dict`, lê strings, e retorna outro `dict`. Toda a semântica HTTP (TCP, TLS, parsing, content negotiation, CORS) é responsabilidade exclusiva do API Gateway.

**Contraste com frameworks web tradicionais:**

Em Flask ou FastAPI, a aplicação **é** o servidor HTTP — ela faz bind em uma porta, aceita conexões TCP e parseia HTTP internamente. No modelo serverless com API Gateway + Lambda, essas responsabilidades são separadas: o Gateway é o servidor, o Lambda é a lógica. Isso é o que permite ao Lambda escalar para zero (não há processo escutando porta) e escalar horizontalmente (a AWS instancia quantas cópias forem necessárias, cada uma recebendo events independentes).

---

### 3.7 Dispatcher de rotas em Lambda único (complemento da 3.6)

**O que foi feito:** uma única função Lambda com um dicionário `ROUTES` que mapeia `(method, resource)` para handlers.

**Por quê:**

Dado o volume esperado (case/demo), uma função por rota seria over-engineering. O padrão de dispatcher:

```python
ROUTES = {
    ("POST", "/sobreviventes"): post_sobreviventes,
    ("GET",  "/sobreviventes"): get_sobreviventes,
    ...
}
```

- Mantém o modelo carregado em memória compartilhada entre todas as rotas (warm start eficiente)
- É simples de ler e estender
- Evita cold start duplicado por função

Se o volume crescesse ou os handlers tivessem dependências divergentes, a separação em múltiplas funções seria justificada.

---

### 3.8 DynamoDB com PAY_PER_REQUEST

**O que foi feito:** `billing_mode = "PAY_PER_REQUEST"` sem throughput provisionado.

**Por quê:**

Para tráfego imprevisível ou baixo (como em um case/demo), PAY_PER_REQUEST elimina o desperdício de capacidade ociosa. Não há necessidade de estimar RCU/WCU. A tabela escala automaticamente e só gera custo por operação efetivamente executada.

A chave de partição é `id` (UUID v4), garantindo distribuição uniforme — evita hot partitions que degradariam performance em tabelas com billing provisionado.

---

### 3.9 UUID v4 como identificador

**O que foi feito:** `item_id = str(uuid.uuid4())` gerado no Lambda.

**Por quê:**

- **Stateless:** o Lambda não precisa consultar o banco para gerar o próximo ID
- **Sem colisões práticas:** 2¹²² de espaço de endereçamento
- **Distribuição uniforme no DynamoDB:** UUIDs aleatórios distribuem writes igualmente entre partições

Alternativas como IDs sequenciais criariam hot partition no DynamoDB (todos os writes no mesmo shard). Timestamps teriam colisão em concorrência.

---

### 3.10 Decimal para persistência de floats no DynamoDB

**O que foi feito:** `survival_probability` e campos numéricos são convertidos para `Decimal` antes do `put_item`.

**Por quê:**

O boto3 rejeita `float` nativo do Python ao escrever no DynamoDB (levanta `TypeError`). A solução correta é `Decimal(str(round(valor, 6)))` — converter para string intermediária evita erros de representação binária de ponto flutuante (ex: `0.1 + 0.2 ≠ 0.3` em float).

Na leitura, `_item_to_dict` converte `Decimal` de volta para `float` para serialização JSON.

---

### 3.11 One-hot encoding manual no `preprocessing.py`

**O que foi feito:** o `preprocessing.py` usa `pd.get_dummies` sem `drop_first=True` e depois seleciona manualmente apenas as colunas que o modelo espera (`Sex_male`, `Embarked_Q`, `Embarked_S`), em vez de usar `drop_first=True` diretamente.

**Contexto — como o modelo foi treinado:**

No notebook original (`modelo/treinamento.ipynb`), o encoding foi feito com:

```python
pd.get_dummies(df[cat_preds], drop_first=True)
```

O `drop_first=True` descarta a primeira categoria alfabética de cada variável categórica para evitar multicolinearidade (a "dummy variable trap"). O resultado no dataset de treino:

- **Sex** (`female`, `male`) → gerou apenas `Sex_male`. `Sex_female` foi descartada — se `Sex_male=0`, implicitamente é female.
- **Embarked** (`C`, `Q`, `S`) → gerou apenas `Embarked_Q` e `Embarked_S`. `Embarked_C` foi descartada — se ambas são 0, implicitamente é C (Cherbourg).

O modelo foi treinado com 8 features exatas: `Age, Parch, SibSp, Fare, Pclass, Sex_male, Embarked_Q, Embarked_S`.

**Por que não usar `drop_first=True` na inferência:**

No treinamento, o `get_dummies` recebe o dataset inteiro — todas as categorias aparecem nas linhas, gerando todas as colunas dummy. O `drop_first=True` então descarta a primeira coluna de cada grupo de forma previsível.

Na API, o `get_dummies` recebe **um único registro por vez**. Se o payload tem `"Sex": "male"`, o `get_dummies` gera apenas `Sex_male` (uma categoria → uma coluna). O `drop_first=True` descartaria **essa única coluna**, resultando em zero features para Sex — quebrando o modelo.

Exemplo concreto:

```python
# No treinamento (dataset com milhares de linhas):
pd.get_dummies(df["Sex"], prefix="Sex", drop_first=True)
#   Sex_male
# 0        1
# 1        0    ← female, codificado como "não male"
# ...

# Na API (um registro só com Sex="male"):
pd.get_dummies(pd.DataFrame([{"Sex": "male"}])["Sex"], prefix="Sex", drop_first=True)
#   (DataFrame vazio — a única coluna foi descartada!)
```

**A solução adotada:**

```python
# Gera TODAS as dummies (sem drop_first)
sex_dummies = pd.get_dummies(df["Sex"], prefix="Sex")
# Seleciona manualmente apenas Sex_male (replicando o efeito do drop_first do treino)
if "Sex_male" not in sex_dummies.columns:
    sex_dummies["Sex_male"] = 0
df["Sex_male"] = sex_dummies["Sex_male"].astype(int)
```

A guarda `if "Sex_male" not in sex_dummies.columns` cobre o caso defensivo em que o valor não gera a coluna esperada — assume 0.

Para `Embarked`, a mesma lógica: gera todas as dummies, extrai apenas `Embarked_Q` e `Embarked_S`, e preenche com 0 se a coluna não existir (ex: payload com `"Embarked": "S"` não gera `Embarked_Q` — o `else 0` garante o valor correto).

O `FEATURE_COLUMNS` na linha 3 garante que o DataFrame final tenha as mesmas 8 colunas, na mesma ordem, que o modelo espera.

---

### 3.12 Testes locais com moto (sem AWS)

**O que foi feito:** `tests/test_local.py` usa `moto` para mockar o DynamoDB, rodando dentro de um container Docker.

**Por quê:**

- **Zero dependência de conta AWS** para rodar os testes — qualquer contribuidor pode validar sem credenciais
- **moto** é a biblioteca padrão de mocking da AWS para Python, reimplementando o DynamoDB em memória com fidelidade suficiente para testes de integração
- Rodar dentro de Docker garante o mesmo ambiente Python/sistema que o Lambda usa, eliminando a categoria de bugs "funciona na minha máquina"

O `test_local.sh` cobre 9 cenários: POST válido, GET listagem, GET por ID, GET 404, DELETE 204, DELETE 404 idempotente, listagem após deleção, POST com campos faltando e POST de passageiro masculino de 3ª classe (validação semântica da predição).

---

### 3.13 Bruno como cliente de API

**O que foi feito:** collection Bruno com 20 requests organizados em 4 pastas, com environment `prod.bru`.

**Por quê:**

O Bruno armazena as collections como arquivos `.bru` em texto plano, **versionáveis no git** — ao contrário do Postman, que usa formato JSON binário ou requer sync com a nuvem deles. Isso permite que a collection faça parte do repositório como documentação executável, rastreada junto com o código.

O `{{baseUrl}}` centralizado no `environments/prod.bru` permite trocar o endpoint (dev/prod/local) sem editar cada request.

---

## 4. Fluxo Completo de Deploy

```
1. bash scripts/download_model.sh
   └─ curl model.pkl do repo original → lambda/model.pkl

2. terraform init && terraform apply
   ├─ Cria ECR repository
   ├─ null_resource aciona scripts/build_and_push.sh:
   │   ├─ docker buildx build --platform linux/amd64
   │   │   (base: public.ecr.aws/lambda/python:3.9)
   │   │   instala numpy==1.24.4 + scikit-learn==1.1.3 + pandas==1.5.3
   │   │   copia handler.py, preprocessing.py, model.pkl
   │   └─ docker push → ECR
   ├─ Cria Lambda (image_uri = ECR:latest, 1024 MB, timeout 30s)
   ├─ Cria DynamoDB (PAY_PER_REQUEST, hash_key=id)
   ├─ Cria IAM Role (AWSLambdaBasicExecutionRole + DynamoDB CRUD)
   └─ Cria API Gateway (import OpenAPI + deployment + stage v1)

3. Output: api_url = https://<id>.execute-api.us-east-1.amazonaws.com/v1
```

---

## 5. Estrutura de Arquivos

```
case-ml/
├── openapi/
│   └── openapi.yaml          # Spec + integrações AWS (fonte única de verdade da API)
├── lambda/
│   ├── handler.py            # Dispatcher + 4 handlers
│   ├── preprocessing.py      # fillna, get_dummies, reorder de colunas
│   ├── Dockerfile            # Base ECR Lambda Python 3.9
│   ├── requirements.txt      # numpy==1.24.4, scikit-learn==1.1.3, pandas==1.5.3
│   └── model.pkl             # git-ignored, baixado via download_model.sh
├── scripts/
│   ├── download_model.sh     # Baixa model.pkl do repo original
│   ├── build_and_push.sh     # Build Docker + push ECR (usado pelo Terraform)
│   ├── build_package.sh      # Alternativa ZIP (não usada em prod)
│   └── test_local.sh         # Docker run com moto
├── tests/
│   └── test_local.py         # 9 testes de integração
├── terraform/
│   ├── main.tf               # Provider AWS
│   ├── variables.tf          # region, project_name, environment
│   ├── outputs.tf            # api_url, table_name, lambda_function_name
│   ├── dynamodb.tf           # Tabela PAY_PER_REQUEST
│   ├── lambda.tf             # ECR + IAM + null_resource build + Lambda
│   └── api_gateway.tf        # REST API import + deployment + stage + permission
└── bruno/
    ├── environments/prod.bru
    ├── POST sobreviventes/    # 5 requests (casos válidos + erro 400)
    ├── GET sobreviventes/     # 5 requests (listagem em vários estados)
    ├── GET sobreviventes {id}/   # 5 requests (lookup + 404s)
    └── DELETE sobreviventes {id}/ # 5 requests (deleção + idempotência)
```

---

## 6. Contrato da API

| Método | Rota | Corpo | Sucesso | Erro |
|--------|------|-------|---------|------|
| `POST` | `/sobreviventes` | JSON passageiro | `201` `{id, survival_probability}` | `400` campos faltando |
| `GET` | `/sobreviventes` | — | `200` array de itens | — |
| `GET` | `/sobreviventes/{id}` | — | `200` item | `404` |
| `DELETE` | `/sobreviventes/{id}` | — | `204` | `404` |

**Campos do POST:**

| Campo | Tipo | Valores |
|-------|------|---------|
| `Age` | number | idade |
| `Parch` | integer | pais/filhos a bordo |
| `SibSp` | integer | irmãos/cônjuges a bordo |
| `Fare` | number | tarifa |
| `Pclass` | integer | `1`, `2` ou `3` |
| `Sex` | string | `"male"` ou `"female"` |
| `Embarked` | string | `"C"`, `"Q"` ou `"S"` |

---

## 7. Problemas Encontrados em Produção e Resoluções

| Problema | Causa | Solução |
|----------|-------|---------|
| `ValueError: numpy.dtype size changed` | pip resolveu numpy 2.x, incompatível com ABI do scikit-learn 1.1.3 | Fixar `numpy==1.24.4` no requirements.txt |
| `INIT_REPORT Status: timeout` (10 s) | 512 MB de RAM = CPU insuficiente para carregar modelo no cold start | Aumentar `memory_size` de 512 para 1024 MB |
| Docker `pipe/dockerDesktopLinuxEngine not found` | Context Docker errado ao executar via `cmd /C bash` no Terraform | Trocar context para `desktop-linux` antes do deploy |
