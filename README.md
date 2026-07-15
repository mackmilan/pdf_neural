# PDF Neural - PDF para HTML e mapeamento JSON

Converte PDFs em uma representacao HTML fiel, sem usar uma imagem da pagina como fundo.
O conversor recria texto, linhas, retangulos e imagens como elementos HTML/SVG. Os
campos detectados nao viram formularios HTML: seu mapeamento e gravado separadamente
em `fields.json` para permitir o preenchimento posterior do PDF.

## O que ele faz

- le campos AcroForm nativos;
- infere campos visuais a partir de linhas, caixas e rotulos;
- infere tipos (`text`, `date`, `email`, `tel`, `number`, `checkbox` e `textarea`);
- extrai imagens e logotipos para a pasta `assets/`;
- detecta grades de tabelas, celulas mescladas e celulas vazias destinadas a valores;
- gera `index.html` sem campos de formulario e `fields.json` com nome, tipo, pagina,
  coordenadas e dimensoes de cada campo, alem de `tables.json` com a estrutura de
  linhas, colunas, celulas e seus textos;
- inclui uma interface local para enviar o PDF e baixar o resultado em ZIP.

## Instalacao e uso

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

O frontend (Vue 3 + TypeScript, em `frontend/`) precisa ser instalado uma vez com
`npm install --prefix frontend`. Em desenvolvimento, rode o backend Python e o
Vite dev server juntos com:

```bash
./scripts/dev.sh
```

Isso inicia `python app.py` (porta 8000) e `npm run dev` (porta 5173, com proxy
para `/api`, `/auth`, `/jobs`, `/docs` e `/openapi.json` apontando para o
backend). Para gerar os estaticos de producao (servidos pelo proprio
`app.py` a partir de `static/`):

```bash
npm --prefix frontend run build
```

## Detector neural de tabelas

O detector neural e opcional e complementa a deteccao geometrica existente. Ele
usa uma U-Net compacta para segmentar as regioes de tabela e aprende com mascaras
especificas das linhas da grade. Apos localizar a regiao, a cabeca estrutural
recupera linhas e colunas; em PDFs vetoriais preserva a cor e espessura originais,
e em documentos digitalizados estima ambas diretamente dos pixels.

```bash
pip install -r requirements-ml.txt

# Aceita arquivos e/ou pastas; procura PDFs recursivamente nas pastas.
python neural_table_detector.py prepare tmp/pdfs -o data/tables
python neural_table_detector.py train data/tables -o models/table_detector.pt --epochs 30
python neural_table_detector.py detect documento.pdf \
  --model models/table_detector.pt -o output/neural-tables.json
```

Para corrigir falsos positivos junto as bordas sem descartar o aprendizado anterior,
use ajuste fino. O treino pondera como negativos os pixels imediatamente externos a
cada tabela, evitando incluir campos proximos como `Data` e `Assinatura`:

```bash
python neural_table_detector.py train data/uepg/tables \
  --resume models/uepg_table_detector.pt \
  -o models/uepg_table_detector.pt --epochs 10 --learning-rate 0.0002
```

Um modelo treinado com os documentos publicos do Mestrado em Direito da UEPG
esta disponivel em `models/uepg_table_detector.pt`. O corpus correspondente fica
em `data/uepg/` (20 PDFs, 65 paginas, 25 paginas positivas e 40 negativas):

```bash
python neural_table_detector.py detect documento.pdf \
  --model models/uepg_table_detector.pt -o output/neural-tables.json
```

Cada resultado contem pagina, coordenadas PDF, dimensoes, confianca,
`row_count`, `column_count`, `lines` (coordenadas, espessura e cor) e
`source: "neural"`. Um unico PDF permite validar o fluxo, mas um modelo robusto
normalmente exige dezenas ou centenas de paginas variadas, incluindo paginas sem
tabelas. Revise as mascaras em `data/tables/masks/` e
`data/tables/grid-masks/` antes do treino; elas sao os rotulos aprendidos pela rede.

