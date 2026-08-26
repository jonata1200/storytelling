# Erros funcionais

## FUN-01 — Finalização aceita projeto com segmentos pendentes

**Severidade:** alta  
**Evidência:** `app/video_generation/finalization.py:113-114`

`check_all_segments_completed()` retorna `all_completed`, `total` e `completed`, mas
`concatenate_videos()` descarta o primeiro valor e só exige três vídeos concluídos. Assim, um
projeto com, por exemplo, 10 segmentos planejados e apenas 3 gerados pode ser “finalizado” com
um vídeo parcial. O endpoint de status informa que nem todos terminaram, enquanto a ação de
finalização permite prosseguir, criando uma contradição funcional.

**Impacto:** entrega truncada apresentada como vídeo final e necessidade de apagar/regenerar o
artefato.

**Recomendação:** exigir `all_completed` antes da concatenação, ou tornar explicitamente
configurável e visível uma operação distinta de “exportação parcial”.

## FUN-02 — Caminhos de segmentos são interpretados de forma diferente do restante do storage

**Severidade:** média  
**Evidência:** `app/video_generation/finalization.py:130-140`

A finalização converte `video_storage_uri` diretamente com `Path(video_uri)` e testa
`exists()`. Outros fluxos usam `resolve_storage_path()`, que trata caminhos relativos e valida o
storage root. Se um URI persistido for relativo ao diretório de storage, mas o processo for
iniciado em outro diretório, a finalização não encontra um arquivo existente.

**Impacto:** falha intermitente dependente do diretório de trabalho e contagem incorreta de
segmentos disponíveis.

**Recomendação:** usar o mesmo resolvedor canônico de storage empregado nos endpoints de
download e assets.
