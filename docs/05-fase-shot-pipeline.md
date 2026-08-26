# Fase 05 — Pipeline centrado em Shot e continuidade

## Objetivo

Fazer `Shot` virar a unidade fundamental de produção de vídeo e ligar diretamente roteiro, Visual Bible, geração, review e continuidade.

Hoje o projeto já possui `Scene`, `Shot` e `ContinuousVideoSegment`; esta fase elimina a distância conceitual entre eles.

## Mudança de modelo sugerida

Adicionar relação opcional para preservar compatibilidade:

```text
ContinuousVideoSegment.shot_id → shots.id
```

## Arquivos principais

```text
app/storytelling/models.py
app/video_generation/models.py
app/video_generation/continuous_planning.py
app/video_generation/continuous_generation.py
app/video_generation/continuous_review.py
app/generation/shot_generation_spec.py
app/generation/shot_prompt_compiler.py
alembic/versions/...
tests/
```

## Checklist — migration

- [x] Criar migration Alembic para `shot_id`.
- [x] Campo inicialmente nullable.
- [x] Criar índice.
- [x] Não apagar segmentos históricos.
- [x] Criar backfill quando associação puder ser deduzida com segurança.
- [x] Não inventar associação para projetos legados ambíguos.
- [ ] Testar upgrade.
- [x] Testar downgrade se a política do projeto exigir.
- [ ] Testar banco com dados existentes.

## Checklist — ShotGenerationSpec

Para cada Shot:

- [x] Carregar Scene.
- [x] Carregar personagem(s) mencionados.
- [x] Carregar local.
- [x] Carregar props relevantes.
- [x] Carregar estado/roupa do personagem.
- [x] Carregar referências aprovadas.
- [x] Carregar frame final do shot anterior quando aplicável.
- [x] Carregar action.
- [x] Carregar emotion.
- [x] Carregar visual composition.
- [x] Carregar camera movement.
- [x] Carregar duração.
- [x] Carregar regras de continuidade.
- [x] Produzir `ShotGenerationSpec`.
- [x] Validar que campos obrigatórios estejam preenchidos.
- [x] Registrar warnings para referências ausentes.

## Checklist — compilador de prompt

Separar conteúdo semântico de sintaxe do provider.

```text
Shot
 ↓
ShotGenerationSpec
 ↓
VibesPromptCompiler
 ↓
VideoGenerationRequest
```

- [x] Criar compilador Vibes.
- [x] Descrever uma ação principal por shot.
- [x] Descrever um movimento de câmera principal.
- [x] Descrever elementos que devem permanecer estáveis.
- [x] Evitar repetir toda a bíblia visual em texto quando ingredient/referência existir.
- [x] Referenciar continuidade explícita.
- [x] Produzir prompt em idioma que melhor performar no provider, sem alterar a UI do usuário.
- [x] Manter prompt final persistido/auditável.
- [x] Guardar versão do compilador.
- [x] Permitir regenerar usando o mesmo spec.

## Checklist — continuidade

- [x] Usar frame final anterior como referência quando fizer sentido.
- [x] Usar VisualReference do personagem.
- [x] Usar VisualReference de roupa/estado.
- [x] Usar VisualReference de local.
- [x] Usar ingredient Vibes quando disponível.
- [x] Manter mão/objeto/posição importantes no `continuity`.
- [x] Manter orientação espacial da cena.
- [x] Não forçar frame anterior quando há corte temporal/espacial deliberado.
- [x] Adicionar `continuity_break=true` quando necessário.
- [ ] Permitir ao diretor marcar uma quebra consciente.

## Checklist — estados do personagem

Criar estrutura semântica por shot, inicialmente em payload/metadata se não justificar tabela:

- [x] outfit.
- [x] hair state.
- [x] injuries.
- [x] carried props.
- [x] emotional state.
- [x] position.
- [x] wet/dry/dirty state.
- [x] time-of-day relevant state.
- [x] continuity notes.

- [x] Distinguir atributo canônico de estado temporário.
- [x] Não alterar `Character.canonical_profile` para representar estado de uma cena.
- [ ] Versionar mudança permanente real.

## Checklist — review/regeneração

- [x] Review deve apontar para Shot.
- [x] Rejeitar uma tomada não deve invalidar toda a Scene.
- [x] Regenerar somente o Shot necessário.
- [x] Guardar variantes.
- [x] Permitir selecionar uma variante.
- [x] Manter histórico.
- [x] Preservar custo de tentativas rejeitadas.
- [x] Permitir nota de rejeição.
- [x] Usar nota de rejeição na próxima tentativa quando apropriado.

## Checklist — montagem

- [x] Ordenar vídeos por Scene + Shot.
- [x] Validar que todos os shots obrigatórios possuem clip aprovado.
- [x] Não montar vídeo final com shot em estado failed/rejected sem override explícito.
- [x] Preservar duração esperada.
- [x] Produzir diagnóstico de gaps.
- [x] Reaproveitar FFmpeg/finalization existente.

## Testes

- [ ] Migration com dados legados.
- [x] Construção de `ShotGenerationSpec`.
- [ ] Shot sem personagem.
- [x] Shot com dois personagens.
- [ ] Shot sem referência visual.
- [x] Shot com frame anterior.
- [x] Shot com continuity break.
- [x] Prompt compiler.
- [x] Regeneração de um único shot.
- [x] Seleção de variante.
- [x] Ordenação de montagem.
- [x] Ruff.
- [x] mypy.
- [x] pytest.

## Critérios de aceite

- [x] Todo novo segmento de vídeo aponta para um Shot.
- [x] É possível rastrear `Script → Scene → Shot → Segment → Asset`.
- [x] Uma referência visual aprovada chega automaticamente ao request do Vibes.
- [x] A continuidade não depende apenas do frame anterior.
- [x] É possível regenerar um único Shot sem refazer o projeto inteiro.
