from uuid import uuid4

from app.storyboards.timeline import build_visual_timeline_items, build_word_alignment


def test_build_visual_timeline_items_is_contiguous() -> None:
    first_artifact = uuid4()
    first_asset = uuid4()
    second_artifact = uuid4()
    second_asset = uuid4()

    items = build_visual_timeline_items(
        [
            (first_artifact, first_asset, 3, {"frame": 1}),
            (second_artifact, second_asset, 2, {"frame": 2}),
        ]
    )

    assert items[0].start_ms == 0
    assert items[0].end_ms == 3000
    assert items[1].start_ms == 3000
    assert items[1].end_ms == 5000


def test_build_word_alignment_spreads_words_across_duration() -> None:
    alignment = build_word_alignment("uma promessa esquecida", 3)

    assert [item["word"] for item in alignment["words"]] == ["uma", "promessa", "esquecida"]
    assert alignment["words"][0]["start_ms"] == 0
    assert alignment["words"][-1]["end_ms"] == 3000
