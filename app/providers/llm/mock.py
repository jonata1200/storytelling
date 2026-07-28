# ruff: noqa: E501

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
                "Use o botão de geração no topo destá área; vou manter o contexto já aprovado."
            )
        elif any(word in message for word in ("melhor", "revise", "ajuste", "mude")):
            guidance = (
                "Eu sugiro priorizar clareza emocional, continuidade e um gancho visual forte."
            )
        else:
            guidance = "Posso revisar, propor alternativas ou indicar o próximo passo destá etapa."
        return {
            "message": (
                f"Estou acompanhando o {labels.get(section, section)}. {guidance} "
                f"O projeto tem atualmente {context.get('summary', 'conteúdo em desenvolvimento')}."
            )
        }

    def _story_ideas(self, variables: dict) -> dict:
        base_theme = str(variables.get("theme") or "tema livre criado pela IA")
        audience = str(variables.get("audience") or "público geral")
        count = int(variables.get("count") or 3)
        target_duration = float(variables.get("target_duration_minutes") or 5)
        selected_genre = str(variables.get("genre") or "").strip()
        idea_specs = [
            {
                "title": "O Trem Que Não Para Na Estacao",
                "theme": "uma maquinista descobre que cada parada apagaria um bairro inteiro",
                "genre": "Suspense",
                "primary_emotion": "Tensão",
                "hook": "O painel mostra uma estácao que foi demolida ha vinte anos.",
                "premise": (
                    "Nina, maquinista noturna, precisa decidir se freia um trem lotado "
                    f"quando percebe que a rota impossível pode salvar {audience} de um apagao urbano."
                ),
                "protagonist": "Nina, uma maquinista noturna obsessiva por horarios",
                "protagonist_desire": "Impedir um acidente sem abandonar os passageiros",
                "emotional_need": "Aceitar que controle absoluto tambem pode ferir",
                "conflict": "Frear o trem salva uma memória coletiva, mas coloca vidas reais em risco",
                "obstacles": ["sinalizacao contraditoria", "passageiros em panico", "um supervisor que nega a rota"],
                "stakes": "Centenas de pessoas podem sumir dos registros da cidade",
                "twist": "A estácao fantasma foi criada para esconder um despejo ilegal",
                "climax": "Nina corta a energia do trem no tunel antes da ultima curva",
                "payoff": "A cidade recupera o bairro apagado sem transformar os passageiros em prova descartavel",
                "resolution": "Nina entrega os registros e volta a dirigir sabendo quando desobedecer",
            },
            {
                "title": "A Cozinha Dos Nomes Trocados",
                "theme": "um cozinheiro perde o proprio nome sempre que salva alguem",
                "genre": "Fantasia urbana",
                "primary_emotion": "Melancolia",
                "hook": "No pedido da mesa sete aparece um nome que ninguem vivo deveria conhecer.",
                "premise": (
                    "Davi, cozinheiro de madrugada, percebe que seus pratos curam lutos, "
                    "mas cada cura apaga uma parte de sua identidade."
                ),
                "protagonist": "Davi, um cozinheiro de lanchonete que memoriza desconhecidos",
                "protagonist_desire": "Salvar a dona do restáurante sem desaparecer",
                "emotional_need": "Parar de confundir sacrificio com amor",
                "conflict": "Cada prato perfeito devolve alguem a uma familia e rouba uma lembranca de Davi",
                "obstacles": ["clientes desesperados", "receitas que mudam sozinhas", "a dona escondendo a origem da cozinha"],
                "stakes": "Davi pode virar um funcionario sem nome em uma cidade que esquece seus cuidadores",
                "twist": "A primeira péssoa salva por aquela cozinha foi ele mesmo",
                "climax": "Davi serve um prato incompleto para quebrar o pacto sem abandonar a cliente",
                "payoff": "A cura deixa de exigir apagamento e passa a exigir testemunho",
                "resolution": "O restáurante vira um lugar onde as pessoas deixam nomes, não dividas",
            },
            {
                "title": "Manual Para Roubar Um Minuto",
                "theme": "uma ladra de relogios rouba tempo de corruptos para devolver a trabalhadores",
                "genre": "Aventura",
                "primary_emotion": "Coragem",
                "hook": "Lia abre um relogio caro e ouve dentro dele a respiracao de uma crianca exausta.",
                "premise": (
                    "Lia, falsificadora de antiguidades, descobre que executivos compram minutos "
                    "de vida de funcionarios invisiveis e decide desmontar o leilao."
                ),
                "protagonist": "Lia, uma falsificadora de antiguidades com mãos tremulas",
                "protagonist_desire": "Recuperar o tempo roubado da irma",
                "emotional_need": "Confiar em aliados em vez de atuar sempre sozinha",
                "conflict": "Para devolver o tempo roubado, Lia precisa destruir a única prova que salvaria sua irma",
                "obstacles": ["segurança do leilao", "um comprador que reconhece suas falsificacoes", "o relogio falhando a cada mentira"],
                "stakes": "Centenas de trabalhadores podem envelhecer anos em uma única noite",
                "twist": "A irma de Lia vendeu minutos voluntariamente para financiar a fuga das duas",
                "climax": "Lia troca o relogio mestre por uma copia imperfeita diante de todos",
                "payoff": "O tempo volta como escolha compartilhada, não como resgate individual",
                "resolution": "As irmas fogem sem riqueza, mas com dias suficientes para recomecar",
            },
            {
                "title": "O Arquivo Das Vozes Baixas",
                "theme": "uma arquivista encontra audios de pessoas que nunca foram autorizadas a falar",
                "genre": "Drama",
                "primary_emotion": "Indignacao",
                "hook": "Uma fita sem etiqueta reproduz a voz de alguem que está em silencio na sala.",
                "premise": (
                    "Helena, arquivista de tribunal, descobre depoimentos ocultados e precisa "
                    "decidir entre proteger sua carreira ou expor uma cidade inteira."
                ),
                "protagonist": "Helena, uma arquivista judicial que fala baixo por habito",
                "protagonist_desire": "Fazer os depoimentos chegarem as pessoas certas",
                "emotional_need": "Reconhecer a propria voz como prova",
                "conflict": "Publicar as fitas liberta vitimas, mas tambem incrimina alguem que a protegeu",
                "obstacles": ["lacres adulterados", "ameacas administrativas", "uma testemunha que pede silencio"],
                "stakes": "Um julgamento historico pode ser decidido por arquivos falsificados",
                "twist": "A voz mais importante nas fitas e da propria Helena quando crianca",
                "climax": "Helena reproduz o audio no alto-falante do tribunal lotado",
                "payoff": "A verdade vira escuta pública, não espetaculo de púnicao",
                "resolution": "Ela perde o cargo, mas cria um arquivo independente de testemunhos",
            },
            {
                "title": "A Ilha Que Cabe No Elevador",
                "theme": "moradores presos em um elevador descobrem que ele replica o predio inteiro",
                "genre": "Ficcao cientifica",
                "primary_emotion": "Estranhamento",
                "hook": "O elevador abre no decimo segundo andar, mas do lado de fora ha areia e mar.",
                "premise": (
                    "Caio, sindico recem-eleito, entra no elevador com tres vizinhos e encontra "
                    "uma versão comprimida do condomínio que revela acordos absurdos."
                ),
                "protagonist": "Caio, um sindico jovem que odeia conflito presencial",
                "protagonist_desire": "Sair do elevador antes da assembleia decisiva",
                "emotional_need": "Parar de terceirizar decisoes que afetam outras vidas",
                "conflict": "Cada andar impossível mostra uma consequencia real das omissoes do condomínio",
                "obstacles": ["vizinhos acusando uns aos outros", "portas que abrem em memórias materiais", "o painel cobrando uma escolha unanime"],
                "stakes": "O predio pode repetir para sempre a mesma assembleia sem resolver seus danos",
                "twist": "O elevador foi instalado para transformar decisoes coletivas em experiencia fisica",
                "climax": "Caio segura a porta aberta e obriga todos a votar olhando para os efeitos",
                "payoff": "A comunidade entende que convivencia tambem e autoria",
                "resolution": "O elevador volta ao normal, mas ninguem consegue fingir neutralidade",
            },
            {
                "title": "O Jardim Que Recusa Flores",
                "theme": "uma botanica cultiva plantas que so crescem com promessas cumpridas",
                "genre": "Drama fantastico",
                "primary_emotion": "Esperanca",
                "hook": "Todas as flores do viveiro murcham quando a prefeita sorri para a camera.",
                "premise": (
                    "Rosa, botanica municipal, descobre que o jardim público reage a mentiras "
                    "políticas e vira prova viva de promessas quebradas."
                ),
                "protagonist": "Rosa, uma botanica municipal que mede afeto em solo",
                "protagonist_desire": "Salvar o viveiro antes que a cidade o transforme em estácionamento",
                "emotional_need": "Trocar paciencia silenciosa por confronto público",
                "conflict": "Expor o jardim salva a memória ambiental, mas pode destruir o trabalho de sua equipe",
                "obstacles": ["plantas adoecendo em cadeia", "contratos assinados as pressas", "moradores descrentes"],
                "stakes": "A ultima area verde do bairro pode virar propaganda de sustentabilidade falsa",
                "twist": "O jardim não reage a mentiras, mas a promessas que ninguem pretende cobrar",
                "climax": "Rosa planta as mudas no asfalto durante a inauguracao oficial",
                "payoff": "A cidade entende cuidado como compromisso mensuravel",
                "resolution": "O estácionamento vira horta-escola administrada pelos moradores",
            },
            {
                "title": "A Ponte Dos Guarda-Chuvas Fechados",
                "theme": "um cobrador de onibus escolta desconhecidos por uma chuva que revela medos",
                "genre": "Realismo magico",
                "primary_emotion": "Ternura",
                "hook": "Chove para cima dentro do onibus, mas so sobre quem está mentindo para si.",
                "premise": (
                    "Orlando, cobrador prestes a ser substituido por catracas digitais, percebe "
                    "que sua ultima rota atravessa arrependimentos materializados pela chuva."
                ),
                "protagonist": "Orlando, um cobrador de onibus que conhece todos pelo sapato",
                "protagonist_desire": "Completar a ultima viagem sem deixar passageiros para tras",
                "emotional_need": "Aceitar que ser necessario não é o mesmo que ser amado",
                "conflict": "A rota so termina quando cada passageiro admite o medo que trouxe consigo",
                "obstacles": ["ruas alagadas por lembrancas", "um motorista que quer abandonar a linha", "passageiros recusando ajuda"],
                "stakes": "A linha pode desaparecer levando junto a única conexao do bairro",
                "twist": "Orlando tambem está preso na rota porque nunca se despediu do proprio futuro",
                "climax": "Ele abre todos os guarda-chuvas no teto do onibus para inverter a chuva",
                "payoff": "A despedida vira passagem, não apagamento",
                "resolution": "A linha muda de número, mas Orlando vira mapa vivo da comunidade",
            },
            {
                "title": "Contrato Para Um Silencio",
                "theme": "uma interprete de libras descobre clausulas escondidas em pausas",
                "genre": "Thriller juridico",
                "primary_emotion": "Desconfianca",
                "hook": "Durante uma audiencia, a pausa de uma testemunha forma uma frase que ninguem ouviu.",
                "premise": (
                    "Maya, interprete de libras em audiencias remotas, percebe que silenciamentos "
                    "editados escondem acordos ilegais entre advogados e empresas."
                ),
                "protagonist": "Maya, uma interprete de libras treinada para notar pausas",
                "protagonist_desire": "Provar que o depoimento foi manipulado sem expor a testemunha",
                "emotional_need": "Permitir que sua precisão tambem carregue raiva",
                "conflict": "A única prova está em segundos de silencio que o tribunal considera irrelevantes",
                "obstacles": ["vídeos comprimidos", "peritos comprados", "uma testemunha aterrorizada"],
                "stakes": "Um acordo toxico pode condenar trabalhadores a aceitar culpa inexistente",
                "twist": "As pausas formam um pedido de socorro feito em codigo visual",
                "climax": "Maya reconstroi o depoimento ao vivo com os gestos omitidos",
                "payoff": "O silencio ganha valor legal sem virar espetaculo",
                "resolution": "A audiencia e anulada e Maya cria protocolo para provas acessiveis",
            },
            {
                "title": "A Oficina Dos Mapas Que Sangram",
                "theme": "um cartografo repara mapas que mostram feridas urbanas",
                "genre": "Noir urbano",
                "primary_emotion": "Inquietacao",
                "hook": "Uma avenida desenhada no mapa começa a sangrar antes do primeiro acidente.",
                "premise": (
                    "Tadeu, restáurador de mapas antigos, descobre que plantas oficiais revelam "
                    "danos futuros sempre que alguem lucra com trajetos perigosos."
                ),
                "protagonist": "Tadeu, um cartografo apósentado que perdeu a direcao na propria vida",
                "protagonist_desire": "Impedir uma obra viaria antes que ela mate de novo",
                "emotional_need": "Voltar a confiar no proprio senso de orientacao moral",
                "conflict": "Corrigir o mapa pode salvar o bairro, mas incrimina o antigo parceiro de Tadeu",
                "obstacles": ["mapas adulterados", "engenheiros apressando a obra", "uma memória falhando"],
                "stakes": "O bairro inteiro pode ser redesenhado para esconder mortes previsiveis",
                "twist": "Tadeu assinou o primeiro mapa defeituoso sem ler a legenda escondida",
                "climax": "Ele projeta o mapa ferido na fachada da prefeitura durante a votacao",
                "payoff": "A cidade enxerga que rota tambem e responsabilidade",
                "resolution": "Tadeu abre uma oficina pública de mapas corrigidos pelos moradores",
            },
            {
                "title": "Ultima Aula De Gravidade",
                "theme": "uma professora percebe que alunos flutuam quando desistem do futuro",
                "genre": "Drama escolar",
                "primary_emotion": "Cuidado",
                "hook": "No meio da chamada, um aluno sobe lentamente ate encostar no ventilador desligado.",
                "premise": (
                    "Samira, professora substituta, descobre que a escola perde gravidade sempre "
                    "que os alunos acreditam que ninguem espera nada deles."
                ),
                "protagonist": "Samira, uma professora substituta que evita criar raizes",
                "protagonist_desire": "Manter a turma segura ate o fim do dia",
                "emotional_need": "Entender presenca como compromisso, não prisão",
                "conflict": "Para devolver os alunos ao chao, Samira precisa prometer permanecer onde sempre foge",
                "obstacles": ["direcao negando o fenomeno", "alunos transformando levitacao em desafio", "pais ausentes"],
                "stakes": "A turma pode desaparecer pelo teto antes de acreditar em qualquer futuro",
                "twist": "Samira tambem flutuava quando era aluna daquela escola",
                "climax": "Ela prende a propria cadeira ao chao e da aula olhando para cima",
                "payoff": "Os alunos descem quando percebem que alguem vai testemunhar sua queda e sua subida",
                "resolution": "Samira fica por um semestre e transforma a sala em observatorio de futuros",
            },
        ]
        if base_theme != "tema livre criado pela IA":
            for index, spec in enumerate(idea_specs, 1):
                spec["theme"] = f"{base_theme} por uma abordagem dramatica {index}"
        return {
            "ideas": [
                (
                    {
                        **idea_specs[(index - 1) % len(idea_specs)],
                        "genre": (
                            selected_genre
                            if selected_genre and selected_genre != "gênero livre criado pela IA"
                            else idea_specs[(index - 1) % len(idea_specs)]["genre"]
                        ),
                        "duration_minutes": max(5, min(25, target_duration)),
                        "retention_potential": min(95, 75 + index),
                        "cliche_risk": 12 + index,
                        "production_complexity": 30 + index,
                        "estimated_production_cost": "low",
                    }
                )
                for index in range(1, count + 1)
            ]
        }

    def _script(self, variables: dict) -> dict:
        idea = variables.get("idea", {})
        contract = variables.get("narrative_contract", {})
        title = str(idea.get("title") or contract.get("title") or "Historia")
        language = str(variables.get("language") or "pt-BR")
        target_duration_seconds = int(variables.get("target_duration_seconds") or 240)
        protagonist = str(idea.get("protagonist") or "Ari, uma péssoa em conflito").strip()
        protagonist_name = protagonist.split(",", 1)[0].strip() or "Ari"
        protagonist_upper = protagonist_name.upper()
        hook = str(idea.get("hook") or "Um sinal visual rompe a rotina.").strip()
        conflict = str(idea.get("conflict") or "A escolha certa cobra um preco imediato.").strip()
        twist = str(idea.get("twist") or "A pista mais confiavel estáva incompleta.").strip()
        payoff = str(idea.get("payoff") or idea.get("resolution") or "A decisão final muda o sentido da perda.").strip()
        location_options = [
            "ESTACAO SUBTERRANEA",
            "COZINHA DE MADRUGADA",
            "LEILAO CLANDESTINO",
            "ARQUIVO DO TRIBUNAL",
            "ELEVADOR ANTIGO",
            "JARDIM MUNICIPAL",
            "ONIBUS NOTURNO",
            "SALA DE AUDIENCIA REMOTA",
        ]
        location = location_options[sum(ord(char) for char in title) % len(location_options)]
        scene_count = int(
            variables.get("expected_scene_count")
            or _expected_scene_count(target_duration_seconds)
        )
        scene_templates = [
            (
                f"INT. {location} - FIM DE TARDE",
                f"{protagonist_upper}, em alerta, percebe algo impossível no espaco. "
                f"{hook}\n\n{protagonist_upper}\nIsso muda tudo agora.",
            ),
            (
                f"EXT. ARREDORES DE {location} - NOITE",
                f"{protagonist_upper} atravessa a noite tentando agir antes que alguem "
                f"transforme o medo em regra. {conflict}",
            ),
            (
                f"INT. {location} - MADRUGADA",
                f"O ambiente revela uma camada escondida do conflito. {twist} "
                f"{protagonist_upper} entende que vencer não basta; será preciso escolher.",
            ),
            (
                f"INT. {location} - AMANHECER",
                f"{protagonist_upper} encara a consequencia diante de todos. O gesto final "
                "e simples, visivel e impossível de desfazer.",
            ),
            (
                f"EXT. {location} - MANHA",
                f"{payoff} {protagonist_upper} sai diferente, sem transformar a dor em "
                "explicacao facil.",
            ),
        ]
        scenes = []
        for index in range(scene_count):
            slugline, action = scene_templates[index % len(scene_templates)]
            bridge = (
                "\n\nA escolha anterior muda o péso da cena, acrescentando uma virada "
                "emocional antes do próximo passo."
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
            + f"A revisão ganha corpo em uma acao simples: {instruction.strip().capitalize()}. "
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
            ("A escolha", "A protagonista precisa agir apésar do medo.", "coragem"),
            ("O payoff", "A verdade permite uma reconciliacao possível.", "catarse"),
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
