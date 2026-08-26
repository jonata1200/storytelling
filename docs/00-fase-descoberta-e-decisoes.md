# Fase 00 — Descoberta técnica e decisões de integração

## Objetivo

Eliminar as maiores incertezas antes de modificar a arquitetura: confirmar como Meta e Vibes serão acessados programaticamente, quais recursos realmente estão disponíveis na conta e quais partes precisarão de API oficial ou automação de navegador.

Esta fase não altera o comportamento da aplicação.

## Por que esta fase existe

Em agosto de 2026:

- o **Meta Model API** está em preview público para Muse Spark e é o caminho preferencial para texto/raciocínio;
- **Muse Image** está disponível nos produtos Meta AI, mas a estratégia de acesso programático precisa ser confirmada para a conta/projeto;
- **Muse Video** foi anunciado pela Meta como recurso em expansão;
- o site oficial do **Vibes** oferece criação de vídeo, projetos, timeline e `ingredients`, mas deve ser confirmada a existência de uma API pública apropriada para a conta;
- não devemos depender de endpoints privados obtidos por engenharia reversa;
- automação de navegador só deve ser usada quando autorizada pelos termos e pela conta.

## Decisões que precisam sair desta fase

- `Meta text`: API oficial.
- `Meta image`: API oficial se disponível; caso contrário, browser adapter autorizado.
- `Vibes video`: API oficial se disponível; caso contrário, browser adapter autorizado.
- Não usar endpoints privados/reverse engineered.
- Não armazenar cookies/sessões no Git.
- Definir quais credenciais entram em `.env` e quais ficam em perfil persistente de navegador fora do repositório.

## Checklist — inventário do projeto

- [x] Criar branch de migração, por exemplo `feat/meta-vibes-migration`.
- [x] Registrar o SHA da `main` que servirá de baseline.
- [x] Rodar `pytest`, Ruff e mypy antes de qualquer alteração.
- [x] Salvar o resultado dos checks como baseline.
- [x] Mapear todas as referências a `ollama_cloud`.
- [x] Mapear todas as referências a `openrouter`.
- [x] Mapear `TEXT_PROVIDER`, `VIDEO_PROVIDER`, `AI_PROVIDER` e variáveis derivadas.
- [x] Mapear textos de UI que mencionam Ollama/OpenRouter.
- [x] Mapear testes e fixtures específicos dos providers legados.
- [x] Mapear custos/observabilidade que codificam nomes de providers.
- [x] Mapear diretórios de storage provider-specific, por exemplo `openrouter_videos`.
- [x] Mapear metadados provider-specific, por exemplo `openrouter_job_id`.

## Checklist — Meta Text

- [ ] Criar credencial de desenvolvimento para Meta Model API.
- [ ] Executar uma chamada mínima real de texto.
- [ ] Confirmar endpoint/base URL oficial.
- [ ] Confirmar modelo alvo.
- [ ] Confirmar compatibilidade com structured JSON necessário pelo projeto.
- [ ] Testar timeout.
- [ ] Testar erro de autenticação.
- [ ] Testar rate limit.
- [ ] Testar resposta inválida.
- [ ] Confirmar limites de contexto relevantes para roteiro.
- [ ] Registrar formato de usage/custo retornado pela API, se houver.
- [ ] Definir `META_TEXT_MODEL` padrão.

## Checklist — Meta Image / Muse Image

- [ ] Confirmar se a conta possui acesso programático oficial ao Muse Image.
- [ ] Se houver API: documentar autenticação, submit, polling/download e limites.
- [ ] Se não houver API: confirmar se automação de navegador é permitida para o uso pretendido.
- [ ] Validar geração simples `text → image`.
- [ ] Validar geração com uma referência.
- [ ] Validar geração com múltiplas referências.
- [ ] Validar edição/variação de um personagem existente.
- [ ] Validar consistência de rosto em pelo menos 3 imagens.
- [ ] Validar geração de local sem personagem.
- [ ] Validar aspect ratios necessários.
- [ ] Confirmar como salvar o arquivo original sem depender de screenshot.
- [ ] Registrar metadados retornados que possam ser úteis no `VisualReference`.
- [ ] Definir fallback operacional caso a geração visual esteja indisponível.

## Checklist — Vibes

- [ ] Confirmar se existe API oficial/documentada disponível para a conta.
- [ ] Confirmar autenticação e limites de geração.
- [ ] Validar `text → video`.
- [ ] Validar `image → video`.
- [ ] Validar uso de referência/ingredient.
- [ ] Validar criação e reutilização de personagem como ingredient.
- [ ] Validar criação e reutilização de local/estilo como ingredient.
- [ ] Validar duração suportada.
- [ ] Validar aspect ratio 9:16.
- [ ] Validar áudio ligado/desligado.
- [ ] Validar download do arquivo final.
- [ ] Confirmar se existe operação assíncrona/polling.
- [ ] Confirmar como identificar uma geração de forma estável.
- [ ] Confirmar política de concorrência e rate limits.
- [ ] Se não houver API: confirmar autorização para browser automation.
- [ ] Se browser automation for usada: não usar endpoints privados nem capturar tokens internos para chamar APIs não documentadas.

## Checklist — browser automation, se necessária

- [ ] Escolher Playwright como mecanismo padrão.
- [ ] Criar perfil persistente separado por serviço.
- [x] Colocar `runtime/browser_profiles/` no `.gitignore`.
- [ ] Nunca salvar cookie/token de sessão em `.env.example`.
- [ ] Implementar login manual inicial quando necessário.
- [ ] Implementar detecção de sessão expirada.
- [ ] Implementar captura de screenshot apenas para diagnóstico.
- [ ] Implementar timeout de navegação.
- [ ] Implementar retry limitado.
- [ ] Implementar lock para impedir dois workers usando o mesmo perfil simultaneamente.
- [ ] Definir como baixar o arquivo gerado pela interface.
- [ ] Definir evidência de que a geração realmente terminou.
- [ ] Definir comportamento quando a UI mudar.

## Artefatos de saída

- [x] Criar `docs/integrations/meta.md`.
- [x] Criar `docs/integrations/vibes.md`.
- [x] Criar uma tabela `capability → integration_mode`.
- [ ] Registrar modelos escolhidos e limites conhecidos.
- [x] Registrar riscos de cada integração.
- [x] Registrar decisão de API vs navegador em ADR, por exemplo `docs/adr/001-meta-vibes-integration.md`.

## Critérios de aceite

- [ ] Existe um caminho técnico validado para Meta Text.
- [ ] Existe um caminho técnico validado para Meta Image ou um fallback autorizado.
- [ ] Existe um caminho técnico validado para Vibes Video ou um fallback autorizado.
- [ ] Nenhuma solução depende de engenharia reversa de endpoints privados.
- [ ] As credenciais e sessões têm estratégia segura definida.
- [ ] Os checks do projeto continuam exatamente como no baseline.
- [ ] A equipe consegue responder, antes da Fase 01: "como cada provider será chamado e como seu resultado será recuperado?".

## Não fazer nesta fase

- [ ] Não apagar Ollama/OpenRouter.
- [ ] Não mudar banco.
- [ ] Não alterar prompts narrativos.
- [ ] Não reescrever NiceGUI.
- [ ] Não adicionar Celery/Temporal.
- [ ] Não mudar o pipeline de produção.
