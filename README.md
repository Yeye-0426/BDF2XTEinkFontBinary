# BDF → E-Ink 字体二进制转换工具

> 一个用于将 **BDF（Bitmap Distribution Format）位图字体** 转换为 **电子墨水屏（E-Ink）固定网格二进制格式** 的 Python 工具。

---

## ✨ 项目特性

- ✅ 基于 `FONT_ASCENT` 的 **基线对齐（baseline alignment）**
- ✅ 使用 `DWIDTH` 的 **字符逻辑宽度（advance width）**
- ✅ 支持 **整数倍缩放（无失真像素复制）**
- ✅ 支持 **预览 PNG（生成前可视化）**
- ✅ 支持 **Unicode BMP 全字符集（0x0000 - 0xFFFF）**

---

## 🔹 基本用法

```bash
python bdf2bin.py font.bdf output.bin --preview preview.png
```

## ⚙️ 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--cell-width` | int | 0 | 字符宽度（0 = 自动计算） |
| `--cell-height` | int | 0 | 字符高度（0 = 自动计算） |
| `--scale` | int | 1 | 缩放倍数（整数 ≥ 1） |
| `--offset-x` | int | 0 | 横向偏移（像素） |
| `--offset-y` | int | 0 | 纵向偏移（像素） |
| `--vertical` | flag | False | 使用列优先存储（column-major） |
| `--preview` | str | None | 输出预览图片路径（PNG） |