## Detector neural de campos

O preparo reconhece AcroForms, linhas vetoriais e campos textuais como
`Data: ____`. Durante o treino tambem sao sintetizados exemplos de data no rodape,
o que cobre documentos digitalizados sem camada de texto. Para ajustar o modelo
existente sem perder o aprendizado anterior:

```bash
python neural_field_detector.py prepare data/uepg/pdfs -o data/fields_uepg_v6
python neural_field_detector.py train data/fields_uepg_v6 \
  --resume models/field_detector.pt \
  -o models/field_detector.pt --epochs 10 --learning-rate 0.0002
```

Abra `http://127.0.0.1:8000`. Na interface, envie um arquivo local ou informe uma
URL publica HTTP/HTTPS que aponte para o PDF. Downloads remotos possuem limite de
30 MB e enderecos locais ou de rede privada sao bloqueados.

A interface executa automaticamente o modelo `models/uepg_table_detector.pt` e
mostra as grades encontradas em **Tabelas - rede neural**. O arquivo
`neural-tables.json` tambem e incluido no ZIP. Na previa HTML, linhas e colunas sao
renderizadas nas coordenadas detectadas usando a cor dos tracos do documento de
origem. Para trocar o checkpoint ou ajustar a sensibilidade:

```bash
TABLE_MODEL=models/uepg_table_detector.pt \
NEURAL_THRESHOLD=0.7 \
NEURAL_MIN_CONFIDENCE=0.65 \
python app.py
```

Por padrao, uma falha neural e registrada e a conversao geometrica continua. Use
`NEURAL_REQUIRED=true` quando a requisicao inteira deva falhar caso o modelo nao
possa ser executado.

A documentacao interativa Swagger fica em `http://127.0.0.1:8000/docs` e a
especificacao OpenAPI 3.1 em `http://127.0.0.1:8000/openapi.json`.

## Autenticação e autorização

A API valida access tokens JWT emitidos pelo Keycloak. O Keycloak mantém
identidade, credenciais e a role administrativa `pdf-admin`; o MongoDB mantém os
acessos de cada `sub` a tenants e grupos, com permissão `reader` ou `editor`.

Ao abrir `http://localhost:8000`, a aplicação mostra somente a tela de login.
O botão **Entrar com Keycloak** usa Authorization Code com PKCE; após o retorno,
os tokens ficam apenas em `sessionStorage`, são renovados automaticamente e todas
as chamadas à API recebem o header Bearer. O botão **Sair** encerra também a sessão
no Keycloak. O conteúdo da aplicação nunca é exibido sem uma sessão válida.

Com o Keycloak local em `http://localhost:8080` e o administrador `admin/admin`,
configure o realm, o client público e um administrador inicial da aplicação:

```bash
python scripts/configure_keycloak.py --app-password admin
```

O script usa a porta `PORT` do `.env` para autorizar os callbacks da aplicação.
Se você acessar a aplicação por outra origem, informe-a explicitamente:

```bash
python scripts/configure_keycloak.py --app-password admin \
  --app-url http://localhost:8002 \
  --app-url http://127.0.0.1:8002
```

O script cria o realm `pdf-neural`, o client público `pdf-neural-api`, a role
`pdf-admin` e o usuário inicial `pdf-admin/admin`. Troque essa senha antes de usar
fora do ambiente local.

Configure o arquivo `.env` da API com os valores básicos:

```env
AUTH_ENABLED=true
KEYCLOAK_ISSUER=http://localhost:8080/realms/pdf-neural
KEYCLOAK_AUDIENCE=pdf-neural-api
KEYCLOAK_ADMIN_ROLE=pdf-admin
KEYCLOAK_ADMIN_URL=http://localhost:8080/admin/realms/pdf-neural
```

Para a API consultar roles de Service Accounts no Keycloak, crie também um client
confidencial administrativo:

