from app.providers.llm.types import LLMRequest, LLMResult


class MockLLMProvider:
    provider_name = "mock"

    async def generate_structured(self, request: LLMRequest) -> LLMResult:
        generators = {
            "generate_story_ideas": self._story_ideas,
            "generate_story_bible": self._story_bible,
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
            f"TITULO: {title}\n\n"
            "CENA 01 - INT. CASA DA FAMILIA - FIM DE TARDE - 45s\n"
            "OBJETIVO DRAMATICO: Apresentar Clara e a pista que rompe a rotina.\n"
            "PERSONAGENS: CLARA.\n"
            "LOCAL: sala simples, fotografias antigas, luz fria pela janela.\n"
            "OBJETOS IMPORTANTES: carta azul, porta-retratos rachado.\n"
            "ELEMENTOS VISUAIS: mesa antiga, poeira iluminada, mao tremendo.\n"
            "ACAO: CLARA encontra uma carta escondida entre fotografias antigas. "
            "O silencio da casa parece responder antes dela.\n"
            "NARRACAO: A casa guardou por anos uma resposta que Clara nunca pediu.\n"
            "DIALOGO:\n"
            "CLARA\n"
            "Isso nao podia estar aqui.\n"
            "INDICACAO PARA STORYBOARD: close na carta, push-in no rosto de Clara, "
            "corte para o porta-retratos.\n"
            "INDICACAO PARA VIDEO: movimento lento de aproximacao, ritmo suspenso.\n\n"
            "CENA 02 - EXT. RUA ESTREITA - NOITE - 70s\n"
            "OBJETIVO DRAMATICO: Transformar a pista em busca ativa.\n"
            "PERSONAGENS: CLARA.\n"
            "LOCAL: rua estreita, portas fechadas, postes falhando.\n"
            "OBJETOS IMPORTANTES: carta azul dobrada no bolso.\n"
            "ELEMENTOS VISUAIS: sombras longas, reflexos no asfalto, vento forte.\n"
            "ACAO: Clara segue os rastros da promessa esquecida. Cada porta fechada "
            "revela uma nova versao da mesma culpa.\n"
            "NARRACAO: Quanto mais Clara procura, mais a cidade parece reconhecer seu medo.\n"
            "DIALOGO: \n"
            "INDICACAO PARA STORYBOARD: plano geral vertical da rua, travelling curto, "
            "close da carta no bolso.\n"
            "INDICACAO PARA VIDEO: camera acompanha Clara por tras, cortes curtos.\n\n"
            "CENA 03 - INT. SALA DA FAMILIA - MADRUGADA - 85s\n"
            "OBJETIVO DRAMATICO: Revelar que a culpa estava no lugar errado.\n"
            "PERSONAGENS: CLARA.\n"
            "LOCAL: sala da familia, luz de abajur, parede de fotografias.\n"
            "OBJETOS IMPORTANTES: carta aberta, fita antiga.\n"
            "ELEMENTOS VISUAIS: rosto em close, sombras no papel, lagrima contida.\n"
            "ACAO: A verdade surge no momento de maior perda. Clara entende que o "
            "abandono tambem foi uma tentativa torta de protecao.\n"
            "NARRACAO: A revelacao nao apaga a dor, mas muda o nome dela.\n"
            "DIALOGO:\n"
            "CLARA\n"
            "Eu passei anos odiando a pessoa errada.\n"
            "INDICACAO PARA STORYBOARD: close no texto da carta, contra-plongee leve, "
            "corte para Clara respirando fundo.\n"
            "INDICACAO PARA VIDEO: push-in lento no climax, pausa antes do dialogo.\n\n"
            "CENA 04 - INT. CASA DA FAMILIA - AMANHECER - 100s\n"
            "OBJETIVO DRAMATICO: Entregar o payoff emocional e abrir reconciliacao.\n"
            "PERSONAGENS: CLARA.\n"
            "LOCAL: mesma sala, agora com luz quente do amanhecer.\n"
            "OBJETOS IMPORTANTES: carta azul, porta-retratos restaurado.\n"
            "ELEMENTOS VISUAIS: luz dourada, carta sobre a mesa, rosto aliviado.\n"
            "ACAO: Clara coloca a carta ao lado da fotografia restaurada e escolhe "
            "contar a verdade sem transformar ninguem em vilao.\n"
            "NARRACAO: Algumas promessas chegam tarde, mas ainda conseguem mudar o caminho.\n"
            "DIALOGO: \n"
            "INDICACAO PARA STORYBOARD: detalhe da fotografia, plano medio de Clara, "
            "fade para a janela iluminada.\n"
            "INDICACAO PARA VIDEO: camera fixa, movimento minimo, ritmo contemplativo."
        )
        return {
            "title": title,
            "language": language,
            "target_duration_seconds": int(variables.get("target_duration_seconds") or 240),
            "word_count": len(content.split()),
            "content": content,
        }

    def _revise_script(self, variables: dict) -> dict:
        current_script = str(variables.get("current_script") or "")
        instruction = str(variables.get("instruction") or "ajuste solicitado")
        language = str(variables.get("language") or "pt-BR")
        target_duration_seconds = int(variables.get("target_duration_seconds") or 300)
        content = (
            current_script.strip()
            + "\n\nAJUSTE DE PRODUCAO APLICADO:\n"
            + f"Pedido do Diretor IA: {instruction.strip().capitalize()}.\n"
            + "Impacto nas proximas etapas: preservar personagens, locais, objetos, "
            + "acoes filmaveis, indicacoes de storyboard e movimentos de camera."
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
