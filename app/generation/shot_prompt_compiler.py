import re
from dataclasses import dataclass

from app.generation.shot_generation_spec import ShotGenerationSpec

VIBES_SHOT_PROMPT_COMPILER_VERSION = "vibes_shot_v13_no_camera_no_plans_no_lighting"
VIDEO_PROMPT_MAX_CHARS = 420

# Legado dos compiladores v10/v11 (câmera/enquadramento). Desde a v12 o
# compilador NÃO fala de planos ou movimentos de câmera: o modelo de vídeo
# define a cobertura sozinho — direções de câmera viravam placeholder genérico
# ("A câmera movimento curto e realista." em 38/38 shots). Os conjuntos
# permanecem exportados para compatibilidade com consumidores irmãos.

# Placeholder que a decupagem antiga gravava em 100% dos shots: não é direção
# de câmera, é ruído — a linha de câmera é omitida quando o valor é este ou
# vazio/estático.
GENERIC_CAMERA_MOVEMENTS = {
    "movimento curto e realista",
    "movimento de câmera curto e realista",
    "câmera curto e realista",
    # Placeholder do antigo setdefault da normalização (shots persistidos
    # antes da v11 podem carregá-lo): igualmente ruído, não é direção real.
    "movimento suave e realista",
}

_CAMERA_MOVEMENT_TRANSLATIONS = {
    "static": "fica parada",
    "locked": "fica parada",
    "locked off": "fica parada",
    "handheld": "acompanha a ação com um movimento leve de câmera na mão",
    "dolly in": "se aproxima devagar",
    "push in": "se aproxima devagar",
    "zoom in": "se aproxima devagar",
    "dolly out": "se afasta devagar",
    "pull out": "se afasta devagar",
    "zoom out": "se afasta devagar",
    "pan left": "gira para a esquerda",
    "pan right": "gira para a direita",
    "tilt up": "se inclina para cima",
    "tilt down": "se inclina para baixo",
    "tracking shot": "acompanha o personagem",
    "lateral tracking": "acompanha a ação lateralmente",
    "orbit": "contorna o personagem",
}


def natural_camera_movement(value: object) -> str:
    movement = " ".join(str(value or "").split()).strip().rstrip(". ")
    return _CAMERA_MOVEMENT_TRANSLATIONS.get(movement.casefold(), movement)


# Direções de câmera/planos embutidas no TEXTO da ação (decupagem/LLM legado
# gravavam "A câmera se aproxima em *slow motion*: ..."). Desde a v12 o
# prompt de vídeo não fala de planos ou movimento de câmera: o modelo decide
# a cobertura sozinho. Mesma família do limpador de frames
# (_CAMERA_DIRECTION_RE em continuous_frames.py), aplicada à ACTION.
_CAMERA_PHRASE_RE = re.compile(
    r"(?i)[^.!?\n]*(?:\b[aâ]mera\b|\bslow\s?motion\b|\bzoom\b|\bpan(or[âa]mic[ao])?\b"
    r"|\btilt\b|\bdolly\b|\btravelling\b|\bclose[-\s]?up\b"
    r"|\bplano\s+(?:geral|americano|m[ée]dio|detalh?[eo]|fechado|aberto|pr[óo]ximo)\b"
    r"|\bprimeiro\s+plano\b|\bgrande\s+plano\b|\bcontra[-\s]?plano\b)[^.!?\n]*[.!?]?",
)


def strip_camera_directions(action: str) -> str:
    """Remove frases de direção de câmera/plano da ação do vídeo.

    Frases que MENCIONAM o objeto câmera como elemento da cena ("ELIAS ajusta
    a câmera do celular") podem conter "câmera" sem ser direção; para não
    devorar ação legítima, só removemos frases onde a câmera é o SUJEITO da
    ação (começa com "A câmera"/"Câmera") ou o termo técnico abre a frase.
    """
    text = " ".join(str(action or "").split()).strip()
    if not text:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    for sentence in sentences:
        stripped = sentence.strip()
        if not stripped:
            continue
        lowered = stripped.casefold()
        starts_with_camera = lowered.startswith(
            ("a câmera", "a camera", "câmera", "camera", "cámara", "slow motion", "slow-motion")
        )
        if starts_with_camera:
            # Câmera é o sujeito: frase inteira é direção → descartar.
            continue
        kept.append(stripped)
    if not kept:
        return text  # não devolver vazio; ação original é melhor que nada
    return " ".join(kept)


