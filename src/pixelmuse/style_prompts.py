"""Map the offline style catalog onto prompt phrases for text-guided mode.

The offline styles are algorithms; the text-guided mode needs words.  Keeping
the mapping in one table means the two modes offer the same named choices, so
switching mode does not change what the user recognises.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

#: style_key -> phrase describing that look to a generative model.
STYLE_PROMPTS: Dict[str, str] = {
    "oil_painting": "a thick impasto oil painting with visible brush strokes and canvas texture",
    "oil_realism": "a realistic classical oil painting with fine brushwork, deep colour and varnish",
    "acrylic": "a bold flat acrylic painting with thick raised paint and strong texture",
    "watercolour": "a translucent watercolour painting with blooming washes and rough paper texture",
    "gouache": "an opaque matte gouache painting with flattened poster-like planes",
    "palette_knife": "a palette-knife oil painting built from bold sculpted smears of thick paint",
    "pastel": "a soft pastel drawing with powdery chalk colour rubbed into textured paper",
    "ink_wash": "a sumi-e ink wash painting, monochrome brushwork diffusing into wet rice paper",
    "spray_paint": "an urban spray-paint stencil artwork with soft aerosol edges and speckle",
    "pencil_sketch": "a graphite pencil sketch with fine line work and light hatching on paper",
    "charcoal": "a charcoal drawing with smudged dark masses and a dry dusty edge",
    "digital_sketch": "clean digital line art with flat cel-shaded colour",
    "comic_ink": "a comic book illustration with bold black outlines and screentone dot shading",
    "ballpoint": "a ballpoint pen drawing with fine blue biro hatching, like a sketchbook page",
    "lineart": "pure black ink line art on clean white, colouring-book style",
    "blueprint": "a cyanotype blueprint technical drawing with white lines on deep blue",
    "pop_art": "a pop-art screenprint with flat saturated colour blocks and halftone dots",
    "pixel_art": "retro pixel art with a limited palette and visible chunky pixels",
    "noir": "a high-contrast black and white film noir photograph with dramatic shadows",
}


def style_choices() -> List[Tuple[str, str]]:
    """``(key, prompt)`` pairs, ordered like the offline catalog."""
    from .styles import all_styles

    choices: List[Tuple[str, str]] = []
    for style in all_styles():
        prompt = STYLE_PROMPTS.get(style.key)
        if prompt:
            choices.append((style.key, prompt))
    return choices


def prompt_for(style_key: str) -> str:
    """The prompt phrase for *style_key*, or '' when it has no equivalent."""
    return STYLE_PROMPTS.get(style_key, "")


def label_for(style_key: str) -> str:
    """Human-readable label, falling back to a title-cased key."""
    from .styles import get_style

    try:
        return get_style(style_key).label
    except KeyError:
        return style_key.replace("_", " ").title()
