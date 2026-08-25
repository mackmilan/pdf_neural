# Contexto do projeto

**Schema:** `1`
**Status:** `active`
**Última revisão:** `2026-08-25`
**Condição de revisão:** revisar após mudança de stack, contrato de API,
persistência, autenticação ou processo de build.

## Finalidade

O PDF Neural converte PDFs administrativos em HTML fiel ao desenho original,
extrai campos e imagens, detecta tabelas e disponibiliza o resultado para
preenchimento posterior por usuários autorizados.

## Stack e limites

- Backend: Python, FastAPI e Pydantic, em `backend/app/`.
- Frontend: Vue 3, TypeScript e Pinia, em `frontend/`.
- Persistência: MongoDB, encapsulado por `backend/app/db/mongo.py` e pelos
  modelos de `backend/app/db/odm.py`.
- Identidade e autorização: Keycloak/OIDC/JWT e API Keys; as regras de escopo
  usam tenant, grupo e permissões `reader`/`editor`.
- Conversão: pdfplumber, pypdf, PyMuPDF/PIL, OCR opcional e modelos neurais
  locais para campos e tabelas.
- Integração de renderização: Gotenberg pode ser usado para gerar PDF a partir
  do HTML.

## Organização das fontes

- `backend/app/main.py` registra a aplicação FastAPI e as rotas.
- `backend/app/api/`, `auth/`, `core/`, `db/`, `ml/`, `services/`, `utils/` e
  `workers/` separam responsabilidades do backend.
- `frontend/src/` contém a SPA, stores, componentes e modelos TypeScript.
- `docs/arquitetura-tecnica.md` descreve os fluxos e diagramas; `README.md`
  documenta instalação, uso e endpoints públicos.
- `static/` é resultado do build do frontend. Alterações manuais ali não são
  uma fonte durável do comportamento.

## Contratos que exigem cuidado

### Documentos e versões

`documents` mantém o ponteiro canônico e `document_versions` mantém o
histórico. Alterações de HTML ou aplicação de norma criam uma nova versão;
apenas uma versão deve ser marcada como atual no escopo do documento. Ações de
edição, exclusão e versionamento exigem autorização de editor.

As rotas de versões ficam sob `/api/documents/{document_id}/versions`. Ao mudar
esse contrato, alinhe backend, frontend, README, documentação técnica e testes.

### Segurança

Autenticação, autorização por tenant/grupo e restrições de API Key devem ser
validadas no backend. A interface pode ocultar ações sem permissão, mas não é a
autoridade para concedê-las.

### Artefatos e configuração

Configuração sensível vem do ambiente e não pertence à memória do projeto.
Modelos neurais, PDFs de treino e arquivos de saída podem ser grandes ou
gerados; confirme o escopo no `.gitignore` antes de incluí-los em uma mudança.

## Verificação de rotina

Use o ambiente local do projeto quando disponível:

```bash
.venv/bin/python -m pytest tests/ -q
npm --prefix frontend run build
```

Se uma verificação depender de MongoDB, Keycloak, Gotenberg, OCR ou outro
serviço ausente, registre o bloqueio; não transforme uma execução parcial em
evidência de funcionamento completo.
