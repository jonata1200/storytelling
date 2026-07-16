from app.quality.continuity import check_timeline_integrity, compare_continuity_states


def test_compare_continuity_states_detects_missing_object() -> None:
    previous = {
        "characters": [
            {
                "id": "char_1",
                "name": "Clara",
                "outfit": "casaco azul",
                "hair": "cabelo preso",
            }
        ],
        "carried_objects": [{"id": "prop_1", "name": "carta"}],
    }
    current = {
        "characters": [
            {
                "id": "char_1",
                "name": "Clara",
                "outfit": "casaco azul",
                "hair": "cabelo preso",
            }
        ],
        "carried_objects": [],
        "action": "Ela olha para a porta",
    }

    issues = compare_continuity_states(previous, current)

    assert issues[0]["issue_code"] == "object_disappeared"
    assert issues[0]["severity"] == "error"


def test_compare_continuity_states_allows_explained_object_exit() -> None:
    previous = {"characters": [], "carried_objects": [{"id": "prop_1", "name": "carta"}]}
    current = {"characters": [], "carried_objects": [], "action": "Ela entrega a carta"}

    assert compare_continuity_states(previous, current) == []


def test_check_timeline_integrity_detects_video_gap() -> None:
    issues = check_timeline_integrity([(0, 1000, "video"), (1500, 2000, "video")])

    assert issues[0]["issue_code"] == "timeline_gap"
