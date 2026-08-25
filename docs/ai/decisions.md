# Decisões arquiteturais da memória

As decisões abaixo são versionadas junto com o projeto. Uma decisão antiga não
é apagada quando deixa de valer: uma nova entrada deve indicar qual decisão ela
supersede.

## ADR-001 — Fonte canônica única em Markdown

- **Status:** accepted
- **Data:** `2026-08-25`
- **Supersedes:** none
- **Decisão:** manter o contexto compartilhado em `docs/ai/`, com
  `AGENTS.md` como bootstrap e arquivos separados para contexto, decisões e
  fatos.
- **Motivo:** Markdown é revisável em Git, legível por pessoas e carregável por
  diferentes agentes sem depender de um serviço externo ou de uma base local.
- **Consequências:** mudanças de contrato devem atualizar a memória no mesmo
  change set; a memória local de cada ferramenta não é considerada fonte de
  verdade.
- **Evidência:** `README.md`, `docs/arquitetura-tecnica.md` e a estrutura criada
  em `docs/ai/`.

## ADR-002 — Adaptadores finos para OpenAI e Claude

- **Status:** accepted
- **Data:** `2026-08-25`
- **Supersedes:** none
- **Decisão:** OpenAI Codex entra por `AGENTS.md`; Claude Code entra por
  `CLAUDE.md` com `@AGENTS.md`. As regras detalhadas permanecem somente em
  `docs/ai/`.
- **Motivo:** evita deriva entre provedores e permite que cada ferramenta use
  seu mecanismo nativo de descoberta.
- **Consequências:** alterações de instrução devem ser feitas primeiro na fonte
  canônica; `CLAUDE.md` não deve receber uma cópia independente.
- **Evidência:** `AGENTS.md` e `CLAUDE.md`.

## ADR-003 — Memória sem segredos ou dados reais

- **Status:** accepted
- **Data:** `2026-08-25`
- **Supersedes:** none
- **Decisão:** não persistir credenciais, tokens, sessões, valores de `.env`,
  dados pessoais ou payloads reais. Usar `[VALOR_SENSIVEL_REDACTED]` quando a
  descrição do tipo de valor for necessária.
- **Motivo:** a memória é versionada e pode ser lida por várias ferramentas,
  clones e colaboradores.
- **Consequências:** evidências devem apontar para arquivos, testes e comandos,
  sem copiar valores sensíveis.
- **Evidência:** `.env` é configuração local ignorada; regras de segurança do
  backend estão descritas em `docs/arquitetura-tecnica.md`.

## ADR-004 — Contexto factual separado de decisões

- **Status:** accepted
- **Data:** `2026-08-25`
- **Supersedes:** none
- **Decisão:** fatos atuais ficam em `project-context.md`, decisões ficam em
  `decisions.md` e aprendizados append-only ficam em `memory-log.md`.
- **Motivo:** cada tipo tem ciclo de revisão diferente e a separação torna
  conflitos e obsolescência visíveis.
- **Consequências:** um fato que mudar deve atualizar o contexto e registrar a
  transição no log; uma escolha de design deve ganhar um ADR.
- **Evidência:** `docs/ai/README.md`.
