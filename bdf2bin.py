# -*- coding: utf-8 -*-

"""
BDF → XTEinkFontBinary 转换工具

核心设计思想：
- 使用 BDF 原生 baseline（FONT_ASCENT）进行垂直对齐
- 使用 DWIDTH（advance width）控制字符横向布局
- 输出为固定 cell 网格
- 支持整数倍缩放（保证位图不失真）
"""

import argparse
import sys
from typing import List


# --------------------------------------------------------------
# Bitmap scaling（整数倍像素复制）
# --------------------------------------------------------------


def scale_bitmap(bitmap: List[List[bool]], scale: int):
    """
    对 bitmap 进行整数倍缩放（无插值）

    原理：
    - 每个像素扩展为 scale × scale 的块
    - 完全保持原始形状（适合点阵字体）
    """
    if scale == 1:
        h = len(bitmap)
        w = len(bitmap[0]) if h > 0 else 0
        return w, h, bitmap

    h = len(bitmap)
    w = len(bitmap[0]) if h > 0 else 0

    new_w = w * scale
    new_h = h * scale

    # 初始化新 bitmap
    scaled = [[False] * new_w for _ in range(new_h)]

    # 像素块复制
    for y in range(h):
        for x in range(w):
            val = bitmap[y][x]
            if val:
                for dy in range(scale):
                    for dx in range(scale):
                        scaled[y * scale + dy][x * scale + dx] = True

    return new_w, new_h, scaled


# --------------------------------------------------------------
# BDF parsing
# --------------------------------------------------------------


