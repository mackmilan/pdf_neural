# PDF Neural — instruções para agentes

Este arquivo é o bootstrap versionado para agentes de desenvolvimento. A
memória detalhada e compartilhada fica em [`docs/ai/`](docs/ai/README.md).

## Antes de alterar o projeto

1. Leia [`docs/ai/README.md`](docs/ai/README.md),
   [`docs/ai/project-context.md`](docs/ai/project-context.md) e as decisões
   relevantes em [`docs/ai/decisions.md`](docs/ai/decisions.md).
2. Confira `git status --short` e preserve alterações preexistentes.
3. Confirme o contrato no código e nos testes atuais antes de alterar uma
   documentação histórica.

## Regras do projeto

- O backend atual fica em `backend/app/` e usa FastAPI, MongoDB e Keycloak.
- O frontend fica em `frontend/` e é Vue 3 + TypeScript; `static/` é artefato
  gerado e não deve ser tratado como fonte.
- Mantenha autenticação, autorização por tenant/grupo e versionamento de
  documentos alinhados entre backend, frontend, documentação e testes.
- Prefira mudanças pequenas e verificáveis. Relate separadamente verificações
  aprovadas, bloqueios ambientais e validações que não foram executadas.
- Não faça commit, push, deploy, reset ou exclusão ampla sem solicitação
  explícita.

## Higiene da memória

- Registre somente conhecimento de projeto que seja verificável e reutilizável.
- O [`memory-log.md`](docs/ai/memory-log.md) é append-only: para corrigir um
  fato, registre uma nova entrada que o substitua e indique a evidência.
- Toda entrada precisa informar `type`, `evidence`, `confidence` e
  `review_when`.
- Nunca grave tokens, senhas, cookies, valores de `.env`, dados pessoais ou
  outros segredos. Use `[VALOR_SENSIVEL_REDACTED]` quando for necessário
  descrever um valor sem armazená-lo.

## Compatibilidade com agentes

- OpenAI Codex lê este `AGENTS.md` como instrução de projeto.
- Claude Code usa o [`CLAUDE.md`](CLAUDE.md), que aponta para este mesmo
  bootstrap; não mantenha uma segunda cópia das regras.
- Para ferramentas que não carregam esses arquivos automaticamente, use o
  prompt portátil em [`docs/ai/adapter-prompt.md`](docs/ai/adapter-prompt.md).
