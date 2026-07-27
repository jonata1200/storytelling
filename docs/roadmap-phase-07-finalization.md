# Fase 7 - Finalizacao de Video e Provider de Voz

## Objetivo

Completar a etapa final do pipeline com voz real e renderizacao mais robusta.

## Escopo

- Implementar provider real de fala ou adaptar uma interface para multiplos providers.
- Gerar audio final com alinhamento para legendas.
- Melhorar exportacao FFmpeg para lidar com codecs/resolucoes diferentes.
- Adicionar normalizacao de clipes antes do concat final quando necessario.
- Permitir perfil de exportacao configuravel.
- Validar existencia e compatibilidade de assets antes de renderizar.

## Checklist de acoes

- [ ] Definir interface de provider de fala.
- [ ] Escolher primeiro provider real de voz.
- [ ] Adicionar configuracoes de provider/modelo/voz.
- [ ] Implementar chamada real de sintese de voz.
- [ ] Persistir audio gerado como asset.
- [ ] Gerar alinhamento para legendas quando o provider suportar.
- [ ] Criar fallback seguro quando alinhamento nao estiver disponivel.
- [ ] Desbloquear fluxo de narracao final sem usar mock.
- [ ] Validar codecs, resolucao e fps dos clipes antes de exportar.
- [ ] Implementar normalizacao FFmpeg quando clipes forem incompativeis.
- [ ] Permitir perfil de exportacao configuravel.
- [ ] Melhorar mensagens de erro de exportacao.
- [ ] Adicionar testes para provider de voz.
- [ ] Adicionar testes para exportacao manifest-only.
- [ ] Adicionar testes para exportacao MP4 quando FFmpeg estiver disponivel.

## Entregaveis

- Provider de voz real.
- Narracao final desbloqueada.
- Exportacao MP4 mais resiliente.
- Testes unitarios para montagem e fallback de manifest.

## Criterios de aceite

- Pipeline consegue gerar narracao final sem provider mock.
- Exportacao falha com mensagem clara quando assets sao incompativeis.
- Quando FFmpeg esta disponivel e assets sao validos, exporta MP4 final.
