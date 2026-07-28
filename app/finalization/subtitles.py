def milliseconds_to_srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_srt_from_alignment(alignment: dict, max_words_per_caption: int = 7) -> str:
    words = alignment.get("words", [])
    if not words:
        return ""

    captions: list[str] = []
    for index in range(0, len(words), max_words_per_caption):
        chunk = words[index : index + max_words_per_caption]
        start_ms = int(chunk[0]["start_ms"])
        end_ms = int(chunk[-1]["end_ms"])
        text = " ".join(str(item["word"]) for item in chunk)
        captions.append(
            "\n".join(
                [
                    str(len(captions) + 1),
                    f"{milliseconds_to_srt_timestamp(start_ms)} --> "
                    f"{milliseconds_to_srt_timestamp(end_ms)}",
                    text,
                    "",
                ]
            )
        )
    return "\n".join(captions)


def safe_area_profile() -> dict:
    return {
        "top_percent": 10,
        "bottom_percent": 18,
        "left_percent": 8,
        "right_percent": 8,
    }