1. Acesse `http://localhost:8080/admin` com `admin/admin`.
2. Entre no realm `pdf-neural`.
3. Crie o client `pdf-neural-admin`.
4. Habilite `Client authentication` e `Service accounts roles`.
5. Desabilite fluxos de usuário como `Standard flow` e `Direct access grants`.
6. Em `Service account roles`, atribua as roles do client `realm-management`:
   `view-clients`, `view-users`, `query-clients` e `query-users`.
7. Copie o secret em `Credentials` e complete o `.env`:

```env
KEYCLOAK_ADMIN_CLIENT_ID=pdf-neural-admin
KEYCLOAK_ADMIN_CLIENT_SECRET=secret_do_client_pdf_neural_admin
```

Reinicie a API sempre que alterar o `.env`. Obtenha um token de desenvolvimento:

```bash
TOKEN=$(curl -s -X POST \
  http://localhost:8080/realms/pdf-neural/protocol/openid-connect/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'client_id=pdf-neural-api' -d 'grant_type=password' \
  -d 'username=pdf-admin' -d 'password=admin' | jq -r .access_token)

curl http://localhost:8000/api/me -H "Authorization: Bearer $TOKEN"
```

### API Key com Keycloak

Para integrações automatizadas, você pode usar uma API Key em vez de tokens JWT. As chaves são vinculadas a um `client_id` e podem ser restritas a um tenant ou grupo específico.
Ao autenticar com uma API Key, a aplicação busca no Keycloak as roles de Realm atribuídas ao Service Account do client associado à chave.
Mantenha o client `pdf-neural-api` como público para o login do navegador; use outro client confidencial para API Keys.

Crie um client confidencial específico para integrações, por exemplo `pdf-neural-api-key`:

1. No realm `pdf-neural`, crie o client `pdf-neural-api-key`.
2. Habilite `Client authentication` e `Service accounts roles`.
3. Desabilite `Standard flow` e `Direct access grants`, pois esse client não é usado pelo navegador.
4. Em `Service account roles`, atribua a role de Realm `pdf-admin` se a chave deve ter acesso administrativo.
5. Se preferir acesso sem `pdf-admin`, não atribua a role e crie registros em `user_access` para o subject `client:pdf-neural-api-key`.

Gere a chave usando o mesmo `client_id` do client confidencial:

```bash
python3 -c "from database import Database; print(Database().create_api_key('pdf-neural-api-key', 'Chave de Integracao', 'TENANT_ID', 'GROUP_ID'))"
```

Exemplo de validação:

```bash
curl http://localhost:8000/api/me -H "X-API-Key: ak_sua_chave_aqui"

curl 'http://localhost:8000/api/documents?tenant_id=TENANT_ID&group_id=GROUP_ID' \
  -H "X-API-Key: ak_sua_chave_aqui"
```

As restrições de tenant e grupo gravadas na API Key limitam o escopo permitido, mas não substituem autorização. A requisição é liberada quando o Service Account tem `pdf-admin` ou quando existe acesso em `user_access` para `client:<client_id>`. Uma chave restrita a outro tenant ou grupo recebe `403`.

Todas as rotas de API e as prévias em `/jobs/...` exigem autenticação. A raiz,
o Swagger e o OpenAPI permanecem públicos. Para conceder acesso a um usuário,
copie seu claim `sub` e, usando um token com a role `pdf-admin`, execute:

```bash
curl -X PUT http://localhost:8000/api/users/KEYCLOAK_SUB/access \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tenant_id":"TENANT_ID","permission":"editor","username":"maria"}'
```

Um acesso sem `group_id` vale para todo o tenant. Um acesso com `group_id` vale
somente para aquele grupo. `reader` permite consultas e `editor` também permite
converter, editar e excluir documentos. Criação de tenants, grupos, categorias e gestão de
acessos exigem `pdf-admin`.

As variáveis relevantes estão em `.env.example`. Em Docker Desktop, mantenha
`KEYCLOAK_ISSUER` igual ao issuer presente no token e use `KEYCLOAK_JWKS_URL` com
`host.docker.internal` para a API conseguir buscar as chaves públicas.

