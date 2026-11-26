"""
文本清洗模块

职责：
- 接收 converter 产出的原始 Markdown 文本
- 去掉噪音（多余空行、页眉页脚、乱码、无意义的短行）
- 输出干净的纯文本，交给 splitter 切分

设计原则：
  清洗要"保守"——宁可少删不要多删。
  因为切分器依赖 ## / ### 标题来定位章节，
  所以标题行绝对不能动。
"""

import re
from app.config import config


def clean_markdown(raw_text: str) -> str:
    """
    主入口：对原始 Markdown 文本做一轮清洗

    处理顺序：
      1. 统一换行符
      2. 去掉页眉页脚（常见模式）
      3. 去掉连续空行（>3 个换行压缩为 2 个）
      4. 去掉行尾多余空格
      5. 去掉纯空白的短行（< 5 个字符且不是标题）
      6. 去掉 OCR 残留的孤立标点行
    """
    text = raw_text

    # 1. 统一换行
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. 去掉常见页眉页脚模式
    #    例如："第 1 页 / 共 20 页"、"Page 1 of 20"、"Company Confidential"
    text = _remove_header_footer(text)

    # 3. 压缩连续空行：3+ 个连续换行 → 2 个
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 4. 逐行清洗
    lines = text.split("\n")
    cleaned_lines = []

    for line in lines:
        line = line.rstrip()  # 去掉行尾空格

        # 跳过纯空白行（后面会统一压缩空行，这里先不过滤）
        if not line.strip():
            cleaned_lines.append("")
            continue

        # 标题行：原样保留，不动
        if line.startswith("#"):
            cleaned_lines.append(line)
            continue

        # 跳过过短的纯标点/符号行（OCR 垃圾）
        stripped = line.strip()
        if len(stripped) < 5 and re.match(r"^[\s\W\d]*$", stripped):
            continue

        cleaned_lines.append(line)

    # 5. 重新拼接，再压一次空行
    result = "\n".join(cleaned_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()


def _remove_header_footer(text: str) -> str:
    """
    去掉页眉页脚

    常见模式（可随实际文档补充）：
      - "第 X 页"
      - "Page X of Y"
      - "Company Name | Confidential"
      - 连续出现的短行（< 30 字符）出现在文本开头或结尾
    """
    lines = text.split("\n")

    # 去掉开头可能的页眉（前 5 行里找）
    start_idx = 0
    for i, line in enumerate(lines[:5]):
        if re.search(r"(第\s*\d+\s*页|Page\s*\d+\s*of|Confidential|机密)", line, re.IGNORECASE):
            start_idx = i + 1

    # 去掉结尾可能的页脚（后 5 行里找）
    end_idx = len(lines)
    for i, line in enumerate(reversed(lines[-5:])):
        if re.search(r"(第\s*\d+\s*页|Page\s*\d+\s*of|Confidential|机密)", line, re.IGNORECASE):
            end_idx = len(lines) - i - 1

    return "\n".join(lines[start_idx:end_idx])