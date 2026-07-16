import hashlib
from html import escape
from pathlib import Path
from uuid import uuid4

from app.providers.image.types import ImageEditRequest, ImageGenerationRequest, ImageResult


class MockImageProvider:
    provider_name = "mock"

    async def generate(self, request: ImageGenerationRequest) -> ImageResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{request.target_id}_{request.view_type}_{uuid4().hex[:8]}.svg"
        file_path = request.output_dir / filename
        svg = self._build_svg(request.prompt, request.target_id, request.view_type)
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

    def _build_svg(self, prompt: str, target_id: str, view_type: str) -> str:
        digest = hashlib.sha256(f"{target_id}:{view_type}:{prompt}".encode()).hexdigest()
        color_a = f"#{digest[:6]}"
        color_b = f"#{digest[6:12]}"
        label = escape(view_type.replace("_", " ").title())
        safe_prompt = escape(prompt[:180])
        safe_target = escape(target_id)
        body_style = (
            "font-family:Arial;color:#f8fafc;font-size:30px;"
            "text-align:center;line-height:1.3"
        )
        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920"',
                '     viewBox="0 0 1080 1920">',
                f'  <rect width="1080" height="1920" fill="{color_a}"/>',
                f'  <rect x="90" y="140" width="900" height="1640" rx="44" fill="{color_b}"',
                '        opacity="0.86"/>',
                '  <circle cx="540" cy="560" r="230" fill="#f8fafc" opacity="0.82"/>',
                '  <rect x="330" y="820" width="420" height="520" rx="120"',
                '        fill="#f8fafc" opacity="0.78"/>',
                '  <text x="540" y="1480" text-anchor="middle" font-family="Arial"',
                f'        font-size="58" fill="#f8fafc">{label}</text>',
                '  <text x="540" y="1560" text-anchor="middle" font-family="Arial"',
                f'        font-size="34" fill="#f8fafc">{safe_target}</text>',
                '  <foreignObject x="160" y="1620" width="760" height="180">',
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
