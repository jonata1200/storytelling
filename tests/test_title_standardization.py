"""Testes da padronização de caixa dos títulos da história."""

from app.ui.shared.page_config import clean_idea_title, standardize_title_case


def test_standardize_title_case_converts_all_caps_to_title_case() -> None:
    assert standardize_title_case("O ÚLTIMO SINAL") == "O Último Sinal"
    assert standardize_title_case("A CHAVE PERDIDA DO TÚNEL") == "A Chave Perdida do Túnel"


def test_standardize_title_case_keeps_minor_words_lowercase() -> None:
    assert standardize_title_case("uma comunidade em silêncio") == "Uma Comunidade em Silêncio"
    assert standardize_title_case("carta ao lado") == "Carta ao Lado"


def test_standardize_title_case_recapitalizes_after_colon_and_dash() -> None:
    assert standardize_title_case("o trem das 6: a última viagem") == (
        "O Trem das 6: A Última Viagem"
    )
    assert standardize_title_case("sinal perdido - o despertar") == (
        "Sinal Perdido - O Despertar"
    )


def test_standardize_title_case_preserves_acronyms() -> None:
    assert standardize_title_case("TV e o mistério da UF perdida") == (
        "TV e o Mistério da UF Perdida"
    )


def test_standardize_title_case_mixed_case_is_capitalized_normally() -> None:
    assert standardize_title_case("uma fotografia muda cada vez que é limpa") == (
        "Uma Fotografia Muda Cada Vez que É Limpa"
    )


def test_standardize_title_case_handles_empty_values() -> None:
    assert standardize_title_case("") == ""
    assert standardize_title_case(None, "Fallback") == "Fallback"
    assert standardize_title_case("   ") == ""


def test_clean_idea_title_standardizes_case() -> None:
    # O prefixo "Ideia NN:" é removido antes da padronização.
    assert clean_idea_title("IDEIA 02 - O TREM DAS SEIS") == "O Trem das Seis"
    assert clean_idea_title("Ideia 06: UMA COMUNIDADE") == "Uma Comunidade"
    assert clean_idea_title("") == "História sem título"