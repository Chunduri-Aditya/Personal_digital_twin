"""Generate data/test_photo.jpg (1600x1200): sky gradient, green ground, yellow sun, house with red roof, text."""
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 1200
img = Image.new("RGB", (W, H))
draw = ImageDraw.Draw(img)
# blue sky gradient (top darker blue -> lighter at the horizon)
horizon = int(H * 0.62)
for y in range(horizon):
    t = y / max(1, horizon - 1)
    r = int(70 + (170 - 70) * t)
    g = int(130 + (215 - 130) * t)
    b = int(220 + (245 - 220) * t)
    draw.line([(0, y), (W, y)], fill=(r, g, b))
# green ground
draw.rectangle([0, horizon, W, H], fill=(70, 150, 60))
# yellow sun
draw.ellipse([1180, 120, 1440, 380], fill=(255, 220, 40))
# brown house with red triangle roof
draw.rectangle([420, 560, 900, 900], fill=(140, 90, 50))
draw.polygon([(380, 570), (660, 330), (940, 570)], fill=(200, 40, 40))
draw.rectangle([620, 740, 700, 900], fill=(70, 40, 20))  # door
draw.rectangle([470, 620, 560, 700], fill=(200, 230, 255))  # window
draw.rectangle([760, 620, 850, 700], fill=(200, 230, 255))  # window
# text
try:
    font = ImageFont.truetype("arial.ttf", 120)
except OSError:
    font = ImageFont.load_default()
draw.text((120, 980), "coffee time", fill=(255, 255, 255), font=font)
img.save("data/test_photo.jpg", quality=92)
print("wrote data/test_photo.jpg", img.size)
