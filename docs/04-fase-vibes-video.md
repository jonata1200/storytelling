# Fase 04 — Vibes para geração de vídeo

## Objetivo

Implementar o Vibes como único provider alvo de vídeo, inicialmente convivendo com o provider legado apenas para comparação/cutover.

O novo provider deve obedecer ao contrato genérico já existente.

## Novos arquivos sugeridos

```text
app/providers/video/vibes.py
app/providers/video/vibes_browser.py       # se necessário/autorizado
app/providers/video/vibes_mapping.py
app/providers/video/factory.py

app/vibes/ingredients.py                   # opcional; domínio de integração externa

tests/providers/test_vibes_video.py
tests/integration/test_vibes_generation.py
```

## Regra

O módulo `video_generation` não deve conhecer detalhes de Vibes, Playwright, seletor CSS, sessão web ou API.

Ele chama:

```text
VideoProvider.submit()
VideoProvider.poll()
VideoProvider.download()
```

## Checklist — VibesVideoProvider

- [ ] Criar `VibesVideoProvider`.
- [ ] Implementar `provider_name = "vibes"`.
- [ ] Implementar `submit`.
- [ ] Implementar `poll`.
- [ ] Implementar `download`.
- [ ] Converter `VideoGenerationRequest` para formato Vibes.
- [ ] Mapear duração.
- [ ] Mapear aspect ratio.
- [ ] Mapear áudio.
- [ ] Mapear first/final frame quando suportado.
- [ ] Mapear `input_references`.
- [ ] Mapear ingredients.
- [ ] Retornar `VideoJob` genérico.
- [ ] Retornar `VideoJobUpdate` genérico.
- [ ] Retornar `VideoGenerationResult` genérico.
- [ ] Registrar external job id.
- [ ] Registrar provider/model.
- [ ] Registrar custo quando disponível.

## Checklist — modo API, se disponível

- [ ] Usar somente endpoint público/documentado.
- [ ] Implementar auth conforme documentação.
- [ ] Implementar timeouts.
- [ ] Implementar retries de erros transitórios.
- [ ] Implementar 429.
- [ ] Implementar polling.
- [ ] Implementar download.
- [ ] Validar arquivo retornado.
- [ ] Não acessar endpoints internos não documentados.

## Checklist — modo browser, se necessário

- [ ] Usar Playwright.
- [ ] Encapsular tudo em `vibes_browser.py`.
- [ ] Usar perfil persistente dedicado.
- [ ] Nunca armazenar senha/cookie no Git.
- [ ] Verificar sessão antes do job.
- [ ] Detectar login expirado.
- [ ] Criar/selecionar projeto no Vibes.
- [ ] Inserir prompt.
- [ ] Anexar referências.
- [ ] Selecionar ingredients.
- [ ] Configurar aspect ratio.
- [ ] Configurar duração, quando disponível.
- [ ] Disparar geração.
- [ ] Capturar ID/locator estável da geração.
- [ ] Implementar polling baseado no estado visível/documentado.
- [ ] Baixar o arquivo final.
- [ ] Validar MIME/arquivo.
- [ ] Detectar moderação/bloqueio.
- [ ] Detectar mudança de UI e falhar com erro diagnóstico.
- [ ] Salvar screenshot de erro somente em diretório de diagnóstico.
- [ ] Não usar scraping de tokens para chamar APIs privadas.

## Checklist — ingredients

- [ ] Criar serviço de sincronização de ingredient.
- [ ] Receber `VisualReference` aprovada.
- [ ] Criar ingredient de personagem.
- [ ] Criar ingredient de objeto.
- [ ] Criar ingredient de estilo/local quando suportado.
- [ ] Persistir `ingredient_id`.
- [ ] Persistir `ingredient_type`.
- [ ] Persistir `synced_at`.
- [ ] Tornar criação idempotente.
- [ ] Não recriar ingredient se a referência não mudou.
- [ ] Criar novo ingredient quando a referência canônica mudar de versão.
- [ ] Manter relação com a versão antiga para reproduzir vídeos históricos.

## Checklist — integração com continuous generation

- [ ] Remover import concreto de OpenRouter do fluxo principal.
- [ ] Resolver provider pelo factory/registry.
- [ ] Usar diretório neutro `generated_videos/{project_id}`.
- [ ] Usar `provider_job_id` em metadata nova.
- [ ] Preservar leitura de metadata antiga.
- [ ] Enviar frame inicial quando disponível.
- [ ] Enviar referências aprovadas relevantes.
- [ ] Enviar ingredients relevantes.
- [ ] Finalizar asset com o mesmo fluxo atual.
- [ ] Extrair frame final com FFmpeg.
- [ ] Vincular frame final ao próximo segmento/shot.
- [ ] Registrar custos/usage.
- [ ] Registrar eventos de observabilidade.

## Checklist — cenários de erro

- [ ] Login expirado.
- [ ] Geração rejeitada por moderação.
- [ ] Timeout.
- [ ] Página não carregou.
- [ ] Job desapareceu.
- [ ] Download falhou.
- [ ] Arquivo vazio.
- [ ] Arquivo não é vídeo.
- [ ] Ingredient não existe.
- [ ] Ingredient foi removido.
- [ ] Reference upload falhou.
- [ ] Rate limit.
- [ ] Vibes indisponível.
- [ ] Cancelamento pelo usuário.
- [ ] Retry sem gerar duplicação silenciosa.

## Testes

- [ ] Contract test `submit`.
- [ ] Contract test `poll`.
- [ ] Contract test `download`.
- [ ] Teste de request mapping.
- [ ] Teste de ingredients.
- [ ] Teste de idempotência.
- [ ] Teste de timeout.
- [ ] Teste de download corrompido.
- [ ] Teste de erro de autenticação/sessão.
- [ ] Teste do factory.
- [ ] Smoke `text → video`.
- [ ] Smoke `image → video`.
- [ ] Smoke com ingredient de personagem.
- [ ] Smoke com frame de continuidade.
- [ ] Ruff.
- [ ] mypy.
- [ ] pytest.

## Critérios de aceite

- [ ] Um segmento real pode ser gerado pelo Vibes dentro do fluxo da aplicação.
- [ ] O vídeo é salvo como `Asset`.
- [ ] O último frame é extraído e persistido.
- [ ] O próximo segmento consegue reutilizar continuidade.
- [ ] Ingredients aprovados podem ser reutilizados.
- [ ] O domínio não contém Playwright/Vibes-specific logic.
- [ ] Vibes está apto a substituir completamente OpenRouter.
