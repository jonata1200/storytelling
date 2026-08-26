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

- [ ] Criar um `VisualReferencePlan`.
- [ ] Gerar plano de referências a partir do perfil canônico.
- [ ] Para personagem principal, planejar no mínimo:
  - [ ] frontal;
  - [ ] 3/4;
  - [ ] perfil;
  - [ ] corpo inteiro;
  - [ ] expressão neutra;
  - [ ] roupas relevantes para a história.
- [ ] Para personagem secundário, permitir conjunto menor.
- [ ] Para local, planejar:
  - [ ] establishing view;
  - [ ] ângulo principal;
  - [ ] ângulo reverso quando necessário;
  - [ ] variação de iluminação importante para a trama.
- [ ] Para prop importante, criar referência canônica própria.
- [ ] Não gerar dezenas de imagens sem necessidade narrativa.
- [ ] Calcular referências necessárias a partir dos shots existentes.

## Checklist — ImageProvider Meta

- [ ] Implementar `MetaImageProvider`.
- [ ] Se API oficial estiver disponível: usar API.
- [ ] Se apenas UI autorizada estiver disponível: encapsular em `meta_browser.py`.
- [ ] Implementar `text → image`.
- [ ] Implementar `reference(s) → image`.
- [ ] Implementar download do arquivo.
- [ ] Implementar hash SHA-256.
- [ ] Identificar content type.
- [ ] Persistir metadados externos úteis.
- [ ] Registrar provider/model.
- [ ] Registrar custo/usage quando disponível.
- [ ] Implementar timeout.
- [ ] Implementar retries limitados.
- [ ] Nunca depender de screenshot como asset final se houver arquivo original disponível.

## Checklist — persistência

Para cada imagem aceita:

- [ ] Criar `Asset(kind=IMAGE)`.
- [ ] Criar `AssetVersion`.
- [ ] Criar `VisualReference`.
- [ ] Definir `target_kind`.
- [ ] Definir `target_id`.
- [ ] Definir `view_type`.
- [ ] Salvar prompt.
- [ ] Salvar provider.
- [ ] Salvar model.
- [ ] Salvar metadata.
- [ ] Vincular ao artifact correto.
- [ ] Preservar versionamento.

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

- [ ] Não colocar dados críticos somente em metadata se precisarem de query relacional frequente.
- [ ] Usar metadata para IDs externos e detalhes específicos de provider.
- [ ] Não apagar metadata histórica de imagens antigas.

## Checklist — aprovação visual

- [ ] Adicionar status de referência: `generated`, `approved`, `rejected`.
- [ ] Permitir escolher imagem canônica.
- [ ] Permitir regenerar uma view específica.
- [ ] Não substituir silenciosamente uma referência aprovada.
- [ ] Criar nova versão/asset ao regenerar.
- [ ] Manter histórico.
- [ ] Permitir editar prompt antes da regeneração.
- [ ] Mostrar provider/model na UI de diagnóstico, não como informação principal.

## Checklist — consistência de personagem

- [ ] Usar referências já aprovadas ao gerar novas views.
- [ ] Guardar fingerprint visual/canônico existente.
- [ ] Não alterar características fixas sem versionamento.
- [ ] Detectar quando um novo prompt contradiz o perfil canônico.
- [ ] Bloquear troca acidental de idade, cabelo ou traços marcantes.
- [ ] Permitir mudança deliberada via versão (ex.: cabelo cortado durante a história).
- [ ] Separar identidade permanente de estado por cena/shot.

## Checklist — UI

- [ ] Atualizar aba Visual Bible.
- [ ] Exibir cards de personagem.
- [ ] Exibir cards de local.
- [ ] Exibir views/referências.
- [ ] Botão `Gerar referências`.
- [ ] Botão `Regenerar`.
- [ ] Botão `Aprovar como canônica`.
- [ ] Botão `Rejeitar`.
- [ ] Exibir progresso.
- [ ] Exibir erro de provider de forma amigável.
- [ ] Permitir abrir imagem em tamanho maior.
- [ ] Não expor cookies/chaves.

## Checklist — integração com Vibes

Preparar a biblioteca, sem ainda gerar vídeo.

- [ ] Adicionar campo/metadata para `vibes.ingredient_id`.
- [ ] Adicionar `vibes.ingredient_type`.
- [ ] Adicionar `vibes.synced_at`.
- [ ] Adicionar `vibes.sync_status`.
- [ ] Não sincronizar automaticamente tudo.
- [ ] Sincronizar somente referências aprovadas.
- [ ] Tornar operação idempotente.

## Testes

- [ ] Teste de planejamento de referências.
- [ ] Teste de persistência Asset + VisualReference.
- [ ] Teste de regeneração sem destruir histórico.
- [ ] Teste de aprovação.
- [ ] Teste de imagem inválida.
- [ ] Teste de output fora do storage root.
- [ ] Teste de browser profile seguro, se aplicável.
- [ ] Teste provider Meta mockado.
- [ ] Smoke real de personagem.
- [ ] Smoke real de local.
- [ ] Smoke real com múltiplas referências.
- [ ] Ruff.
- [ ] mypy.
- [ ] pytest.

## Critérios de aceite

- [ ] A Visual Bible deixa de ser apenas textual.
- [ ] É possível gerar e aprovar imagens canônicas.
- [ ] Toda imagem é `Asset` versionado.
- [ ] Toda relação visual é `VisualReference`.
- [ ] Personagens podem reutilizar imagens aprovadas para novas gerações.
- [ ] As referências aprovadas ficam prontas para serem transformadas em ingredients no Vibes.
