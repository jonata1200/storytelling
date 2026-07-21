from app.providers.llm.types import LLMRequest, LLMResult
from app.video_generation.durations import video_clip_durations


def _expected_scene_count(target_duration_seconds: int) -> int:
    target_minutes = max(1, target_duration_seconds / 60)
    return max(5, min(24, int(round(target_minutes * 0.8))))


class MockLLMProvider:
    provider_name = "mock"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        generators = {
            "generate_story_ideas": self._story_ideas,
            "generate_script": self._script,
            "generate_scenes_and_shots": self._scenes_and_shots,
            "revise_script": self._revise_script,
            "director_agent_chat": self._director_agent_chat,
        }
        generator = generators.get(request.task)
        if generator is None:
            content = {"message": "Mock response", "task": request.task}
        else:
            content = generator(request.variables)
        return LLMResult(content=content, model=request.model, provider=self.provider_name)

    def _director_agent_chat(self, variables: dict) -> dict:
        section = str(variables.get("section") or "script")
        message = str(variables.get("message") or "").lower()
        context = variables.get("project_context", {})
        labels = {
            "script": "roteiro",
            "assets": "universo visual",
            "storyboard": "storyboard",
            "video": "montagem de vídeo",
        }
        if any(word in message for word in ("crie", "gere", "criar", "gerar")):
            guidance = (
                "Use o botão de geração no topo desta área; vou manter o contexto já aprovado."
            )
        elif any(word in message for word in ("melhor", "revise", "ajuste", "mude")):
            guidance = (
                "Eu sugiro priorizar clareza emocional, continuidade e um gancho visual forte."
            )
        else:
            guidance = "Posso revisar, propor alternativas ou indicar o próximo passo desta etapa."
        return {
            "message": (
                f"Estou acompanhando o {labels.get(section, section)}. {guidance} "
                f"O projeto tem atualmente {context.get('summary', 'conteúdo em desenvolvimento')}."
            )
        }

    def _story_ideas(self, variables: dict) -> dict:
        base_theme = str(variables.get("theme") or "tema livre criado pela IA")
        audience = str(variables.get("audience") or "publico geral")
        emotion = str(variables.get("primary_emotion") or "esperanca")
        count = int(variables.get("count") or 3)
        target_duration = float(variables.get("target_duration_minutes") or 5)
        selected_genre = str(variables.get("genre") or "").strip()
        genres = ["Drama", "Suspense", "Ficcao cientifica", "Romance", "Aventura"]
        emotions = ["Esperanca", "Curiosidade", "Tensao", "Melancolia", "Surpresa"]
        themes = [
            "uma promessa esquecida numa cidade pequena",
            "um sinal vindo de uma missao espacial perdida",
            "a verdade por tras de uma foto de familia",
            "um amor interrompido por uma escolha impossivel",
            "a ultima entrevista de uma artista anonima",
            "uma comunidade que decide apagar suas memorias",
            "um objeto herdado que muda de dono a cada mentira",
            "uma crianca que reconhece uma casa onde nunca esteve",
            "um restaurante que so abre para despedidas",
            "uma mensagem de voz entregue dez anos tarde demais",
        ]
        return {
            "ideas": [
                {
                    "title": f"Ideia {index:02d}: {themes[(index - 1) % len(themes)].title()}",
                    "theme": (
                        themes[(index - 1) % len(themes)]
                        if base_theme == "tema livre criado pela IA"
                        else f"{base_theme} por um angulo {index}"
                    ),
                    "genre": (
                        selected_genre
                        if selected_genre and selected_genre != "genero livre criado pela IA"
                        else genres[(index - 1) % len(genres)]
                    ),
                    "primary_emotion": emotions[(index - 1) % len(emotions)],
                    "duration_minutes": max(5, min(25, target_duration)),
                    "hook": "Ela encontra uma mensagem que muda tudo nos primeiros segundos.",
                    "premise": (
                        "Uma pessoa comum precisa encarar uma revelacao inesperada "
                        f"diante de {audience}."
                    ),
                    "protagonist": "Clara, uma cuidadora exausta mas resiliente",
                    "protagonist_desire": "Consertar uma promessa quebrada",
                    "emotional_need": "Perdoar a si mesma",
                    "conflict": "A verdade chega tarde demais",
                    "obstacles": ["falta de tempo", "culpa antiga", "uma decisao familiar dificil"],
                    "stakes": "Perder a ultima chance de reparacao",
                    "twist": "A pessoa que parecia culpada estava protegendo Clara",
                    "climax": "Clara escolhe contar a verdade em publico",
                    "payoff": "Clara transforma a mensagem atrasada em um gesto de reparacao",
                    "resolution": "A familia se reconcilia sem apagar a dor",
                    "final_emotion": emotion,
                    "retention_potential": min(95, 75 + index),
                    "cliche_risk": 20 + index,
                    "production_complexity": 25 + index,
                    "estimated_production_cost": "low",
                }
                for index in range(1, count + 1)
            ]
        }

    def _script(self, variables: dict) -> dict:
        idea = variables.get("idea", {})
        contract = variables.get("narrative_contract", {})
        title = str(idea.get("title") or contract.get("title") or "Historia")
        language = str(variables.get("language") or "pt-BR")
        target_duration_seconds = int(variables.get("target_duration_seconds") or 240)
        scene_count = int(
            variables.get("expected_scene_count")
            or _expected_scene_count(target_duration_seconds)
        )
        scene_templates = [
            (
                "INT. CASA DA FAMILIA - FIM DE TARDE",
                "A sala simples respira poeira e luz fria. Fotografias antigas cobrem a mesa. "
                "CLARA, exausta mas atenta, encontra uma carta azul escondida atras de um "
                "porta-retratos rachado.\n\nCLARA\nIsso nao podia estar aqui.",
            ),
            (
                "EXT. RUA ESTREITA - NOITE",
                "Postes falham sobre o asfalto molhado. Clara atravessa a rua com a carta "
                "dobrada no bolso do casaco, seguindo uma pista que a familia sempre evitou.",
            ),
            (
                "INT. SALA DA FAMILIA - MADRUGADA",
                "A carta aberta repousa sob a luz de um abajur. A parede de fotografias vira "
                "um tribunal silencioso enquanto Clara entende uma nova camada da verdade.",
            ),
            (
                "INT. CASA DA FAMILIA - AMANHECER",
                "A mesma sala ganha luz quente. Clara encara a fotografia restaurada e decide "
                "que a proxima conversa nao sera adiada outra vez.",
            ),
            (
                "EXT. FRENTE DA CASA - MANHA",
                "Clara sai com a carta no bolso. A porta permanece aberta atras dela, como se "
                "a casa finalmente respirasse junto.",
            ),
        ]
        scenes = []
        for index in range(scene_count):
            slugline, action = scene_templates[index % len(scene_templates)]
            bridge = (
                "\n\nA escolha anterior muda o peso da cena, acrescentando uma virada "
                "emocional antes do proximo passo."
                if index >= len(scene_templates)
                else ""
            )
            ending = "\n\nFADE OUT." if index == scene_count - 1 else ""
            scenes.append(
                f"CENA {index + 1:02d}\n{slugline}\n\n{action}{bridge}{ending}"
            )
        content = "\n\n".join([f"TITULO: {title}", "FADE IN:", *scenes])
        return {
            "title": title,
            "language": language,
            "target_duration_seconds": target_duration_seconds,
            "word_count": len(content.split()),
            "content": content,
            "production_plan": self._scenes_and_shots(variables),
        }

    def _revise_script(self, variables: dict) -> dict:
        current_script = str(variables.get("current_script") or "")
        instruction = str(variables.get("instruction") or "ajuste solicitado")
        language = str(variables.get("language") or "pt-BR")
        target_duration_seconds = int(variables.get("target_duration_seconds") or 300)
        content = (
            current_script.strip()
            + "\n\nCENA 06\n"
            + "INT. CASA DA FAMILIA - MANHA\n\n"
            + f"A revisao ganha corpo em uma acao simples: {instruction.strip().capitalize()}. "
            + "A cena preserva o conflito principal e deixa a emocao aparecer no gesto."
        ).strip()
        return {
            "title": str(variables.get("title") or "Roteiro revisado"),
            "language": language,
            "target_duration_seconds": target_duration_seconds,
            "word_count": len(content.split()),
            "content": content,
        }

    def _scenes_and_shots(self, variables: dict) -> dict:
        total_duration = int(variables.get("target_duration_seconds") or 240)
        durations = video_clip_durations(total_duration)
        scene_count = int(
            variables.get("expected_scene_count") or _expected_scene_count(total_duration)
        )
        base_scene_specs = [
            ("O gancho", "Uma pista rompe a rotina da protagonista.", "curiosidade"),
            ("A busca", "Ela segue rastros que a familia evitava.", "ansiedade"),
            ("A revelacao", "O segredo muda o sentido do abandono.", "choque"),
            ("A escolha", "A protagonista precisa agir apesar do medo.", "coragem"),
            ("O payoff", "A verdade permite uma reconciliacao possivel.", "catarse"),
        ]
        scene_specs = [
            (
                f"{base_scene_specs[index % len(base_scene_specs)][0]} {index + 1}",
                base_scene_specs[index % len(base_scene_specs)][1],
                base_scene_specs[index % len(base_scene_specs)][2],
            )
            for index in range(scene_count)
        ]
        grouped: list[list[int]] = [[] for _ in scene_specs]
        for index, duration in enumerate(durations):
            scene_index = min((index * len(scene_specs)) // len(durations), len(scene_specs) - 1)
            grouped[scene_index].append(duration)
        return {
            "scenes": [
                {
                    "scene_number": index,
                    "title": title,
                    "summary": summary,
                    "duration_seconds": sum(scene_durations),
                    "shots": [
                        {
                            "shot_number": shot_index,
                            "duration_seconds": duration,
                            "narration_text": summary,
                            "dialogue_text": "",
                            "action": "Apresentar informacao visual essencial em tomada curta.",
                            "emotion": emotion,
                            "visual_composition": (
                                "Plano vertical 9:16 com rosto, objeto narrativo, "
                                "ambiente reconhecivel e luz consistente."
                            ),
                            "camera_movement": "push-in lento e realista",
                            "generation_type": "CAMERA_ZOOM",
                        }
                        for shot_index, duration in enumerate(scene_durations, 1)
                    ],
                }
                for index, ((title, summary, emotion), scene_durations) in enumerate(
                    zip(scene_specs, grouped, strict=True), 1
                )
                if scene_durations
            ]
        }