Para o Keycloak remoto configurado para este projeto, use os valores de
`config/keycloak.remote.env.example`. As credenciais administrativas do Keycloak
servem apenas ao script de provisionamento e não devem ser copiadas para a API.
Ao publicar a aplicação em outro domínio, execute novamente o provisionamento
com `--app-url https://dominio-da-aplicacao` para autorizar callback e logout.

Uso direto pela linha de comando:

```bash
python converter.py documento.pdf -o output/documento
```

O resultado fica autocontido na pasta escolhida. O PDF original nao e incorporado ao HTML.

## API assincrona com callback

Envie as URLs do PDF e do callback em JSON. Ambas precisam ser publicas; enderecos
locais e privados sao recusados. O campo `reference` e opcional e e devolvido sem
alteracoes para permitir a correlacao com o sistema de origem.

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "pdf_url": "https://exemplo.com/formulario.pdf",
    "callback_url": "https://sistema.exemplo.com/callbacks/pdf",
    "reference": "documento-123"
  }'
```

A API responde imediatamente com HTTP `202`:

```json
{
  "job_id": "9a46c0ef8db14a119a006f239683ef9f",
  "reference": "documento-123",
  "status": "queued",
  "status_url": "https://pdf.exemplo.com/api/jobs/9a46c0ef8db14a119a006f239683ef9f"
}
```

## Documentos e versões

O conteúdo binário do PDF é identificado por SHA-256. A primeira conversão cria
o documento canônico e a versão 1; novas conversões do mesmo arquivo acrescentam
versões sem duplicar o documento. Apenas uma versão possui `is_current: true`.
Versões anteriores podem ser marcadas como `deprecated`; elas continuam acessíveis
no histórico, mas não podem ser definidas como padrão.

```bash
# Versão atual (tenant obrigatório; grupo opcional)
curl 'http://localhost:8000/api/documents/{document_id}?tenant_id={tenant_id}&group_id={group_id}'

# Exemplo com API Key
curl 'http://localhost:8000/api/documents/{document_id}?tenant_id={tenant_id}' \
  -H "X-API-Key: ak_sua_chave_aqui"

# Histórico de versões
curl 'http://localhost:8000/api/documents/{document_id}/versions?tenant_id={tenant_id}'

# Versão específica
curl 'http://localhost:8000/api/documents/{document_id}/versions/2?tenant_id={tenant_id}'

# Marcar como deprecated (use DELETE na mesma URL para restaurar)
curl -X PUT 'http://localhost:8000/api/documents/{document_id}/versions/2/deprecated?tenant_id={tenant_id}'
```

O retorno da conversão inclui `document_id`, `job_id` e `version`. Links antigos
baseados em `job_id` continuam aceitos.

### Página de preenchimento

Um documento convertido pode ser aberto diretamente em
`/documento/{document_id}` (o `job_id` também é aceito). A página exige autenticação
por e-mail e senha no Keycloak, carrega o documento usando apenas o identificador
presente na URL e aplica as mesmas permissões de tenant/grupo da API.

Ao clicar em **Salvar resultado**, os valores preenchidos, a versão do documento e
a identidade do usuário são gravados na collection MongoDB
`document_submissions`. Cada envio recebe um `submission_id` próprio.

## Tenants, grupos e categorias

Tenants representam qualquer organização, conta ou domínio de dados. Cada tenant
pode possuir grupos com nomes livres; os grupos podem representar departamentos,
projetos, equipes, categorias ou qualquer outra divisão necessária. O sistema não
impõe significado de negócio a esses nomes.

```bash
# Criar tenant
curl -X POST http://localhost:8000/api/tenants \
  -H 'Content-Type: application/json' -d '{"name":"Organização Alfa"}'

# Criar grupo no tenant
curl -X POST http://localhost:8000/api/tenants/{tenant_id}/groups \
  -H 'Content-Type: application/json' -d '{"name":"Projeto Norte"}'

