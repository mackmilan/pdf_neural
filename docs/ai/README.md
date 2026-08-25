# Memória versionada do projeto

**Schema da memória:** `1`

**Fonte canônica:** este diretório, versionado junto com o código.

Esta memória registra contexto técnico, decisões e fatos úteis para agentes de
desenvolvimento. Ela não é memória de execução da API nem substitui o código,
os testes ou a documentação operacional. A memória local de uma ferramenta
(por exemplo, `~/.codex/memories/`) é apenas auxiliar e não é sincronizada
automaticamente com este repositório.

## Arquivos

- [`project-context.md`](project-context.md): retrato curto e revisável da
  arquitetura, contratos e comandos do projeto.
- [`decisions.md`](decisions.md): decisões arquiteturais aceitas, com motivo,
  consequências e evidências.
- [`memory-log.md`](memory-log.md): registro factual append-only para
  aprendizados que não cabem em uma decisão.
- [`adapter-prompt.md`](adapter-prompt.md): instruções portáteis para agentes
  que não carregam `AGENTS.md` ou `CLAUDE.md`.

## Precedência

Quando houver divergência, use esta ordem para investigar e atualizar a fonte
correta:

1. código atual e testes que exercem o contrato;
2. decisões ativas em `decisions.md`;
3. `project-context.md` e documentação técnica;
4. entradas históricas de `memory-log.md`.

Uma divergência não deve ser escondida. Atualize a memória no mesmo change set
quando o contrato mudou e registre no log o que foi superseded.

## Fluxo de versionamento

1. Inspecione o worktree e localize a evidência antes de escrever memória.
2. Atualize somente o arquivo que corresponde ao tipo de informação.
3. Para fatos novos, acrescente uma entrada no log com data, tipo, evidência,
   confiança e condição de revisão.
4. Para decisões, preserve a entrada anterior e crie uma nova decisão que a
   superseda quando necessário.
5. Revise o diff, execute a validação apropriada e inclua os arquivos de
   memória na mesma revisão do código relacionado.

## Compatibilidade entre provedores

| Ferramenta | Entrada | Detalhes |
| --- | --- | --- |
| OpenAI Codex | `AGENTS.md` | Bootstrap curto com links para a fonte canônica. |
| Claude Code | `CLAUDE.md` | Adaptador mínimo via `@AGENTS.md`. |
| Outros agentes | `docs/ai/adapter-prompt.md` | Prompt explícito, sem depender de descoberta automática. |

Os adaptadores devem permanecer finos. Regras de negócio, decisões e fatos
devem existir uma única vez em `docs/ai/` para evitar que OpenAI e Claude
recebam contextos diferentes.

## Segurança e privacidade

Não armazene credenciais, tokens, sessões, conteúdo de `.env`, informações
pessoais ou payloads reais de usuários. Use nomes fictícios e
`[VALOR_SENSIVEL_REDACTED]` em exemplos. Se uma evidência contiver segredo,
descreva apenas o caminho, o tipo de dado e o resultado relevante.
