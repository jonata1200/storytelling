from dataclasses import dataclass

from app.generation.shot_generation_spec import ShotGenerationSpec

VIBES_SHOT_PROMPT_COMPILER_VERSION = "vibes_shot_v1"


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
        stable: list[str] = []
        for name, state in spec.character_states.items():
            details = ", ".join(
                str(value).strip()
                for key, value in state.items()
                if key != "emotional_state" and str(value).strip()
            )
            stable.append(f"{name}: {details}" if details else name)
        stable.extend(str(item) for item in spec.continuity.get("stable_elements", []) if item)
        lines = [
            f"Scene: {spec.scene_title}. {spec.scene_summary}",
            f"Primary action: {spec.action.strip()}.",
            f"Primary camera movement: {(spec.camera_movement or spec.camera).strip()}.",
            f"Composition: {spec.visual_composition.strip()}.",
            f"Emotion and atmosphere: {spec.emotion.strip()}; {spec.lighting.strip()}.",
        ]
        if stable:
            lines.append(f"Keep stable: {'; '.join(stable)}.")
        if spec.previous_frame_reference and not spec.continuity_break:
            lines.append("Continue spatial position and movement from the supplied previous frame.")
        if spec.continuity_break:
            lines.append(
                "Intentional temporal or spatial cut: establish the new shot independently."
            )
        if rejection_note:
            lines.append(f"Revision direction: {rejection_note.strip()}.")
        if spec.visual_references or spec.ingredient_ids:
            lines.append(
                "Use the supplied references and ingredients for identity; do not redescribe or "
                "redesign them."
            )
        lines.append("No subtitles, logos, on-screen text, identity drift or abrupt morphing.")
        return CompiledShotPrompt(prompt="\n".join(lines), compiler_version=self.version)
