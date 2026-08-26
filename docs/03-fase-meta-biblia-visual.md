# Fase 03 — Meta para biblioteca visual e imagens

## Objetivo

Transformar a `visual_bible` atual — que já cria perfis canônicos textuais — em uma biblioteca visual persistente com assets de personagens, locais, roupas, objetos e referências geradas pela Meta.

## Princípio

Não criar um segundo sistema de biblioteca.

Reutilizar:

```text
Character
CharacterVersion
Location
LocationVersion
VisualReference
Asset
AssetVersion
Artifact
```

`VisualReference` passa a ser a ponte entre uma entidade canônica e uma imagem real.

## Novos arquivos sugeridos

```text
app/providers/image/meta.py
app/providers/image/meta_browser.py        # somente se necessário/autorizado
app/providers/image/types.py

app/visual_bible/image_generation.py
app/visual_bible/reference_planning.py
app/visual_bible/reference_queries.py

tests/providers/test_meta_image.py
tests/integration/test_visual_bible_images.py
```

## Checklist — planejamento de referências

- [x] Criar um `VisualReferencePlan`.
- [x] Gerar plano de referências a partir do perfil canônico.
- [ ] Para personagem principal, planejar no mínimo:
  - [x] frontal;
  - [x] 3/4;
  - [x] perfil;
  - [x] corpo inteiro;
  - [x] expressão neutra;
  - [x] roupas relevantes para a história.
- [x] Para personagem secundário, permitir conjunto menor.
- [ ] Para local, planejar:
  - [x] establishing view;
  - [x] ângulo principal;
  - [x] ângulo reverso quando necessário;
  - [x] variação de iluminação importante para a trama.
- [x] Para prop importante, criar referência canônica própria.
- [x] Não gerar dezenas de imagens sem necessidade narrativa.
- [x] Calcular referências necessárias a partir dos shots existentes.

## Checklist — ImageProvider Meta

- [x] Implementar `MetaImageProvider`.
- [ ] Se API oficial estiver disponível: usar API.
- [ ] Se apenas UI autorizada estiver disponível: encapsular em `meta_browser.py`.
- [x] Implementar `text → image`.
- [x] Implementar `reference(s) → image`.
- [x] Implementar download do arquivo.
- [x] Implementar hash SHA-256.
- [x] Identificar content type.
- [x] Persistir metadados externos úteis.
- [x] Registrar provider/model.
- [x] Registrar custo/usage quando disponível.
- [x] Implementar timeout.
- [x] Implementar retries limitados.
- [x] Nunca depender de screenshot como asset final se houver arquivo original disponível.

## Checklist — persistência

Para cada imagem aceita:

- [x] Criar `Asset(kind=IMAGE)`.
- [x] Criar `AssetVersion`.
- [x] Criar `VisualReference`.
- [x] Definir `target_kind`.
- [x] Definir `target_id`.
- [x] Definir `view_type`.
- [x] Salvar prompt.
- [x] Salvar provider.
- [x] Salvar model.
- [x] Salvar metadata.
- [x] Vincular ao artifact correto.
- [x] Preservar versionamento.

## Checklist — metadata padrão

Padronizar algo equivalente a:

```json
{
  "canonical": true,
  "reference_role": "character_front",
  "generation_seed": null,
  "external_generation_id": "...",
  "source_mode": "api",
  "approved": false,
  "vibes": {
    "ingredient_id": null,
    "ingredient_type": null
  }
}
```

- [x] Não colocar dados críticos somente em metadata se precisarem de query relacional frequente.
- [x] Usar metadata para IDs externos e detalhes específicos de provider.
- [x] Não apagar metadata histórica de imagens antigas.

## Checklist — aprovação visual

- [x] Adicionar status de referência: `generated`, `approved`, `rejected`.
- [x] Permitir escolher imagem canônica.
- [x] Permitir regenerar uma view específica.
- [x] Não substituir silenciosamente uma referência aprovada.
- [x] Criar nova versão/asset ao regenerar.
- [x] Manter histórico.
- [x] Permitir editar prompt antes da regeneração.
- [x] Mostrar provider/model na UI de diagnóstico, não como informação principal.

## Checklist — consistência de personagem

- [x] Usar referências já aprovadas ao gerar novas views.
- [x] Guardar fingerprint visual/canônico existente.
- [x] Não alterar características fixas sem versionamento.
- [x] Detectar quando um novo prompt contradiz o perfil canônico.
- [x] Bloquear troca acidental de idade, cabelo ou traços marcantes.
- [x] Permitir mudança deliberada via versão (ex.: cabelo cortado durante a história).
- [x] Separar identidade permanente de estado por cena/shot.

## Checklist — UI

- [x] Atualizar aba Visual Bible.
- [x] Exibir cards de personagem.
- [x] Exibir cards de local.
- [x] Exibir views/referências.
- [x] Botão `Gerar referências`.
- [x] Botão `Regenerar`.
- [x] Botão `Aprovar como canônica`.
- [x] Botão `Rejeitar`.
- [x] Exibir progresso.
- [x] Exibir erro de provider de forma amigável.
- [x] Permitir abrir imagem em tamanho maior.
- [x] Não expor cookies/chaves.

## Checklist — integração com Vibes

Preparar a biblioteca, sem ainda gerar vídeo.

- [x] Adicionar campo/metadata para `vibes.ingredient_id`.
- [x] Adicionar `vibes.ingredient_type`.
- [x] Adicionar `vibes.synced_at`.
- [x] Adicionar `vibes.sync_status`.
- [x] Não sincronizar automaticamente tudo.
- [x] Sincronizar somente referências aprovadas.
- [x] Tornar operação idempotente.

## Testes

- [x] Teste de planejamento de referências.
- [x] Teste de persistência Asset + VisualReference.
- [x] Teste de regeneração sem destruir histórico.
- [ ] Teste de aprovação.
- [x] Teste de imagem inválida.
- [x] Teste de output fora do storage root.
- [x] Teste de browser profile seguro, se aplicável.
- [x] Teste provider Meta mockado.
- [ ] Smoke real de personagem.
- [ ] Smoke real de local.
- [ ] Smoke real com múltiplas referências.
- [x] Ruff.
- [x] mypy.
- [x] pytest.

## Critérios de aceite

- [x] A Visual Bible deixa de ser apenas textual.
- [x] É possível gerar e aprovar imagens canônicas.
- [x] Toda imagem é `Asset` versionado.
- [x] Toda relação visual é `VisualReference`.
- [x] Personagens podem reutilizar imagens aprovadas para novas gerações.
- [x] As referências aprovadas ficam prontas para serem transformadas em ingredients no Vibes.
