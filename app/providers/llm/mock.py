from app.providers.llm.types import LLMRequest, LLMResult


class MockLLMProvider:
    provider_name = "mock"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        generators = {
            "generate_story_ideas": self._story_ideas,
            "generate_story_bible": self._story_bible,
            "generate_script": self._script,
            "generate_scenes_and_shots": self._scenes_and_shots,
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
        genres = ["Drama", "Suspense", "Ficcao cientifica", "Romance", "Documentario"]
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
                    "duration_minutes": max(3, min(8, target_duration)),
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

    def _story_bible(self, variables: dict) -> dict:
        idea = variables.get("idea", {})
        title = str(idea.get("title") or "Historia sem titulo")
        return {
            "title": title,
            "logline": str(idea.get("premise") or "Uma historia emocional de reparacao."),
            "theme": variables.get("theme", "reparacao"),
            "genre": variables.get("genre", "drama emocional"),
            "tone": "intimo, humano e progressivamente catartico",
            "target_emotion": variables.get("primary_emotion", "esperanca"),
            "audience": variables.get("audience", "publico geral"),
            "world_rules": ["realismo contemporaneo", "conflitos resolvidos por escolhas humanas"],
            "visual_style": {"format": "vertical 9:16", "palette": ["azul frio", "dourado quente"]},
            "narrative_rules": [
                "gancho imediato",
                "microgancho a cada cena",
                "payoff emocional claro",
            ],
            "forbidden_elements": ["reviravolta aleatoria", "exposicao longa"],
            "characters": [
                {
                    "id": "char_protagonist",
                    "name": str(idea.get("protagonist", "Protagonista")),
                    "role": "protagonista",
                    "arc": str(idea.get("emotional_need", "mudanca emocional")),
                }
            ],
            "locations": [
                {"id": "loc_home", "name": "Casa da familia", "mood": "memoria e tensao"}
            ],
            "props": [{"id": "prop_reveal", "name": "objeto de revelacao", "importance": "payoff"}],
            "timeline": [],
            "relationships": [],
            "continuity_rules": ["manter roupas consistentes por sequencia"],
            "audio_style": {"narration": "voz calorosa e contida", "music": "piano discreto"},
            "export_profile": {"aspect_ratio": "9:16", "resolution": "1080x1920"},
        }

    def _script(self, variables: dict) -> dict:
        bible = variables.get("story_bible", {})
        title = str(bible.get("title") or "Historia")
        language = str(variables.get("language") or "pt-BR")
        content = (
            f"Titulo: {title}\n\n"
            "Gancho: Ela encontra uma pista que ninguem deveria ter deixado para tras.\n\n"
            "Ato 1: O cotidiano parece simples, ate que uma lembranca interrompe tudo.\n"
            "Ato 2: A busca por respostas revela escolhas dolorosas e uma promessa esquecida.\n"
            "Ato 3: A verdade aparece no momento de maior perda, transformando culpa em perdao.\n\n"
            "Encerramento: A personagem entende que amar tambem pode ter sido proteger em silencio."
        )
        return {
            "title": title,
            "language": language,
            "target_duration_seconds": int(variables.get("target_duration_seconds") or 240),
            "word_count": len(content.split()),
            "content": content,
        }

    def _scenes_and_shots(self, variables: dict) -> dict:
        total_duration = int(variables.get("target_duration_seconds") or 240)
        scene_duration = max(30, total_duration // 4)
        return {
            "scenes": [
                {
                    "scene_number": index,
                    "title": title,
                    "summary": summary,
                    "duration_seconds": scene_duration,
                    "shots": [
                        {
                            "shot_number": 1,
                            "duration_seconds": scene_duration // 3,
                            "narration_text": summary,
                            "dialogue_text": "",
                            "action": "Apresentar informacao visual essencial.",
                            "emotion": emotion,
                            "visual_composition": "Plano vertical com rosto e objeto em destaque.",
                            "camera_movement": "push-in lento",
                            "generation_type": "ANIMATED_STILL",
                        },
                        {
                            "shot_number": 2,
                            "duration_seconds": scene_duration // 3,
                            "narration_text": "A tensao cresce sem explicar demais.",
                            "dialogue_text": "",
                            "action": "Mostrar reacao e microgancho.",
                            "emotion": emotion,
                            "visual_composition": "Close emocional com fundo reconhecivel.",
                            "camera_movement": "pan curto",
                            "generation_type": "IMAGE_TO_VIDEO",
                        },
                        {
                            "shot_number": 3,
                            "duration_seconds": scene_duration - 2 * (scene_duration // 3),
                            "narration_text": "A cena termina prometendo uma revelacao.",
                            "dialogue_text": "",
                            "action": "Fechar com detalhe visual.",
                            "emotion": emotion,
                            "visual_composition": "Objeto narrativo ocupando o terco inferior.",
                            "camera_movement": "zoom suave",
                            "generation_type": "CAMERA_ZOOM",
                        },
                    ],
                }
                for index, title, summary, emotion in [
                    (1, "O gancho", "Uma pista rompe a rotina da protagonista.", "curiosidade"),
                    (2, "A busca", "Ela segue rastros que a familia evitava.", "ansiedade"),
                    (3, "A revelacao", "O segredo muda o sentido do abandono.", "choque"),
                    (4, "O payoff", "A verdade permite uma reconciliacao possivel.", "catarse"),
                ]
            ]
        }
