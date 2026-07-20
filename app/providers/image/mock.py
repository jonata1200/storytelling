import hashlib
import re
from html import escape
from pathlib import Path
from uuid import uuid4

from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult


class MockImageProvider:
    provider_name = "mock"

    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        safe_target = self._safe_filename_part(request.target_id)
        safe_view = self._safe_filename_part(request.view_type)
        filename = f"{safe_target}_{safe_view}_{uuid4().hex[:8]}.svg"
        file_path = request.output_dir / filename
        svg = self._build_svg(
            request.prompt,
            request.target_id,
            request.view_type,
            request.aspect_ratio,
        )
        file_path.write_text(svg, encoding="utf-8")
        sha256 = hashlib.sha256(svg.encode("utf-8")).hexdigest()
        return ImageResult(
            file_path=file_path,
            storage_uri=self._storage_uri(file_path),
            sha256=sha256,
            content_type="image/svg+xml",
            provider=self.provider_name,
            model=request.model,
            prompt=request.prompt,
        )

    async def edit(self, request: ImageEditRequest) -> ImageResult:
        generation_request = ImageGenerationRequest(
            prompt=f"Edit {request.source_uri}: {request.prompt}",
            target_id="edit",
            view_type="variant",
            output_dir=request.output_dir,
            model=request.model,
        )
        return await self.generate(generation_request)

    def _build_svg(
        self, prompt: str, target_id: str, view_type: str, aspect_ratio: str
    ) -> str:
        digest = hashlib.sha256(f"{target_id}:{view_type}:{prompt}".encode()).hexdigest()
        color_a = f"#{digest[:6]}"
        color_b = f"#{digest[6:12]}"
        label = escape(view_type.replace("_", " ").title())
        safe_prompt = escape(prompt[:180])
        safe_target = escape(target_id)
        width, height = {
            "16:9": (1920, 1080),
            "1:1": (1400, 1400),
            "9:16": (1080, 1920),
        }.get(aspect_ratio, (1080, 1920))
        inset_x = int(width * 0.08)
        inset_y = int(height * 0.07)
        panel_width = width - 2 * inset_x
        panel_height = height - 2 * inset_y
        center_x = width // 2
        label_y = int(height * 0.77)
        target_y = int(height * 0.82)
        text_y = int(height * 0.86)
        figure_top = int(height * 0.22)
        figure_mid = int(height * 0.43)
        head_radius = max(72, min(width, height) // 8)
        body_width = max(140, width // 3)
        body_height = max(220, height // 4)
        body_style = (
            "font-family:Arial;color:#f8fafc;font-size:30px;"
            "text-align:center;line-height:1.3"
        )
        return "\n".join(
            [
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"',
                f'     viewBox="0 0 {width} {height}">',
                f'  <rect width="{width}" height="{height}" fill="{color_a}"/>',
                f'  <rect x="{inset_x}" y="{inset_y}" width="{panel_width}"',
                f'        height="{panel_height}" rx="44" fill="{color_b}"',
                '        opacity="0.86"/>',
                f'  <circle cx="{center_x}" cy="{figure_top}" r="{head_radius}"',
                '        fill="#f8fafc" opacity="0.82"/>',
                f'  <rect x="{center_x - body_width // 2}" y="{figure_mid}"',
                f'        width="{body_width}" height="{body_height}" rx="120"',
                '        fill="#f8fafc" opacity="0.78"/>',
                f'  <text x="{center_x}" y="{label_y}" text-anchor="middle" font-family="Arial"',
                f'        font-size="58" fill="#f8fafc">{label}</text>',
                f'  <text x="{center_x}" y="{target_y}" text-anchor="middle" font-family="Arial"',
                f'        font-size="34" fill="#f8fafc">{safe_target}</text>',
                f'  <foreignObject x="{inset_x + 70}" y="{text_y}"',
                f'        width="{panel_width - 140}" height="{max(120, height - text_y - 40)}">',
                f'    <div xmlns="http://www.w3.org/1999/xhtml" style="{body_style}">',
                f"      {safe_prompt}",
                "    </div>",
                "  </foreignObject>",
                "</svg>",
                "",
            ]
        )

    def _storage_uri(self, file_path: Path) -> str:
        return file_path.as_posix()

    def _safe_filename_part(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
        return cleaned[:120] or "item"