def parse_bdf(filepath: str):
    """
    解析 BDF 文件

    返回：
    - glyph 字典：
        code → (w, h, x_off, y_off, advance, bitmap)
    - font_ascent / font_descent（用于 baseline）

    关键点：
    - bitmap 行是“字节对齐”的（不是按 width）
    - DWIDTH 表示逻辑宽度（advance）
    """
    with open(filepath, "r", encoding="latin-1") as f:
        lines = f.readlines()

    char_map = {}

    font_ascent = 0
    font_descent = 0

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # 全局 baseline 信息
        if line.startswith("FONT_ASCENT"):
            font_ascent = int(line.split()[1])

        elif line.startswith("FONT_DESCENT"):
            font_descent = int(line.split()[1])

        elif line.startswith("STARTCHAR"):
            i += 1

            encoding = None
            bbx = None
            dwidth = None
            bitmap_lines = []

            # 解析单个字符块
            while i < len(lines):
                line = lines[i].strip()

                if line.startswith("ENCODING"):
                    encoding = int(line.split()[1])

                elif line.startswith("BBX"):
                    parts = line.split()
                    bbx = (
                        int(parts[1]),  # width
                        int(parts[2]),  # height
                        int(parts[3]),  # x_offset（相对 origin）
                        int(parts[4]),  # y_offset（相对 baseline）
                    )

                elif line.startswith("DWIDTH"):
                    # advance width（排版宽度）
                    parts = line.split()
                    dwidth = int(parts[1])

                elif line.startswith("BITMAP"):
                    i += 1
                    while i < len(lines):
                        line = lines[i].strip()
                        if line.startswith("ENDCHAR"):
                            break
                        if line:
                            bitmap_lines.append(line)
                        i += 1
                    break

                i += 1

            # 构建 glyph
            if encoding is not None and bbx is not None:
                w, h, x_off, y_off = bbx
                advance = dwidth if dwidth is not None else w

                bitmap = []

                # BDF bitmap 是按“字节对齐”的
                # 例如 width=10 → 实际占 16 bit
                row_bits_total = ((w + 7) // 8) * 8  # ⭐ 字节对齐

                for row_str in bitmap_lines:
                    row_int = int(row_str, 16)

                    row_bits = []
                    for bit in range(w):
                        bit_val = (row_int >> (row_bits_total - 1 - bit)) & 1
                        row_bits.append(bit_val == 1)

                    bitmap.append(row_bits)

                char_map[encoding] = (w, h, x_off, y_off, advance, bitmap)

        i += 1

    return char_map, font_ascent, font_descent


def compute_cell_size(glyphs, font_ascent, font_descent, scale):
    """
    自动计算 cell 尺寸

    策略：
    - 宽度：使用最大 advance（保证不会截断）
    - 高度：ascent + descent（完整 baseline 覆盖）
    """

    max_advance = 0

    for _, _, _, _, advance, _ in glyphs.values():
        if advance > max_advance:
            max_advance = advance

    cell_width = max_advance * scale
    cell_height = (font_ascent + font_descent) * scale

    return cell_width, cell_height


# --------------------------------------------------------------
# Conversion（核心逻辑）
# --------------------------------------------------------------


def convert_bdf_to_bin(
    bdf_path: str,
    output_path: str,
    cell_width: int,
    cell_height: int,
    scale: float = 1.0,
    offset_x: int = 0,
    offset_y: int = 0,
    vertical: bool = False,
):
    """
    主转换函数

    输出格式：
    - 固定 cell 网格
    - row-major
    - MSB first（bit 7 → 左）

    注意：
    - 每个字符占用固定字节数
    """
    print(f"Parsing BDF: {bdf_path}")
    glyphs, font_ascent, font_descent = parse_bdf(bdf_path)

    if not glyphs:
        print("No glyphs found.")
        sys.exit(1)
    # 自动设置 cell 宽高
    if cell_width == 0 or cell_height == 0:
        cell_width, cell_height = compute_cell_size(
            glyphs, font_ascent, font_descent, scale
        )
        print(f"Auto cell size: {cell_width}x{cell_height}")

    # baseline（关键：所有字符对齐基准）
    baseline = int(round(font_ascent * scale))

    # 预缩放
    scaled_glyphs = {}

    for code, (w, h, x_off, y_off, advance, bitmap) in glyphs.items():
        new_w, new_h, scaled = scale_bitmap(bitmap, scale)

        new_x_off = int(round(x_off * scale))
        new_y_off = int(round(y_off * scale))
        new_advance = int(round(advance * scale))

        scaled_glyphs[code] = (new_w, new_h, new_x_off, new_y_off, new_advance, scaled)

    # 计算每字符字节数对齐存储
    if vertical:
        height_byte = (cell_height + 7) // 8
        cell_bytes = cell_width * height_byte
    else:
        width_byte = (cell_width + 7) // 8
        cell_bytes = cell_height * width_byte

    total_chars = 0x10000
    buffer = bytearray(cell_bytes * total_chars)

    # 主循环（遍历 Unicode BMP）
    for code in range(total_chars):
        if code % 0x1000 == 0:
            sys.stdout.write(f"\rProcessing {code:04X}/FFFF")
            sys.stdout.flush()

        # 初始化 cell（全白）
        cell = [[False] * cell_width for _ in range(cell_height)]

        if code in scaled_glyphs:
            w, h, x_off, y_off, advance, bitmap = scaled_glyphs[code]

            # 横向：advance width 居中
            dx = (advance - w) // 2 + x_off + offset_x

            # 纵向：baseline 对齐
            top = baseline - (h + y_off) + offset_y

            # 绘制 glyph
            for y in range(h):
                py = top + y
                if py < 0 or py >= cell_height:
                    continue

                for x in range(w):
                    if bitmap[y][x]:
                        px = dx + x
                        if 0 <= px < cell_width:
                            cell[py][px] = True

        base = code * cell_bytes

        # 写入 buffer（bit packing）
        if vertical:
            for y in range(cell_height):
                for x in range(cell_width):
                    if cell[y][x]:
                        byte_idx = x * height_byte + (y // 8)
                        bit_idx = 7 - (y % 8)
                        buffer[base + byte_idx] |= 1 << bit_idx
        else:
            for y in range(cell_height):
                for x in range(cell_width):
                    if cell[y][x]:
                        byte_idx = y * width_byte + (x // 8)
                        bit_idx = 7 - (x % 8)
                        buffer[base + byte_idx] |= 1 << bit_idx

    print("\nWriting file...")
    with open(output_path, "wb") as f:
        f.write(buffer)

    print(f"Done: {output_path}")


# 生成预览字体图片
# 半角字符在预览时会显示为全宽，最后生成的字体是正常宽度
def generate_preview(
    bdf_path, output_image, text, cell_width, cell_height, scale, offset_x, offset_y
):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Please install Pillow: pip install pillow")
        return

    glyphs, font_ascent, font_descent = parse_bdf(bdf_path)

    if cell_width == 0 or cell_height == 0:
        cell_width, cell_height = compute_cell_size(
            glyphs, font_ascent, font_descent, scale
        )

    baseline = font_ascent * scale

    # 预缩放
    scaled_glyphs = {}
    for code, (w, h, x_off, y_off, advance, bitmap) in glyphs.items():
        new_w, new_h, scaled = scale_bitmap(bitmap, scale)

        scaled_glyphs[code] = (
            new_w,
            new_h,
            x_off * scale,
            y_off * scale,
            advance * scale,
            scaled,
        )

    lines = text.split("\n")

    img_w = max(len(line) for line in lines) * cell_width
    img_h = len(lines) * cell_height

    img = Image.new("1", (img_w, img_h), 1)
    draw = ImageDraw.Draw(img)

    y_cursor = 0

    for line in lines:
        x_cursor = 0

        for ch in line:
            code = ord(ch)

            if code in scaled_glyphs:
                w, h, x_off, y_off, advance, bitmap = scaled_glyphs[code]

                dx = (advance - w) // 2 + x_off + offset_x
                top = baseline - (h + y_off) + offset_y

                for y in range(h):
                    py = y_cursor + top + y
                    if py < 0 or py >= img_h:
                        continue

                    for x in range(w):
                        if bitmap[y][x]:
                            px = x_cursor + dx + x
                            if 0 <= px < img_w:
                                draw.point((px, py), 0)

            x_cursor += cell_width

        y_cursor += cell_height

    img.save(output_image)
    print(f"Preview saved to {output_image}")


# --------------------------------------------------------------
# CLI
# --------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="BDF to BIN converter (baseline + advance width)"
    )

    parser.add_argument("bdf")
    parser.add_argument("output")

    parser.add_argument("--cell-width", type=int, default=0)
    parser.add_argument("--cell-height", type=int, default=0)

    parser.add_argument(
        "--scale", type=int, default=1, help="Integer scaling factor (>=1)"
    )
    parser.add_argument("--offset-x", type=int, default=0)
    parser.add_argument("--offset-y", type=int, default=0)

    parser.add_argument("--vertical", action="store_true")

    parser.add_argument("--preview", type=str, help="Output preview image")

    args = parser.parse_args()
    if args.scale < 1:
        print("Error: scale must be >= 1")
        sys.exit(1)
    if args.scale > 8:
        print("Warning: scale too large may consume a lot of memory")

    if args.preview:
        sample_text = (
            "中国智造，慧及全球。中國智造，慧及全球。\n"
            "THE QUICK BROWN·FOX JUMPS OVER A LAZY DOG.\n"
            "the quick brown·fox jumps over a lazy dog.\n"
            "01234567890Oo1lIga\n"
            ".。，|？|！“……”‘——’（）【】《》/->+\n"
            "①②⑨한국어あさひ・テレビ／℃＄¤￠￡‰§№★⒛⑴＊"
        )

        generate_preview(
            args.bdf,
            args.preview,
            sample_text,
            args.cell_width,
            args.cell_height,
            args.scale,
            args.offset_x,
            args.offset_y,
        )

        if input("Continue to generate binary? (y/N): ").lower() != "y":
            return

    convert_bdf_to_bin(
        bdf_path=args.bdf,
        output_path=args.output,
        cell_width=args.cell_width,
        cell_height=args.cell_height,
        scale=args.scale,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        vertical=args.vertical,
    )


if __name__ == "__main__":
    main()

# python bdf2bin.py Fusion-Pixel-8px-Mono-All-Regular.bdf output.bin --preview preview.png
# python bdf2bin.py Fusion-Pixel-8px-Mono-All-Regular.bdf Fusion-Pixel-8-scale3.bin  --cell-width 24  --cell-height 24  --scale 3  --offset-x 0  --offset-y 0 --preview preview.png
