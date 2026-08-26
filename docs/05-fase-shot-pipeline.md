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

- [ ] Criar migration Alembic para `shot_id`.
- [ ] Campo inicialmente nullable.
- [ ] Criar índice.
- [ ] Não apagar segmentos históricos.
- [ ] Criar backfill quando associação puder ser deduzida com segurança.
- [ ] Não inventar associação para projetos legados ambíguos.
- [ ] Testar upgrade.
- [ ] Testar downgrade se a política do projeto exigir.
- [ ] Testar banco com dados existentes.

## Checklist — ShotGenerationSpec

Para cada Shot:

- [ ] Carregar Scene.
- [ ] Carregar personagem(s) mencionados.
- [ ] Carregar local.
- [ ] Carregar props relevantes.
- [ ] Carregar estado/roupa do personagem.
- [ ] Carregar referências aprovadas.
- [ ] Carregar frame final do shot anterior quando aplicável.
- [ ] Carregar action.
- [ ] Carregar emotion.
- [ ] Carregar visual composition.
- [ ] Carregar camera movement.
- [ ] Carregar duração.
- [ ] Carregar regras de continuidade.
- [ ] Produzir `ShotGenerationSpec`.
- [ ] Validar que campos obrigatórios estejam preenchidos.
- [ ] Registrar warnings para referências ausentes.

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

- [ ] Criar compilador Vibes.
- [ ] Descrever uma ação principal por shot.
- [ ] Descrever um movimento de câmera principal.
- [ ] Descrever elementos que devem permanecer estáveis.
- [ ] Evitar repetir toda a bíblia visual em texto quando ingredient/referência existir.
- [ ] Referenciar continuidade explícita.
- [ ] Produzir prompt em idioma que melhor performar no provider, sem alterar a UI do usuário.
- [ ] Manter prompt final persistido/auditável.
- [ ] Guardar versão do compilador.
- [ ] Permitir regenerar usando o mesmo spec.

## Checklist — continuidade

- [ ] Usar frame final anterior como referência quando fizer sentido.
- [ ] Usar VisualReference do personagem.
- [ ] Usar VisualReference de roupa/estado.
- [ ] Usar VisualReference de local.
- [ ] Usar ingredient Vibes quando disponível.
- [ ] Manter mão/objeto/posição importantes no `continuity`.
- [ ] Manter orientação espacial da cena.
- [ ] Não forçar frame anterior quando há corte temporal/espacial deliberado.
- [ ] Adicionar `continuity_break=true` quando necessário.
- [ ] Permitir ao diretor marcar uma quebra consciente.

## Checklist — estados do personagem

Criar estrutura semântica por shot, inicialmente em payload/metadata se não justificar tabela:

- [ ] outfit.
- [ ] hair state.
- [ ] injuries.
- [ ] carried props.
- [ ] emotional state.
- [ ] position.
- [ ] wet/dry/dirty state.
- [ ] time-of-day relevant state.
- [ ] continuity notes.

- [ ] Distinguir atributo canônico de estado temporário.
- [ ] Não alterar `Character.canonical_profile` para representar estado de uma cena.
- [ ] Versionar mudança permanente real.

## Checklist — review/regeneração

- [ ] Review deve apontar para Shot.
- [ ] Rejeitar uma tomada não deve invalidar toda a Scene.
- [ ] Regenerar somente o Shot necessário.
- [ ] Guardar variantes.
- [ ] Permitir selecionar uma variante.
- [ ] Manter histórico.
- [ ] Preservar custo de tentativas rejeitadas.
- [ ] Permitir nota de rejeição.
- [ ] Usar nota de rejeição na próxima tentativa quando apropriado.

## Checklist — montagem

- [ ] Ordenar vídeos por Scene + Shot.
- [ ] Validar que todos os shots obrigatórios possuem clip aprovado.
- [ ] Não montar vídeo final com shot em estado failed/rejected sem override explícito.
- [ ] Preservar duração esperada.
- [ ] Produzir diagnóstico de gaps.
- [ ] Reaproveitar FFmpeg/finalization existente.

## Testes

- [ ] Migration com dados legados.
- [ ] Construção de `ShotGenerationSpec`.
- [ ] Shot sem personagem.
- [ ] Shot com dois personagens.
- [ ] Shot sem referência visual.
- [ ] Shot com frame anterior.
- [ ] Shot com continuity break.
- [ ] Prompt compiler.
- [ ] Regeneração de um único shot.
- [ ] Seleção de variante.
- [ ] Ordenação de montagem.
- [ ] Ruff.
- [ ] mypy.
- [ ] pytest.

## Critérios de aceite

- [ ] Todo novo segmento de vídeo aponta para um Shot.
- [ ] É possível rastrear `Script → Scene → Shot → Segment → Asset`.
- [ ] Uma referência visual aprovada chega automaticamente ao request do Vibes.
- [ ] A continuidade não depende apenas do frame anterior.
- [ ] É possível regenerar um único Shot sem refazer o projeto inteiro.
