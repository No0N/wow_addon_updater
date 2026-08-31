"""
Создаёт icon.ico из SVG для сборки exe.
Запуск: python build_icon.py
Требуется: pip install cairosvg Pillow
"""
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SVG_PATH = SCRIPT_DIR / "268391_panda-icon.svg"
ICO_PATH = SCRIPT_DIR / "icon.ico"
SIZES = (16, 32, 48, 256)


def main() -> None:
    if not SVG_PATH.is_file():
        print(f"Не найден файл: {SVG_PATH}")
        return
    try:
        import cairosvg
        from PIL import Image
        import io
    except ImportError as e:
        print("Установите зависимости: pip install cairosvg Pillow")
        print("Либо сконвертируйте SVG в ICO онлайн (например convertio.co) и сохраните как icon.ico")
        raise SystemExit(1) from e

    # Рендер в PNG максимального размера
    png_buf = io.BytesIO()
    cairosvg.svg2png(
        url=str(SVG_PATH),
        write_to=png_buf,
        output_width=SIZES[-1],
        output_height=SIZES[-1],
    )
    png_buf.seek(0)
    img = Image.open(png_buf).convert("RGBA")

    # Собрать ICO из нескольких размеров
    images = []
    for size in SIZES:
        if size != SIZES[-1]:
            resized = img.resize((size, size), Image.Resampling.LANCZOS)
        else:
            resized = img
        images.append(resized)

    images[0].save(
        ICO_PATH,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[1:],
    )
    print(f"Создан файл: {ICO_PATH}")


if __name__ == "__main__":
    main()
