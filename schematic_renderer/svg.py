"""Small Pillow-compatible drawing sink for zoomable schematic exports."""
from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw


class SVGDraw:
    def __init__(self, width, height, background, scale=1):
        self.root = ET.Element("svg", xmlns="http://www.w3.org/2000/svg", width=str(width * scale),
                               height=str(height * scale), viewBox=f"0 0 {width} {height}")
        self.measure = ImageDraw.Draw(Image.new("L", (1, 1)))
        self.rectangle((0, 0, width, height), fill=background)

    def _add(self, tag, **attributes):
        return ET.SubElement(self.root, tag, {key.replace("_", "-"): str(value)
                                             for key, value in attributes.items() if value is not None})

    def line(self, xy, fill="black", width=1):
        self._add("polyline", points=" ".join(f"{x},{y}" for x, y in xy), fill="none",
                  stroke=fill, stroke_width=width, stroke_linejoin="round")

    def rectangle(self, box, outline=None, fill=None, width=1):
        x, y, r, b = box
        self._add("rect", x=x, y=y, width=r-x, height=b-y, fill=fill or "none",
                  stroke=outline or "none", stroke_width=width)

    def ellipse(self, box, outline=None, fill=None, width=1):
        x, y, r, b = box
        self._add("ellipse", cx=(x+r)/2, cy=(y+b)/2, rx=(r-x)/2, ry=(b-y)/2,
                  fill=fill or "none", stroke=outline or "none", stroke_width=width)

    def polygon(self, xy, outline=None, fill=None):
        self._add("polygon", points=" ".join(f"{x},{y}" for x, y in xy),
                  fill=fill or "none", stroke=outline or "none")

    def arc(self, box, start, end, fill="black", width=1):
        x, y, r, b = box
        cx, cy, rx, ry = (x+r)/2, (y+b)/2, (r-x)/2, (b-y)/2
        angle1, angle2 = math.radians(start), math.radians(end)
        x1, y1 = cx+rx*math.cos(angle1), cy+ry*math.sin(angle1)
        x2, y2 = cx+rx*math.cos(angle2), cy+ry*math.sin(angle2)
        self._add("path", d=f"M {x1} {y1} A {rx} {ry} 0 0 1 {x2} {y2}",
                  fill="none", stroke=fill, stroke_width=width)

    def textbbox(self, xy, text, font=None, **kwargs):
        return self.measure.textbbox(xy, text, font=font, **kwargs)

    def text(self, xy, text, fill="black", font=None, anchor=None):
        box = self.measure.textbbox(xy, text, font=font, anchor=anchor)
        origin = self.measure.textbbox((0, 0), text, font=font, anchor="ls")
        node = self._add("text", x=box[0]-origin[0], y=box[1]-origin[1], fill=fill,
                         font_family=font.getname()[0] if hasattr(font, "getname") else "Arial",
                         font_size=getattr(font, "size", 12))
        node.text = str(text)

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        ET.ElementTree(self.root).write(path, encoding="utf-8", xml_declaration=True)
