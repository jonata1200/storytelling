"""Teste estático da remoção da propagação automática do frame extraído.

Bug: select_continuous_video_segment_variant propagava o frame extraído
do vídeo para o próximo segmento via next_segment.source_frame_asset_id
= extracted_frame_id (a menos que continuity_break=True).

Correção: propagação REMOVIDA. O frame fica no segmento selecionado
apenas (segment.final_frame_asset_id). O próximo segmento só recebe
o frame se o usuário usar explicitamente o toggle "Usar último frame
do segmento anterior" e clicar "Gerar vídeo".

Este teste é uma proteção contra regressões: se alguém reativar a
propagação automática no futuro, este teste falha.
"""

from __future__ import annotations

import inspect

# Resolver import circular: continuous_review importa de continuous que importa de review.
# Carregar continuous primeiro força os imports em ordem.
from app.video_generation import continuous  # noqa: F401
from app.video_generation.continuous_review import select_continuous_video_segment_variant


def test_select_variant_does_not_propagate_to_next_segment() -> None:
    """A função select_continuous_video_segment_variant não deve
    escrever em next_segment.source_frame_asset_id.

    Verificação estática via inspeção do source.
    """
    source = inspect.getsource(select_continuous_video_segment_variant)

    # Procura padrões de propagação
    forbidden = [
        "next_segment.source_frame_asset_id = extracted_frame_id",
        "next_segment.source_frame_asset_id=extracted_frame_id",
    ]
    for pattern in forbidden:
        assert pattern not in source, (
            "BUG: propagação automática do frame reativada em "
            "select_continuous_video_segment_variant. O usuário deve "
            "optar explicitamente via toggle 'Usar último frame do "
            "segmento anterior'."
        )

    # Garante que o trecho que fazia a propagação foi removido
    # (era linhas 335-341 antes da correção)
    assert "next_metadata[\"continuity_source_variant_asset_id\"]" not in source, (
        "BUG: tag continuity_source_variant_asset_id ainda é gravada "
        "no metadata do próximo segmento."
    )