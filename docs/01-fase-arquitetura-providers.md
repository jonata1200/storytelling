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

- [x] Expandir `ProviderChannel` para suportar `text`, `image` e `video`.
- [x] Introduzir `SUPPORTED_IMAGE_PROVIDERS`.
- [x] Preparar `meta` como provider permitido para `text`.
- [x] Preparar `meta` como provider permitido para `image`.
- [x] Preparar `vibes` como provider permitido para `video`.
- [x] Manter providers antigos apenas como compatibilidade temporária nesta fase.
- [x] Garantir que `provider_display_name()` seja neutro e extensível.
- [x] Garantir que `provider_api_key()` não suponha que todo provider usa API key.
- [x] Permitir providers com autenticação via perfil de browser.
- [x] Separar "provider configurado" de "modo de integração" (`api`, `browser`).

## Checklist — Settings

- [x] Adicionar `image_provider`.
- [x] Adicionar configurações Meta.
- [x] Adicionar configurações Vibes.
- [x] Não apagar ainda configurações Ollama/OpenRouter.
- [x] Introduzir `meta_integration_mode`.
- [x] Introduzir `vibes_integration_mode`.
- [x] Introduzir caminhos de browser profile fora do storage público.
- [x] Validar que caminhos de browser profile não possam escapar da raiz permitida.
- [x] Não imprimir secrets em `repr`.
- [x] Atualizar redaction para novos secrets.
- [x] Preparar runtime preferences para os novos campos.

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

- [x] Criar `ImageReference`.
- [x] Criar `ImageGenerationRequest`.
- [x] Criar `ImageGenerationJob`, se a integração for assíncrona.
- [x] Criar `ImageGenerationResult`.
- [x] Criar `ImageProvider(Protocol)`.
- [x] Definir suporte a prompt.
- [x] Definir suporte a múltiplas referências.
- [x] Definir aspect ratio.
- [x] Definir output_dir.
- [x] Definir provider/model.
- [x] Definir metadata externa.
- [x] Validar que o output fique dentro do storage permitido.
- [x] Evitar qualquer campo Meta-specific no contrato genérico.

## Checklist — registry/factory

- [x] Criar uma única resolução central para provider de texto.
- [x] Criar uma única resolução central para provider de imagem.
- [x] Criar uma única resolução central para provider de vídeo.
- [x] Eliminar imports concretos de provider nos serviços de domínio.
- [x] Fazer `continuous_generation.py` depender de `VideoProvider`.
- [x] Fazer a futura Visual Bible depender de `ImageProvider`.
- [x] Garantir erro claro para provider não suportado.
- [x] Garantir testes de resolução por canal.
- [x] Garantir testes para provider configurado sem credencial.
- [x] Garantir que browser provider não exija artificialmente API key.

## Checklist — neutralização de nomes internos

- [x] Introduzir diretório de storage neutro `generated_videos/`.
- [x] Introduzir diretório neutro `generated_images/`.
- [x] Para novos assets, usar `external_job_id` em vez de nomes como `openrouter_job_id`.
- [x] Para novos metadados, usar `provider_job_id`.
- [x] Manter leitura de metadados antigos para projetos existentes.
- [x] Não regravar assets históricos apenas para trocar nome de chave.
- [x] Neutralizar mensagens de observabilidade.
- [x] Neutralizar mensagens de UI.
- [x] Neutralizar nomes de operações de custo quando possível.

## Checklist — GenerationSpec

Criar um contrato intermediário que represente o que deve existir na tomada antes de traduzi-la para Meta/Vibes.

- [x] Criar `ShotGenerationSpec`.
- [x] Incluir `shot_id`.
- [x] Incluir `scene_id`.
- [x] Incluir duração.
- [x] Incluir personagens.
- [x] Incluir local.
- [x] Incluir props.
- [x] Incluir action.
- [x] Incluir emotion.
- [x] Incluir camera.
- [x] Incluir lighting.
- [x] Incluir continuity.
- [x] Incluir visual references.
- [x] Incluir previous frame/reference quando existir.
- [x] Manter o objeto independente de provider.

## Testes

- [x] Teste unitário do registry de texto.
- [x] Teste unitário do registry de imagem.
- [x] Teste unitário do registry de vídeo.
- [x] Teste de provider inválido.
- [x] Teste de auth mode API.
- [x] Teste de auth mode browser.
- [x] Teste de path traversal para output/profile path.
- [x] Teste de serialização do `ShotGenerationSpec`.
- [ ] Rodar Ruff.
- [x] Rodar mypy.
- [x] Rodar pytest completo.

## Critérios de aceite

- [x] Nenhum serviço de domínio precisa instanciar diretamente `OpenRouterVideoProvider`.
- [x] Existe um contrato genérico para imagem.
- [x] Existe registry/factory por canal.
- [x] `ShotGenerationSpec` existe e não contém nomes Meta/Vibes.
- [x] O comportamento legado ainda funciona.
- [x] Todos os testes existentes continuam verdes.
