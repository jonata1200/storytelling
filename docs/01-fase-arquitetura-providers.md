# Fase 01 — Arquitetura de providers e neutralização do domínio

## Objetivo

Preparar a aplicação para trabalhar exclusivamente com Meta + Vibes sem que módulos de domínio importem implementações concretas de provider.

O comportamento legado continua disponível temporariamente até o cutover.

## Problema atual a corrigir

O projeto já possui bons contratos, mas ainda há acoplamento concreto em pontos como a geração contínua de vídeo, que conhece diretamente `OpenRouterVideoProvider`.

A meta é chegar a:

```text
Domínio / Serviços
       ↓
ProviderRegistry
  ↙      ↓       ↘
text   image    video
 ↓       ↓        ↓
Meta    Meta     Vibes
```

## Novos arquivos sugeridos

```text
app/providers/registry.py

app/providers/image/
  __init__.py
  types.py

app/providers/video/factory.py

app/generation/shot_generation_spec.py
```

## Arquivos principais a revisar

```text
app/config/settings.py
app/config/provider_policy.py
app/generation/model_settings.py
app/generation/service.py
app/providers/llm/types.py
app/providers/video/types.py
app/video_generation/continuous_generation.py
app/production/
tests/
```

## Checklist — canais de provider

- [ ] Expandir `ProviderChannel` para suportar `text`, `image` e `video`.
- [ ] Introduzir `SUPPORTED_IMAGE_PROVIDERS`.
- [ ] Preparar `meta` como provider permitido para `text`.
- [ ] Preparar `meta` como provider permitido para `image`.
- [ ] Preparar `vibes` como provider permitido para `video`.
- [ ] Manter providers antigos apenas como compatibilidade temporária nesta fase.
- [ ] Garantir que `provider_display_name()` seja neutro e extensível.
- [ ] Garantir que `provider_api_key()` não suponha que todo provider usa API key.
- [ ] Permitir providers com autenticação via perfil de browser.
- [ ] Separar "provider configurado" de "modo de integração" (`api`, `browser`).

## Checklist — Settings

- [ ] Adicionar `image_provider`.
- [ ] Adicionar configurações Meta.
- [ ] Adicionar configurações Vibes.
- [ ] Não apagar ainda configurações Ollama/OpenRouter.
- [ ] Introduzir `meta_integration_mode`.
- [ ] Introduzir `vibes_integration_mode`.
- [ ] Introduzir caminhos de browser profile fora do storage público.
- [ ] Validar que caminhos de browser profile não possam escapar da raiz permitida.
- [ ] Não imprimir secrets em `repr`.
- [ ] Atualizar redaction para novos secrets.
- [ ] Preparar runtime preferences para os novos campos.

Exemplo conceitual:

```env
TEXT_PROVIDER=meta
IMAGE_PROVIDER=meta
VIDEO_PROVIDER=vibes

META_INTEGRATION_MODE=api
META_API_KEY=
META_TEXT_MODEL=

META_IMAGE_INTEGRATION_MODE=api

VIBES_INTEGRATION_MODE=browser
VIBES_BROWSER_PROFILE_PATH=./runtime/browser_profiles/vibes
```

## Checklist — contrato ImageProvider

- [ ] Criar `ImageReference`.
- [ ] Criar `ImageGenerationRequest`.
- [ ] Criar `ImageGenerationJob`, se a integração for assíncrona.
- [ ] Criar `ImageGenerationResult`.
- [ ] Criar `ImageProvider(Protocol)`.
- [ ] Definir suporte a prompt.
- [ ] Definir suporte a múltiplas referências.
- [ ] Definir aspect ratio.
- [ ] Definir output_dir.
- [ ] Definir provider/model.
- [ ] Definir metadata externa.
- [ ] Validar que o output fique dentro do storage permitido.
- [ ] Evitar qualquer campo Meta-specific no contrato genérico.

## Checklist — registry/factory

- [ ] Criar uma única resolução central para provider de texto.
- [ ] Criar uma única resolução central para provider de imagem.
- [ ] Criar uma única resolução central para provider de vídeo.
- [ ] Eliminar imports concretos de provider nos serviços de domínio.
- [ ] Fazer `continuous_generation.py` depender de `VideoProvider`.
- [ ] Fazer a futura Visual Bible depender de `ImageProvider`.
- [ ] Garantir erro claro para provider não suportado.
- [ ] Garantir testes de resolução por canal.
- [ ] Garantir testes para provider configurado sem credencial.
- [ ] Garantir que browser provider não exija artificialmente API key.

## Checklist — neutralização de nomes internos

- [ ] Introduzir diretório de storage neutro `generated_videos/`.
- [ ] Introduzir diretório neutro `generated_images/`.
- [ ] Para novos assets, usar `external_job_id` em vez de nomes como `openrouter_job_id`.
- [ ] Para novos metadados, usar `provider_job_id`.
- [ ] Manter leitura de metadados antigos para projetos existentes.
- [ ] Não regravar assets históricos apenas para trocar nome de chave.
- [ ] Neutralizar mensagens de observabilidade.
- [ ] Neutralizar mensagens de UI.
- [ ] Neutralizar nomes de operações de custo quando possível.

## Checklist — GenerationSpec

Criar um contrato intermediário que represente o que deve existir na tomada antes de traduzi-la para Meta/Vibes.

- [ ] Criar `ShotGenerationSpec`.
- [ ] Incluir `shot_id`.
- [ ] Incluir `scene_id`.
- [ ] Incluir duração.
- [ ] Incluir personagens.
- [ ] Incluir local.
- [ ] Incluir props.
- [ ] Incluir action.
- [ ] Incluir emotion.
- [ ] Incluir camera.
- [ ] Incluir lighting.
- [ ] Incluir continuity.
- [ ] Incluir visual references.
- [ ] Incluir previous frame/reference quando existir.
- [ ] Manter o objeto independente de provider.

## Testes

- [ ] Teste unitário do registry de texto.
- [ ] Teste unitário do registry de imagem.
- [ ] Teste unitário do registry de vídeo.
- [ ] Teste de provider inválido.
- [ ] Teste de auth mode API.
- [ ] Teste de auth mode browser.
- [ ] Teste de path traversal para output/profile path.
- [ ] Teste de serialização do `ShotGenerationSpec`.
- [ ] Rodar Ruff.
- [ ] Rodar mypy.
- [ ] Rodar pytest completo.

## Critérios de aceite

- [ ] Nenhum serviço de domínio precisa instanciar diretamente `OpenRouterVideoProvider`.
- [ ] Existe um contrato genérico para imagem.
- [ ] Existe registry/factory por canal.
- [ ] `ShotGenerationSpec` existe e não contém nomes Meta/Vibes.
- [ ] O comportamento legado ainda funciona.
- [ ] Todos os testes existentes continuam verdes.
