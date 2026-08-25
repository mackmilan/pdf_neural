# Prompt portátil para agentes

Use este texto quando a ferramenta não descobrir `AGENTS.md` ou `CLAUDE.md`:

> Você está trabalhando no projeto PDF Neural. Leia `docs/ai/README.md`,
> `docs/ai/project-context.md` e as decisões relevantes em
> `docs/ai/decisions.md` antes de alterar arquivos. Preserve o worktree,
> confirme contratos no código e nos testes e mantenha backend, frontend,
> documentação e testes alinhados. Registre fatos novos em
> `docs/ai/memory-log.md` com `type`, `evidence`, `confidence` e `review_when`.
> Nunca grave tokens, senhas, cookies, valores de `.env`, dados pessoais ou
> payloads reais; use `[VALOR_SENSIVEL_REDACTED]` para descrever um valor sem
> armazená-lo. Ao concluir, informe arquivos alterados, verificações aprovadas
> e bloqueios ambientais separadamente.

Este prompt é um adaptador de entrada, não uma segunda fonte de decisões. Se
ele divergir da documentação canônica, `docs/ai/` tem precedência.
