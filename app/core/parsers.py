# app/core/parsers.py

import re
from pathlib import Path

from docx import Document as DocxDocument
import pypdf


def parse_md(file_path: str) -> str:
    """解析 Markdown 文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def parse_docx(file_path: str) -> str:
    """解析 docx，标题转 markdown 格式方便后续切分"""
    doc = DocxDocument(file_path)
    parts = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        # 标题样式 → markdown 标题
        if para.style.name.startswith("Heading"):
            level_str = para.style.name.replace("Heading ", "").strip()
            try:
                level = int(level_str)
            except ValueError:
                level = 1
            parts.append(f"\n{'#' * level} {text}\n")
        else:
            parts.append(text)

    # 提取表格
    for table in doc.tables:
        header_cells = [cell.text.strip() for cell in table.rows[0].cells]
        parts.append("\n| " + " | ".join(header_cells) + " |")
        parts.append("|" + "|".join(["---"] * len(header_cells)) + "|")
        for row in table.rows[1:]:
            cells = [cell.text.strip() for cell in row.cells]
            parts.append("| " + " | ".join(cells) + " |")
        parts.append("")

    return "\n".join(parts)


def parse_pdf(file_path: str) -> str:
    """解析 PDF"""
    parts = []
    with open(file_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            text = page.extract_text()
            if text and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts)


def parse_file(file_path: str) -> str:
    """根据后缀自动分发"""
    ext = Path(file_path).suffix.lower()
    parsers = {
        ".md": parse_md,
        ".markdown": parse_md,
        ".docx": parse_docx,
        ".pdf": parse_pdf,
    }
    parser = parsers.get(ext)
    if not parser:
        raise ValueError(f"不支持的文件格式: {ext}，仅支持 .md / .docx / .pdf")
    return parser(file_path)