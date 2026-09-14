# Browser automation — autorização Vibes/Meta

## Visão geral

A automação de browser para o Vibes (geração de vídeo) e Meta (geração
de imagem) usa Playwright com perfis persistentes em
`runtime/browser_profiles/{meta,vibes}/`. Cada perfil guarda cookies e
sessão para que o bridge não precise logar de novo a cada job.

Pontos críticos do fluxo:

1. **Autorizar** (tela de Ajustes): abre o navegador no perfil do
   provider para o usuário autenticar manualmente.
2. **Gerar**: o bridge Playwright abre o mesmo perfil, faz a submissão,
   fecha o Chrome.
3. **Sondar** (poll): reabre o projeto persistido e baixa o resultado.

## Proteções implementadas

### 1. Detecção de Chrome zombie

Sintoma: `chromium.launchPersistentContext` lança
`browserType.launchPersistentContext: Target page, context or browser
has been closed`. Causa: o Chrome nativo detecta que já existe outra
instância segurando o lock do `--user-data-dir=<profile>` e mata a nova
instância imediatamente. Isso acontece tipicamente quando um job
anterior deixou Chrome zombie (fechamento parcial, crash do Playwright,
PID órfão segurando o lock).

Correção: `killZombieChromeForProfile(profilePath)` em
`scripts/meta_browser_bridge.mjs` lista Chrome via `wmic`, filtra por
`--user-data-dir=<profile>`, mata PIDs via `taskkill /F` e aguarda 500ms
para o lock file ser liberado pelo Windows. A função é invocada no
início de `persistentPage` antes de `launchPersistentContext`.

Falhas de detecção (wmic/taskkill ausentes) são fail-open: retorna `[]`
e deixa a abertura seguir, com o erro original se repetir.

### 2. Conflito cross-profile (Autorizar Meta com Chrome Vibes aberto)

Sintoma: clicar em "Autorizar Vibes" abre duas janelas — uma com Vibes,
outra com Meta. O usuário não sabe qual é a nova e qual é a antiga.

Causa: a UI não checava se já havia Chrome rodando com o perfil do
**outro** provider.

Correção: `_any_project_chrome_in_use(meta_path, vibes_path)` em
`app/providers/browser_bridge.py` retorna o nome do provider cujo
profile está em uso. As closures `authorize_meta` e `authorize_vibes`
em `app/ui/routes/settings_page.py` consultam antes de lançar a
console; se o **outro** profile já está em uso, exibem notificação
bloqueante sem abrir nova instância.

### 3. Loop de autorização (Chrome duplicado reabrindo)

Sintoma: o Playwright detectava Chrome já aberto no perfil e morria
imediatamente (`<kill>`), fazendo o usuário reabrir autorização em loop.

Correção: `_iter_chrome_processes()` em
`app/providers/browser_bridge.py` retorna PIDs do Chrome rodando (via
PowerShell `Get-CimInstance Win32_Process`) para verificação antes de
autorizar.

## Fluxo esperado (geração de vídeo Vibes)

1. Usuário clica "Gerar vídeo" na UI para um segmento com frame.
2. UI chama `create_or_get_media_job` (worker recebe job).
3. Worker invoca `submitVideo` no bridge Node:
   - `killZombieChromeForProfile(vibes_profile)` — mata zombies.
   - `persistentPage(vibes_profile, headless=false)`.
   - `chromium.launchPersistentContext` — abre Chrome novo no perfil.
   - Vai para `vibes.ai/<project>` (URL persistida) ou cria projeto novo.
   - Faz upload do frame inicial, configura duração, submete prompt.
   - Salva checkpoint do projeto.
   - `closePersistentSession(context)` — fecha Chrome imediatamente.
4. Worker faz poll com `pollVideo` em intervalos até o vídeo ficar
   pronto; cada poll reabre o mesmo projeto persistido.

Se o step 3 falhar, o worker chama `mark_job_failed` e emite
`OperationalEventCreate` com `message=str(exc)`. Mensagens grandes
(Call log do Playwright com 5000+ chars) são truncadas em
`_safe_event_message` para caber em `OperationalEventCreate.message`
(max 2000).

## Logs e diagnóstico

- `runtime/uvicorn.out.log` — HTTP requests.
- `runtime/uvicorn.err.log` — startup, observability, exceptions do app.
- `runtime/worker.out.log` — INFO logs do worker (`video_job_started`,
  `video_job_succeeded`, etc).
- `runtime/worker.err.log` — stderr do worker, incluindo tracebacks.

Atalho: `Get-Content runtime/worker.err.log -Tail 50 -Wait` (PowerShell)
ou `tail -F runtime/worker.err.log` (bash) para acompanhar em tempo
real.
