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