# Filtrar o histórico pelo contexto
curl 'http://localhost:8000/api/documents?tenant_id={tenant_id}&group_id={group_id}'

# Criar e listar categorias de documentos vinculadas ao grupo
curl -X POST http://localhost:8000/api/tenants/{tenant_id}/groups/{group_id}/categories \
  -H 'Content-Type: application/json' -d '{"name":"Contrato"}'
curl http://localhost:8000/api/tenants/{tenant_id}/groups/{group_id}/categories

# Filtrar e reclassificar documentos (use null para remover a categoria)
curl 'http://localhost:8000/api/documents?tenant_id={tenant_id}&category_id={category_id}'
curl -X PUT 'http://localhost:8000/api/documents/{document_id}/category?tenant_id={tenant_id}' \
  -H 'Content-Type: application/json' -d '{"category_id":"CATEGORY_ID"}'
```

As conversões síncronas aceitam `tenant_id`, `group_id` e `category_id` no multipart. Jobs
assíncronos aceitam os mesmos campos no JSON e exigem `tenant_id`. `group_id` e
`category_id` são opcionais; a categoria, quando informada, precisa pertencer ao `group_id`. Todas as consultas de
documentos e jobs exigem `tenant_id`; grupo e categoria podem restringir a busca. A identidade
canônica do documento é isolada por tenant e grupo, portanto o mesmo PDF pode ter
históricos de versão independentes em contextos diferentes.

Ao terminar, o callback recebe um `POST application/json`. Em caso de sucesso, o
corpo contem `status: "completed"` e `result` com `fields`, `tables`, `preview_url`
e `download_url`. Em caso de erro, contem `status: "failed"` e `error`. O envio do
callback e tentado ate tres vezes. O estado tambem pode ser consultado com
`GET /api/jobs/{job_id}`.

Em producao, configure a URL externa usada nos links e a quantidade de conversoes
simultaneas:

```bash
PUBLIC_BASE_URL=https://pdf.exemplo.com PDF_WORKERS=4 python app.py
```

## Deploy com Coolify

Crie um recurso do tipo **Docker Compose** apontando para este repositorio. O servico
publica a porta `8000`, possui healthcheck e salva os jobs no volume persistente
`pdf-neural-data`.

Configure no Coolify:

```env
PUBLIC_BASE_URL=https://pdf.exemplo.com
PDF_WORKERS=2
```

Associe o dominio do recurso a porta interna `8000`. O `docker-compose.yml` usa
`expose` (sem publicar a porta no host) de propósito: o Coolify roda apenas esse
arquivo e acessa o servico diretamente pela rede Docker, entao publicar a porta
arriscaria colidir com outro servico já usando 8000 na mesma VPS. `PUBLIC_BASE_URL`
deve ser a URL publica sem barra no final, para que callbacks e links de resultados
usem o dominio correto.

A imagem builda o frontend (Vue 3 + TypeScript em `frontend/`) em um estagio
separado e copia o resultado para `static/`, que o backend serve diretamente —
nao e necessario rodar `npm` fora do container.

Para executar localmente com acesso via navegador, use `docker-compose.override.yml`
(ja incluido no repositorio e aplicado automaticamente pelo `docker compose up` quando
nenhum `-f` extra e passado — e por isso ignorado pelo Coolify, que especifica o
arquivo explicitamente). Ele publica a porta em `http://localhost:8000`; use
`HOST_PORT=9000 docker compose up` para publicar em outra porta caso a 8000 esteja
ocupada:

```bash
docker compose up --build
```

## Limites conhecidos

PDF e uma linguagem de desenho, nao de layout. Textos e formas sao reconstruidos por
coordenadas absolutas. Fontes nao instaladas no navegador recebem uma alternativa
compativel. Curvas complexas sao preservadas como SVG; isso continua sendo HTML vetorial,
nao uma captura da pagina. PDFs digitalizados precisam de OCR, que nao faz parte desta
primeira versao.
