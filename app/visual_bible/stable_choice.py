"""Escolha estável e determinística por semente (INC-04).

Implementação única usada tanto pelos presets de locais (``_seeded_choice``)
quanto pelos defaults de personagens (``_stable_character_choice``). As duas
implementações eram idênticas (sha1 de ``f"{seed}:{offset}"`` % len) e viviam
duplicadas; qualquer correção precisava ser feita duas vezes.
"""

import hashlib


def stable_choice(seed: str, options: list[str] | tuple[str, ...], offset: int = 0) -> str:
    """Return a deterministic option for ``seed``, stable across runs.

    SEC-06: sha1 aqui é derivador determinístico (escolha estável de defaults),
    não uso criptográfico — ``usedforsecurity=False`` registra isso.
    """
    digest = hashlib.sha1(f"{seed}:{offset}".encode(), usedforsecurity=False).hexdigest()
    return options[int(digest[:8], 16) % len(options)]