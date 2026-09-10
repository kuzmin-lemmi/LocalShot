"""Flattened edits: saved PNG contains only resulting pixels, never hidden layers."""
import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def rectangle(a, b, size):
    x1, x2 = sorted((round(a[0]), round(b[0])))
    y1, y2 = sorted((round(a[1]), round(b[1])))
    # Mouse endpoints identify pixels; Pillow's crop/paste right edge is exclusive.
    return max(0, x1), max(0, y1), min(size[0], x2 + 1), min(size[1], y2 + 1)


def edit(image, tool, a, b, color='#ef4444', width=5, text='', font_size=28):
    out = image.convert('RGB')
    draw = ImageDraw.Draw(out)
    box = rectangle(a, b, out.size)
    if tool in ('hide', 'blur', 'rect'):
        if box[2] <= box[0] or box[3] <= box[1]:
            return out
        if tool == 'hide':
            # Exact overwrite; blur must not be used to conceal sensitive text.
            out.paste(color, box)
        elif tool == 'blur':
            out.paste(out.crop(box).filter(ImageFilter.GaussianBlur(14)), box)
        else:
            draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), outline=color, width=width)
    elif tool in ('line', 'arrow'):
        draw.line([a, b], fill=color, width=width)
        if tool == 'arrow' and math.dist(a, b) > 2:
            angle = math.atan2(b[1] - a[1], b[0] - a[0])
            length = max(16, width * 4)
            points = [b] + [(b[0] - length * math.cos(angle + delta),
                            b[1] - length * math.sin(angle + delta))
                           for delta in (-0.48, 0.48)]
            draw.polygon(points, fill=color)
    elif tool == 'text' and text:
        font = None
        for name in ('C:/Windows/Fonts/arial.ttf', 'DejaVuSans.ttf'):
            try:
                font = ImageFont.truetype(name, font_size)
                break
            except OSError:
                pass
        if font is None:
            font = ImageFont.load_default(size=font_size)
        draw.text(a, text, font=font, fill=color)
    return out