def human_list(values: list[str]) -> str:
    items = [str(item).strip() for item in values if str(item).strip()]
    if len(items) < 2:
        return items[0] if items else ""
    return f"{', '.join(items[:-1])} e {items[-1]}"


# Períodos que a decupagem colava no fim do location ("Rua do Bairro - Amanhecer").
_LOCATION_PERIOD_TAIL_RE = re.compile(
    r"\s*[-\u2013]\s*(?:DIA|NOITE|TARDE|MANH[ÃA]|MADRUGADA|AMANHECER|ENTARDECER|"
    r"MEIO[- ]?DIA|ANOITECER|FIM DE TARDE|IN[IÍ]CIO DA NOITE|ALTA NOITE|"
    r"CREP[UÚ]SCULO|CONT[IÍ]NUO)\s*$",
    flags=re.IGNORECASE,
)


def _clean_compiled_location(value: object) -> str:
    """Local canônico para o prompt de vídeo: sem INT./EXT. e sem período."""
    name = str(value or "").strip()
    if not name:
        return ""
    name = re.sub(r"(?i)^(?:INT|EXT|INT/EXT|EXT/INT)\.?\s*", "", name)
    while True:
        stripped = _LOCATION_PERIOD_TAIL_RE.sub("", name).strip(" -–")
        if stripped == name:
            break
        name = stripped
    name = re.sub(r"\s+", " ", name).strip()
    # Casing natural quando o valor veio em caixa alta da slugline
    # ("RUA DO BAIRRO" -> "Rua do Bairro"); preserva nomes já capitalizados.
    from app.core.title_case import standardize_title_case

    return standardize_title_case(name)


def compact_text(value: object, max_chars: int) -> str:
    """Normalize and limit a detail without cutting through a word."""
    text = " ".join(str(value or "").split()).strip().rstrip(". ")
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{clipped or text[: max_chars - 1].rstrip()}…"


def bounded_prompt(parts: list[str], max_chars: int = VIDEO_PROMPT_MAX_CHARS) -> str:
    """Keep the highest-priority complete sentences that fit the prompt budget."""
    selected: list[str] = []
    for part in parts:
        clean = " ".join(str(part or "").split()).strip()
        if not clean:
            continue
        candidate = " ".join([*selected, clean])
        if len(candidate) <= max_chars:
            selected.append(clean)
    return " ".join(selected)


@dataclass(frozen=True)
class CompiledShotPrompt:
    prompt: str
    compiler_version: str


class VibesPromptCompiler:
    version = VIBES_SHOT_PROMPT_COMPILER_VERSION

    def compile(
        self,
        spec: ShotGenerationSpec,
        *,
        rejection_note: str | None = None,
    ) -> CompiledShotPrompt:
        action = compact_text(strip_camera_directions(spec.action) or spec.action, 190)
        # Local canônico: sem prefixo INT./EXT. e sem período colado
        # ("Rua do Bairro - Amanhecer" -> "Rua do Bairro"); casing natural.
        location = compact_text(_clean_compiled_location(spec.location), 80)
        action_context = (
            f"Em {location}, {action}."
            if location and location.casefold() not in action.casefold()
            else f"{action}."
        )
        lines = [action_context]
        # Só menciona coadjuvantes quando a ação deixa claro quem está em cena e
        # a lista é curta: listar todo elenco não citado ("Voz Gravada e Corte
        # Para: também estão em cena") gera elementos desconexos no vídeo.
        missing_characters = [
            name for name in spec.characters[:4] if name.casefold() not in action.casefold()
        ]
        if 0 < len(missing_characters) <= 2:
            verb = "está" if len(missing_characters) == 1 else "estão"
            lines.append(f"{human_list(missing_characters)} também {verb} em cena.")
        missing_props = [
            item for item in spec.props[:3] if item.casefold() not in action.casefold()
        ]
        if missing_props:
            lines.append(f"Objetos importantes: {compact_text(human_list(missing_props), 80)}.")
        # v12: NADA de Enquadramento/planos, "A câmera ..." nem "Iluminação:" —
        # o modelo de vídeo decide cobertura, movimento e luz sozinho. A linha
        # de iluminação virava ruído repetitivo (\"Iluminação: luz externa.\" em
        # quase todo segmento) e não acrescenta informação à ação.
        if rejection_note:
            lines.append(f"Ajuste: {compact_text(rejection_note, 100)}.")
        prompt = bounded_prompt(lines)
        return CompiledShotPrompt(prompt=prompt, compiler_version=self.version)
