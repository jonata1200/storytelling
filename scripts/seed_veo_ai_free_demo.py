"""Create a demo project ready to exercise Veo AI Free image/video flows."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ArtifactStatus, ArtifactType, DependencyKind, ProjectStatus
from app.database.session import AsyncSessionLocal
from app.production.models import ProjectProductionSettings
from app.projects.models import Artifact, ArtifactVersion, Project, ProjectVersion
from app.storyboards.prompts import _prompt_hash
from app.storytelling.models import Briefing, Scene, Script, ScriptVersion, Shot, StoryIdea
from app.visual_bible.models import (
    Character,
    CharacterVersion,
    Location,
    LocationVersion,
    Prop,
    PropVersion,
)
from app.workflows.models import ArtifactDependency

DEMO_TITLE = "Teste Veo AI Free - O Ultimo Farol"


@dataclass(frozen=True)
class ShotSeed:
    scene_number: int
    shot_number: int
    duration_seconds: int
    narration_text: str
    dialogue_text: str
    action: str
    emotion: str
    visual_composition: str
    camera_movement: str
    generation_type: str
    storyboard_prompt: str


def _script_content() -> str:
    return "\n".join(
        [
            "Titulo: O Ultimo Farol",
            "",
            "Cena 1 - O sinal na chuva",
            "Lia chega ao topo de um predio abandonado enquanto uma tempestade eletrica",
            "varre a cidade. No centro do terraço, o Farol Orbital pulsa como uma pequena lua",
            "presa em metal antigo. Téo, seu robo assistente, tenta estabilizar o sinal.",
            'TEO: "O farol esta respondendo a uma frequencia que nao existe mais."',
            'LIA: "Entao alguem esta chamando de antes do apagao."',
            "",
            "Cena 2 - A mensagem",
            "O projetor de placas quebradas acende e mostra uma gravacao de Lia, dez anos",
            "mais velha, com cicatrizes de luz no rosto. A versao futura pede que ela nao",
            "desligue o farol, mesmo que toda a cidade pareca pedir o contrario.",
            'LIA FUTURA: "Se voce apagar essa luz, ninguem vai lembrar que conseguimos voltar."',
            "Lia toca a esfera, e o teto inteiro se transforma num mapa de rotas orbitais.",
            "",
            "Cena 3 - A escolha",
            "O nucleo aquece e as antenas do farol apontam para o ceu. Téo entrega a Lia",
            "a chave de cobre que pode destruir o aparelho ou abrir a transmissao. Ela respira,",
            "olha para a cidade escura e encaixa a chave no modo de envio.",
            'LIA: "Que todo mundo veja a luz."',
            "O farol dispara uma coluna azul para as nuvens, reacendendo janelas uma a uma.",
        ]
    )


def _story_idea_payload() -> dict[str, Any]:
    return {
        "id": "veo-free-demo-farol",
        "title": "O Ultimo Farol",
        "hook": "Uma tecnica encontra uma mensagem dela mesma vinda de um futuro apagado.",
        "premise": (
            "Em uma cidade sem memoria digital, Lia precisa decidir se preserva o ultimo "
            "sinal orbital ou se destrói a tecnologia que causou o colapso."
        ),
        "protagonist": "Lia, engenheira de transmissoes e guardia de antenas antigas",
        "protagonist_desire": "provar que ainda existe uma rota de retorno para a cidade",
        "emotional_need": "confiar no proprio futuro sem abandonar quem esta no presente",
        "stakes": "se o farol apagar, a cidade perde a unica prova de que sobreviveu",
        "resolution": "Lia escolhe transmitir a mensagem e reacende a rede urbana",
    }


def _character_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": "Lia Azevedo",
            "role": "protagonista",
            "age": "28 anos",
            "body_type": "estatura media, postura alerta, movimentos precisos",
            "hair": "cabelo preto curto, molhado pela chuva, mechas grudadas na testa",
            "eyes": "olhos castanho-escuros atentos, reflexos azulados do farol",
            "base_outfit": (
                "jaqueta tecnica grafite com faixas refletivas, camiseta cinza, calca cargo "
                "preta, botas gastas, luvas de manutencao"
            ),
            "palette": "grafite, azul eletrico, cobre envelhecido",
            "lighting": "luz de tempestade, reflexos frios e brilho azul pulsante",
            "canonical_prompt": (
                "Retrato cinematografico vertical 9:16 de Lia Azevedo, jovem engenheira "
                "brasileira de transmissoes, 28 anos, cabelo preto curto molhado pela chuva, "
                "olhos castanho-escuros com reflexo azul, jaqueta tecnica grafite com faixas "
                "refletivas, camiseta cinza, calca cargo preta, botas gastas e luvas de "
                "manutencao. Expressao determinada e vulneravel, pele realista, textura de "
                "chuva, luz azul do Farol Orbital vindo de baixo, fundo de terraco urbano "
                "noturno, estilo cinematografico realista, alta continuidade de rosto e roupa, "
                "sem texto, sem logo, sem distorcao."
            ),
        },
        {
            "name": "Téo",
            "role": "assistente robo",
            "age": "aparencia de robo compacto",
            "body_type": "robo pequeno de manutencao, corpo arredondado, bracos articulados",
            "hair": "sem cabelo, casco branco fosco com marcas de uso",
            "eyes": "visor circular verde com expressao luminosa simples",
            "base_outfit": "carcaca branca, juntas pretas, mochila de ferramentas magnetica",
            "palette": "branco fosco, verde neon suave, metal escovado",
            "lighting": "reflexos de chuva e pequenos LEDs internos",
            "canonical_prompt": (
                "Design de personagem para Téo, robo assistente pequeno de manutencao, corpo "
                "arredondado branco fosco com arranhoes, bracos articulados finos, visor circular "
                "verde expressivo, mochila magnetica de ferramentas, juntas pretas, escala menor "
                "que uma pessoa adulta. Aparencia amigavel mas utilitaria, realismo "
                "cinematografico, luz de chuva noturna e reflexos azuis, detalhes tecnicos "
                "legiveis, sem texto, sem logo, sem elementos extras."
            ),
        },
        {
            "name": "Lia Futura",
            "role": "mensagem holografica",
            "age": "38 anos",
            "body_type": "mesma silhueta de Lia, postura cansada e urgente",
            "hair": "cabelo preto mais comprido preso de forma improvisada",
            "eyes": "olhos castanhos com brilho digital instavel",
            "base_outfit": "casaco escuro rasgado, marcas luminosas no rosto e no pescoço",
            "palette": "azul holografico, preto queimado, prata",
            "lighting": "projecao translúcida com falhas e ruido visual",
            "canonical_prompt": (
                "Holograma cinematografico vertical 9:16 de Lia Futura, a mesma mulher de Lia "
                "dez anos mais velha, cabelo preto preso de forma improvisada, rosto cansado "
                "com cicatrizes finas de luz azul, casaco escuro rasgado, olhar urgente. "
                "Corpo semi-transparente com ruido digital sutil, contornos azuis, projetado "
                "por placas quebradas em ambiente noturno chuvoso. Manter identidade parecida "
                "com Lia, realista, dramatico, sem texto, sem legenda, sem artefatos estranhos."
            ),
        },
    ]


def _location_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": "Terraco da torre de transmissoes",
            "description": (
                "Topo de predio abandonado com antenas tortas, cabos molhados, poças e vista "
                "para uma cidade apagada."
            ),
            "layout": "espaco aberto vertical, bordas baixas, antenas em silhueta",
            "lighting": "noite chuvosa, relampagos distantes, luz azul do farol",
            "palette": "concreto frio, metal escuro, azul eletrico, amarelos urbanos distantes",
            "canonical_prompt": (
                "Cenario cinematografico vertical 9:16: terraco de uma torre de transmissoes "
                "abandonada durante chuva noturna, antenas tortas, cabos molhados, poças "
                "refletindo luz azul, skyline de cidade apagada ao fundo, concreto desgastado, "
                "vento forte, atmosfera sci-fi realista brasileira, profundidade espacial clara, "
                "sem pessoas, sem texto, sem logotipos."
            ),
        },
        {
            "name": "Sala do Farol Orbital",
            "description": (
                "Nucleo tecnico no topo da torre, com esfera luminosa, placas de controle "
                "quebradas e mapas orbitais projetados."
            ),
            "layout": "sala circular pequena, maquina central, paineis em meia-lua",
            "lighting": "brilho azul vindo da esfera e luzes vermelhas de alerta",
            "palette": "azul plasma, cobre antigo, preto, vermelho de emergencia",
            "canonical_prompt": (
                "Interior sci-fi realista vertical 9:16 da Sala do Farol Orbital, sala circular "
                "no topo de uma torre, esfera central azul brilhante suspensa em estrutura de "
                "cobre antigo, paineis quebrados em meia-lua, mapas orbitais holograficos no ar, "
                "cabos e condensacao, luz azul forte com pequenos alertas vermelhos, ambiente "
                "filmavel e coerente, sem personagens, sem texto legivel, sem interface falsa."
            ),
        },
    ]


def _prop_profiles() -> list[dict[str, Any]]:
    return [
        {
            "name": "Farol Orbital",
            "narrative_importance": "maquina que guarda a ultima rota de retorno da cidade",
            "material": "cobre envelhecido, vidro grosso, nucleo de plasma azul",
            "color": "cobre escuro com luz azul intensa",
            "canonical_prompt": (
                "Objeto heroico para cinema sci-fi: Farol Orbital, esfera de vidro grosso com "
                "nucleo de plasma azul pulsante, presa em aneis de cobre envelhecido e metal "
                "escuro, cabos finos, marcas de ferrugem e gotas de chuva. Deve parecer antigo "
                "e tecnologico ao mesmo tempo, legivel como prop central, luz volumetrica azul, "
                "fundo neutro escuro, sem texto, sem logo, sem maos."
            ),
        },
        {
            "name": "Chave de Cobre",
            "narrative_importance": (
                "objeto que decide entre destruir o farol ou transmitir a mensagem"
            ),
            "material": "cobre oxidado, ceramica preta e filamentos luminosos",
            "color": "cobre, verde oxidado, pontos azuis",
            "canonical_prompt": (
                "Close cinematografico vertical 9:16 de uma Chave de Cobre futurista, pequena "
                "haste de cobre oxidado com sulcos, detalhes de ceramica preta e filamentos "
                "azuis acesos, marcas de uso, gotas de chuva, objeto narrativo importante, "
                "fundo escuro desfocado, escala clara na mao de uma engenheira, sem texto, "
                "sem logotipos, realista."
            ),
        },
    ]


def _shot_seeds() -> list[ShotSeed]:
    return [
        ShotSeed(
            1,
            1,
            5,
            "",
            "",
            "Lia sobe ao terraco sob chuva forte e encara o Farol Orbital apagado.",
            "tensao curiosa",
            "Plano vertical aberto, Lia pequena em primeiro terco inferior, antenas e ceu pesado.",
            "travelling lento de aproximacao",
            "image_to_video",
            (
                "Frame inicial vertical 9:16, cinematografico realista. Lia Azevedo chega ao "
                "terraco da torre de transmissoes sob chuva forte, jaqueta grafite molhada, "
                "antenas tortas em silhueta, cidade apagada ao fundo, Farol Orbital escuro no "
                "centro emitindo apenas um reflexo azul fraco. Composicao limpa para "
                "image-to-video, sem texto, sem logos, sem personagens extras."
            ),
        ),
        ShotSeed(
            1,
            2,
            5,
            "",
            'TEO: "O farol esta respondendo a uma frequencia que nao existe mais."',
            "Téo projeta uma grade verde enquanto o Farol Orbital começa a pulsar.",
            "alerta tecnico",
            "Plano medio com Téo em primeiro plano e Lia desfocada ao fundo olhando para a luz.",
            "pan suave da esquerda para a direita",
            "image_to_video",
            (
                "Frame inicial vertical 9:16. Téo, robo pequeno branco de manutencao com visor "
                "verde, projeta uma grade luminosa sobre cabos molhados no terraco. Ao fundo, "
                "Lia observa o Farol Orbital começando a pulsar em azul. Chuva, reflexos no "
                "concreto, atmosfera sci-fi realista, continuidade dos personagens, sem texto "
                "legivel, sem UI, sem marcas."
            ),
        ),
        ShotSeed(
            2,
            1,
            5,
            "",
            'LIA FUTURA: "Se voce apagar essa luz, ninguem vai lembrar que conseguimos voltar."',
            "A holografia de Lia Futura surge em falhas azuis diante de Lia.",
            "assombro e urgencia",
            "Plano contraplongée discreto, holograma maior que Lia, luz azul atravessando chuva.",
            "camera sobe lentamente acompanhando o holograma",
            "image_to_video",
            (
                "Frame inicial vertical 9:16 dentro da Sala do Farol Orbital. Holograma azul "
                "instavel de Lia Futura aparece diante de Lia Azevedo, mantendo rosto semelhante "
                "mas mais velho, cicatrizes de luz, casaco escuro rasgado. Lia observa em choque, "
                "Farol Orbital brilhando entre elas, mapas orbitais no ar, chuva nas janelas, "
                "sem texto, sem legenda, sem distorcao."
            ),
        ),
        ShotSeed(
            2,
            2,
            5,
            "",
            "",
            "Lia toca a esfera e um mapa de rotas orbitais ilumina toda a sala.",
            "descoberta",
            "Close nas luvas de Lia tocando o vidro azul com rotas refletidas no rosto.",
            "macro push-in muito suave",
            "image_to_video",
            (
                "Frame inicial vertical 9:16, close cinematografico das luvas de Lia tocando "
                "a esfera de vidro do Farol Orbital. O nucleo de plasma azul ilumina gotas de "
                "chuva, cobre envelhecido e reflexos de mapas orbitais no rosto parcialmente "
                "visivel de Lia. Profundidade rasa, textura realista, nenhum texto legivel, "
                "sem logo, foco no contato da mao com a esfera."
            ),
        ),
        ShotSeed(
            3,
            1,
            5,
            "",
            "",
            "Téo entrega a Chave de Cobre para Lia enquanto a maquina ameaça superaquecer.",
            "decisao contida",
            "Plano medio baixo, chave em foco entre Lia e Téo, alertas vermelhos ao fundo.",
            "dolly-in curto na chave",
            "image_to_video",
            (
                "Frame inicial vertical 9:16. Téo entrega a Chave de Cobre para Lia; a chave "
                "esta em foco no centro, com filamentos azuis acesos e gotas de chuva. Lia, "
                "com jaqueta grafite e luvas, estende a mao; atras deles, a Sala do Farol "
                "Orbital pisca em azul e vermelho. Realista, dramatico, sem texto, sem logos, "
                "continuidade de personagem e objeto."
            ),
        ),
        ShotSeed(
            3,
            2,
            5,
            "",
            'LIA: "Que todo mundo veja a luz."',
            "Lia encaixa a chave e o Farol Orbital dispara uma coluna azul para as nuvens.",
            "coragem e alivio",
            "Plano amplo vertical com Lia em silhueta, coluna de luz central e cidade reacendendo.",
            "tilt para cima acompanhando o feixe",
            "image_to_video",
            (
                "Frame inicial vertical 9:16, plano amplo cinematografico do terraco. Lia em "
                "silhueta encaixa a Chave de Cobre no Farol Orbital; uma coluna de luz azul "
                "sobe para nuvens de tempestade, janelas da cidade reacendem ao fundo, Téo ao "
                "lado em escala pequena. Composicao epica e limpa, luz volumetrica, chuva, sem "
                "texto, sem logos, sem multiplas cenas."
            ),
        ),
    ]


async def _create_artifact(
    session: AsyncSession,
    project_id: Any,
    artifact_type: ArtifactType,
    name: str,
    payload: dict[str, Any],
    *,
    status: ArtifactStatus = ArtifactStatus.READY_FOR_REVIEW,
    change_note: str = "Seed Veo AI Free demo",
) -> Artifact:
    artifact = Artifact(
        project_id=project_id,
        artifact_type=artifact_type,
        name=name,
        status=status,
    )
    session.add(artifact)
    await session.flush()
    session.add(
        ArtifactVersion(
            artifact_id=artifact.id,
            version_number=1,
            payload=payload,
            change_note=change_note,
        )
    )
    await session.flush()
    return artifact


async def _add_dependency(
    session: AsyncSession,
    upstream_artifact_id: Any,
    downstream_artifact_id: Any,
    kind: DependencyKind = DependencyKind.DERIVED_FROM,
) -> None:
    session.add(
        ArtifactDependency(
            upstream_artifact_id=upstream_artifact_id,
            downstream_artifact_id=downstream_artifact_id,
            dependency_kind=kind,
        )
    )


async def _seed_project(session: AsyncSession) -> Project:
    existing = await session.scalar(
        select(Project)
        .where(Project.title == DEMO_TITLE)
        .where(Project.deleted_at.is_(None))
        .limit(1)
    )
    if existing is not None:
        return existing

    project = Project(
        title=DEMO_TITLE,
        description=(
            "Projeto demo com roteiro, personagens, locais, objetos e prompts prontos "
            "para testar geracao de imagens e videos no Veo AI Free."
        ),
        status=ProjectStatus.VISUAL_BIBLE_APPROVAL,
    )
    session.add(project)
    await session.flush()
    session.add(
        ProjectVersion(
            project_id=project.id,
            version_number=1,
            snapshot={
                "title": project.title,
                "description": project.description,
                "seed": "veo_ai_free_demo",
            },
            change_note="Seed Veo AI Free demo",
        )
    )

    briefing_payload = {
        "theme": "memoria, coragem e tecnologia perdida",
        "audience": "publico jovem adulto que gosta de ficcao cientifica emocional",
        "genre": "sci-fi drama",
        "primary_emotion": "esperanca sob pressao",
        "emotional_intensity": 8,
        "ending_type": "esperancoso",
        "language": "pt-BR",
        "country_context": "Brasil urbano futurista",
        "desired_duration_minutes": 0.5,
        "has_narrator": False,
        "visual_style": "cinematografico realista, chuva noturna, luz azul e cobre",
        "content_objective": "testar continuidade visual e image-to-video",
        "call_to_action": "gerar imagens e clipes pelo Veo AI Free",
        "constraints": [
            "vertical 9:16",
            "sem texto dentro das imagens",
            "sem narrador",
            "clipes curtos de 5 segundos",
        ],
    }
    briefing_artifact = await _create_artifact(
        session,
        project.id,
        ArtifactType.BRIEFING,
        "Briefing - O Ultimo Farol",
        briefing_payload,
    )
    session.add(
        Briefing(
            project_id=project.id,
            artifact_id=briefing_artifact.id,
            theme=briefing_payload["theme"],
            audience=briefing_payload["audience"],
            genre=briefing_payload["genre"],
            primary_emotion=briefing_payload["primary_emotion"],
            emotional_intensity=briefing_payload["emotional_intensity"],
            ending_type=briefing_payload["ending_type"],
            language=briefing_payload["language"],
            country_context=briefing_payload["country_context"],
            desired_duration_minutes=Decimal("0.50"),
            has_narrator=False,
            visual_style=briefing_payload["visual_style"],
            content_objective=briefing_payload["content_objective"],
            call_to_action=briefing_payload["call_to_action"],
            constraints=briefing_payload["constraints"],
        )
    )

    idea_payload = _story_idea_payload()
    idea_artifact = await _create_artifact(
        session,
        project.id,
        ArtifactType.STORY_IDEA,
        "Ideia - O Ultimo Farol",
        idea_payload,
    )
    await _add_dependency(session, briefing_artifact.id, idea_artifact.id)
    story_idea = StoryIdea(
        project_id=project.id,
        artifact_id=idea_artifact.id,
        title=idea_payload["title"],
        hook=idea_payload["hook"],
        premise=idea_payload["premise"],
        protagonist=idea_payload["protagonist"],
        retention_potential=9,
        cliche_risk=3,
        production_complexity=4,
        payload=idea_payload,
    )
    session.add(story_idea)
    await session.flush()

    script_payload = {
        "title": "O Ultimo Farol",
        "language": "pt-BR",
        "target_duration_seconds": 30,
        "content": _script_content(),
    }
    script_artifact = await _create_artifact(
        session,
        project.id,
        ArtifactType.SCRIPT,
        "Roteiro - O Ultimo Farol",
        script_payload,
    )
    await _add_dependency(session, idea_artifact.id, script_artifact.id)
    script = Script(
        project_id=project.id,
        artifact_id=script_artifact.id,
        story_idea_id=story_idea.id,
        title="O Ultimo Farol",
        language="pt-BR",
        target_duration_seconds=30,
        word_count=len(_script_content().split()),
        content=_script_content(),
    )
    session.add(script)
    await session.flush()
    session.add(
        ScriptVersion(
            script_id=script.id,
            version_number=1,
            content=script.content,
            word_count=script.word_count,
            payload=script_payload,
        )
    )

    scenes: dict[int, Scene] = {}
    for scene_number, title, summary in [
        (
            1,
            "O sinal na chuva",
            "Lia e Téo encontram o Farol Orbital reagindo a uma frequencia impossivel.",
        ),
        (
            2,
            "A mensagem",
            "Uma versao futura de Lia pede que o farol nao seja apagado.",
        ),
        (
            3,
            "A escolha",
            "Lia decide transmitir a mensagem e reacende a cidade.",
        ),
    ]:
        scene_payload = {
            "scene_number": scene_number,
            "title": title,
            "summary": summary,
            "duration_seconds": 10,
        }
        scene_artifact = await _create_artifact(
            session,
            project.id,
            ArtifactType.SCENE,
            f"Cena {scene_number:02d} - {title}",
            scene_payload,
        )
        await _add_dependency(session, script_artifact.id, scene_artifact.id)
        scene = Scene(
            project_id=project.id,
            artifact_id=scene_artifact.id,
            script_id=script.id,
            scene_number=scene_number,
            title=title,
            summary=summary,
            duration_seconds=10,
            payload=scene_payload,
        )
        session.add(scene)
        await session.flush()
        scenes[scene_number] = scene

    shots: list[Shot] = []
    storyboard_prompt_overrides: dict[str, str] = {}
    storyboard_prompt_approvals: dict[str, str] = {}
    for seed in _shot_seeds():
        shot_payload = {
            "scene_number": seed.scene_number,
            "shot_number": seed.shot_number,
            "duration_seconds": seed.duration_seconds,
            "narration_text": seed.narration_text,
            "dialogue_text": seed.dialogue_text,
            "action": seed.action,
            "emotion": seed.emotion,
            "visual_composition": seed.visual_composition,
            "camera_movement": seed.camera_movement,
            "generation_type": seed.generation_type,
            "storyboard_prompt": seed.storyboard_prompt,
        }
        shot_artifact = await _create_artifact(
            session,
            project.id,
            ArtifactType.SHOT,
            f"Plano {seed.scene_number:02d}.{seed.shot_number:02d}",
            shot_payload,
        )
        await _add_dependency(session, scenes[seed.scene_number].artifact_id, shot_artifact.id)
        shot = Shot(
            project_id=project.id,
            artifact_id=shot_artifact.id,
            scene_id=scenes[seed.scene_number].id,
            shot_number=seed.shot_number,
            duration_seconds=seed.duration_seconds,
            narration_text=seed.narration_text,
            dialogue_text=seed.dialogue_text,
            action=seed.action,
            emotion=seed.emotion,
            visual_composition=seed.visual_composition,
            camera_movement=seed.camera_movement,
            generation_type=seed.generation_type,
            payload=shot_payload,
        )
        session.add(shot)
        await session.flush()
        shots.append(shot)
        storyboard_prompt_overrides[str(shot.id)] = seed.storyboard_prompt
        storyboard_prompt_approvals[str(shot.id)] = _prompt_hash(seed.storyboard_prompt)

    for profile in _character_profiles():
        artifact = await _create_artifact(
            session,
            project.id,
            ArtifactType.CHARACTER,
            f"Personagem - {profile['name']}",
            profile,
        )
        await _add_dependency(session, script_artifact.id, artifact.id)
        character = Character(
            project_id=project.id,
            artifact_id=artifact.id,
            name=profile["name"],
            role=profile["role"],
            canonical_profile=profile,
            character_fingerprint={
                "canonical_prompt": _prompt_hash(profile["canonical_prompt"]),
                "profile": _prompt_hash(json.dumps(profile, sort_keys=True, ensure_ascii=True)),
            },
        )
        session.add(character)
        await session.flush()
        session.add(
            CharacterVersion(
                character_id=character.id,
                version_number=1,
                canonical_profile=profile,
                change_note="Seed Veo AI Free demo",
            )
        )

    for profile in _location_profiles():
        artifact = await _create_artifact(
            session,
            project.id,
            ArtifactType.LOCATION,
            f"Local - {profile['name']}",
            profile,
        )
        await _add_dependency(session, script_artifact.id, artifact.id)
        location = Location(
            project_id=project.id,
            artifact_id=artifact.id,
            name=profile["name"],
            description=profile["description"],
            canonical_profile=profile,
        )
        session.add(location)
        await session.flush()
        session.add(
            LocationVersion(
                location_id=location.id,
                version_number=1,
                canonical_profile=profile,
                change_note="Seed Veo AI Free demo",
            )
        )

    for profile in _prop_profiles():
        artifact = await _create_artifact(
            session,
            project.id,
            ArtifactType.PROP,
            f"Objeto - {profile['name']}",
            profile,
        )
        await _add_dependency(session, script_artifact.id, artifact.id)
        prop = Prop(
            project_id=project.id,
            artifact_id=artifact.id,
            name=profile["name"],
            narrative_importance=profile["narrative_importance"],
            canonical_profile=profile,
        )
        session.add(prop)
        await session.flush()
        session.add(
            PropVersion(
                prop_id=prop.id,
                version_number=1,
                canonical_profile=profile,
                change_note="Seed Veo AI Free demo",
            )
        )

    session.add(
        ProjectProductionSettings(
            project_id=project.id,
            content_type="short_drama",
            aspect_ratio="9:16",
            image_resolution="1080x1920",
            video_resolution="1080x1920",
            workflow_mode="keyframes_i2v",
            image_model="veo-ai-free/image",
            video_model="veo-ai-free/video",
            audio_mode="dialogue_only",
            motion_intensity=5,
            metadata_json={
                "seed": "veo_ai_free_demo",
                "storyboard_prompt_overrides": {
                    str(script.id): storyboard_prompt_overrides,
                },
                "storyboard_prompt_approvals": {
                    str(script.id): storyboard_prompt_approvals,
                },
            },
        )
    )

    await session.commit()
    await session.refresh(project)
    return project


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--title",
        default=DEMO_TITLE,
        help="Expected demo project title. Used only as a safety check.",
    )
    args = parser.parse_args()
    if args.title != DEMO_TITLE:
        raise SystemExit(f"Este seed cria apenas o projeto: {DEMO_TITLE}")

    async with AsyncSessionLocal() as session:
        project = await _seed_project(session)
        print(f"Projeto demo disponivel: {project.title}")
        print(f"ID: {project.id}")
        print("Conteudo: roteiro, 3 personagens, 2 locais, 2 objetos e 6 prompts de storyboard.")


if __name__ == "__main__":
    asyncio.run(main())
