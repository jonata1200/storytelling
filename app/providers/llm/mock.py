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
        theme = str(variables.get("theme") or "uma segunda chance")
        audience = str(variables.get("audience") or "publico geral")
        emotion = str(variables.get("primary_emotion") or "esperanca")
        return {
            "ideas": [
                {
                    "title": f"O Ultimo Pedido sobre {theme}",
                    "hook": "Ela encontra uma mensagem que muda tudo nos primeiros segundos.",
                    "premise": f"Uma pessoa comum precisa encarar {theme} diante de {audience}.",
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
                    "retention_potential": 86,
                    "cliche_risk": 28,
                    "production_complexity": 34,
                    "estimated_production_cost": "low",
                },
                {
                    "title": f"A Foto Esquecida de {theme}",
                    "hook": "Um detalhe no fundo de uma foto revela uma injustica.",
                    "premise": "Uma revelacao visual simples abre uma ferida familiar escondida.",
                    "protagonist": "Mateus, entregador que cuida da avo",
                    "protagonist_desire": "Provar que a avo nao mentiu",
                    "emotional_need": "Aprender a confiar na memoria dos outros",
                    "conflict": "Todos tratam a historia como confusao",
                    "obstacles": ["documentos perdidos", "preconceito", "medo de expor a familia"],
                    "stakes": "A avo morrer sem ser acreditada",
                    "twist": "O antagonista guardava a prova por vergonha",
                    "climax": "Mateus mostra a foto restaurada para todos",
                    "resolution": "A avo recebe um pedido de desculpas tardio",
                    "final_emotion": emotion,
                    "retention_potential": 79,
                    "cliche_risk": 22,
                    "production_complexity": 26,
                    "estimated_production_cost": "low",
                },
                {
                    "title": f"Quando a Porta Abriu para {theme}",
                    "hook": "No velorio, uma crianca entrega uma chave que ninguem conhecia.",
                    "premise": "Uma chave pequena revela o sacrificio secreto de uma mae.",
                    "protagonist": "Helena, filha que se afastou da familia",
                    "protagonist_desire": "Entender por que foi abandonada",
                    "emotional_need": "Aceitar amor imperfeito",
                    "conflict": "A resposta contradiz tudo o que ela acreditava",
                    "obstacles": ["ressentimento", "silencio familiar", "um quarto trancado"],
                    "stakes": "Viver presa a uma mentira",
                    "twist": "O abandono foi uma protecao",
                    "climax": "Helena abre o quarto e encontra cartas nunca enviadas",
                    "resolution": "Ela narra a historia da mae sem rancor",
                    "final_emotion": emotion,
                    "retention_potential": 91,
                    "cliche_risk": 35,
                    "production_complexity": 42,
                    "estimated_production_cost": "medium",
                },
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
