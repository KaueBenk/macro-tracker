import unicodedata


def normalize_search_text(*parts: str | None) -> str:
    value = " ".join(part.strip() for part in parts if part and part.strip())
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(without_marks.lower().split())


def search_terms(query: str) -> list[str]:
    return [term for term in normalize_search_text(query).split(" ") if term]
