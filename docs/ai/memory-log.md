# Registro factual da memória

**Schema:** `1`

**Regra:** append-only. Entradas antigas permanecem para auditoria; fatos
superados recebem uma nova entrada que aponta para a evidência atual.
Segredos devem ser omitidos ou representados por
`[VALOR_SENSIVEL_REDACTED]`.

## 2026-08-25 — MEM-001: memória canônica versionada

- **type:** decision
- **status:** active
- **evidence:** `AGENTS.md`, `CLAUDE.md`, `docs/ai/README.md`
- **confidence:** high
- **review_when:** mudar a estratégia de instruções compartilhadas entre agentes
- **summary:** o projeto usa `docs/ai/` como fonte canônica, com adaptadores
  finos para OpenAI Codex e Claude Code.

## 2026-08-25 — MEM-002: arquitetura full-stack atual

- **type:** fact
- **status:** active
- **evidence:** `README.md`, `docs/arquitetura-tecnica.md`,
  `backend/app/main.py`, `frontend/package.json`
- **confidence:** high
- **review_when:** alterar framework, persistência, autenticação ou build
- **summary:** o backend é FastAPI/Python, o frontend é Vue 3/TypeScript, a
  persistência é MongoDB e a identidade usa Keycloak/OIDC.

## 2026-08-25 — MEM-003: versionamento de documentos

- **type:** contract
- **status:** active
- **evidence:** `docs/arquitetura-tecnica.md` seção “Processo: edição,
  versionamento e publicação”; `backend/app/db/mongo.py`;
  `backend/app/main.py`
- **confidence:** high
- **review_when:** alterar `documents`, `document_versions` ou suas rotas
- **summary:** `documents` aponta para o estado canônico e
  `document_versions` guarda o histórico; edições relevantes geram versões e
  somente usuários com permissão `editor` podem versionar.

## 2026-08-25 — MEM-004: dados sensíveis fora da memória

- **type:** policy
- **status:** active
- **evidence:** `.gitignore`, `.env.example`, `backend/app/auth/service.py`,
  `docs/ai/README.md`
- **confidence:** high
- **review_when:** mudar autenticação, configuração ou política de privacidade
- **summary:** credenciais, tokens, sessões, valores reais de `.env` e dados
  pessoais não entram em arquivos versionados de memória.

## 2026-08-25 — MEM-005: listagem administrativa de usuários por tenant

- **type:** contract
- **status:** active
- **evidence:** `backend/app/main.py`, `backend/app/db/mongo.py`,
  `frontend/src/components/UserAccessManager.vue`,
  `tests/test_fastapi_migration.py`, `tests/test_api.py`
- **confidence:** high
- **review_when:** alterar a tela `/usuarios`, o escopo de `user_access` ou a
  rota `/api/users/access`
- **summary:** a tela administrativa envia o `tenant_id` selecionado para
  `/api/users/access`; o backend filtra os vínculos no MongoDB e recarrega a
  lista quando o tenant do contexto muda. Sem filtro, a rota mantém o
  comportamento compatível de listar todos os vínculos para administradores.

## 2026-08-25 — MEM-006: campos textuais e moldura de formulário

- **type:** fact
- **status:** active
- **evidence:** `backend/app/services/converter.py`,
  `backend/app/ml/fields.py`, `backend/app/ml/tables.py`,
  `data/fields_declaracao_uniao_estavel/manifest.json`,
  `data/tables_declaracao_uniao_estavel/manifest.json`,
  `tests/test_neural_field_detector.py`, `tests/test_neural_table_detector.py`
- **confidence:** high
- **review_when:** alterar a extração de underscores, a classificação de
  molduras de página ou o formato dos datasets neurais
- **summary:** formulários Word sem AcroForm podem representar campos apenas
  com underscores; a preparação agora os rotula, preserva componentes de data
  e ignora molduras externas de página como tabelas/células. O documento de
  união estável usado na evidência não contém tabela de dados: sua amostra de
  tabela é exclusivamente hard-negative e não deve ser usada sozinha para
  promover um novo modelo positivo de tabelas.

## 2026-08-25 — MEM-007: fidelidade visual na exportação HTML/PDF

- **type:** fact
- **status:** active
- **evidence:** `backend/app/services/converter.py`,
  `frontend/src/components/PdfPreview.vue`, `tests/test_converter.py`,
  `output/pdf/Declaracao_de_Uniao_Estavel_rev00_alinhado.pdf`
- **confidence:** high
- **review_when:** alterar a renderização de retângulos, fontes PDF ou o fluxo
  de exportação HTML para Gotenberg
- **summary:** retângulos preenchidos com `stroke=false` não podem receber
  borda CSS, pois o PDF original usa preenchimentos brancos no bloco legal e
  preenchimentos finos na moldura. Nomes de fonte com sufixos `Bold`/`Italic`
  devem ser convertidos em família, peso e estilo CSS. As âncoras de campos são
  úteis na prévia, mas ficam ocultas em `@media print` para o PDF exportado
  preservar o desenho original.
