"""
文档切分模块

职责：
- 按标题层级（## / ###）定位章节边界
- 在每个章节内按字数窗口滑动切分
- 保证每个 chunk 在 200～600 字之间
- 相邻 chunk 之间保留 80 字重叠（保证语义连贯）

切分策略回顾（你手动验证过的）：
  1. 先用 ## / ### 把文档拆成"章节块"
  2. 每个章节块内部，如果超过 600 字，按 520 字窗口 + 80 字步长滑动
  3. 如果章节块本身就在 200～600 字之间，直接作为一个 chunk
  4. 如果章节块 < 200 字，直接作为一个 chunk

输出每个 chunk 携带：
  - chunk_id:   "{doc_id}_C{序号:02d}"
  - content:    切出来的纯文本
  - chapter:    所属章节路径（如 "第三章 > 3.2 住宿费"）
"""

import re
from dataclasses import dataclass, field
from app.config import config


@dataclass
class Chunk:
    """切分后的一个文本块"""
    chunk_id: str = ""
    content: str = ""
    chapter: str = ""
    char_count: int = 0


def split_document(
    text: str,
    doc_id: str,
    source_name: str,
) -> list[Chunk]:
    """
    主入口：把清洗后的全文切成 chunks

    参数：
      - text:        清洗后的 Markdown 全文
      - doc_id:      文档 UUID
      - source_name: 文档名（用于 chapter 拼接）

    返回：
      Chunk 对象列表
    """
    # Step 1: 按标题拆成章节
    sections = _split_by_headers(text)

    # Step 2: 每个章节内部切分
    chunks = []
    chunk_seq = 1

    for section in sections:
        content= section["content"]
        chapter_path = section["chapter_path"]
        # 1. 章节的字小于200直接自成一块
        if len(content) < config.split.chunk_min_size:
            chunks.append(Chunk(
                chunk_id=f"{doc_id}_C{chunk_seq:02d}",
                content=content.strip(),
                chapter=chapter_path or "unknown",
                char_count=len(content),
            ))
            chunk_seq += 1
            continue
        # 3. 大于200 → 交给切分函数
        section_chunks = _split_section(
            content,
            chapter_path,
            doc_id,
            chunk_seq,
        )
        chunks.extend(section_chunks)
        chunk_seq += len(section_chunks)
    return chunks


# ============================================================
# 内部函数
# ============================================================

def _split_by_headers(text: str) -> list[dict]:
    """
    按 ## / ### 标题把全文拆成章节

    返回：[{"chapter_path": "第二章 > 2.1 交通费", "content": "..."}, ...]

    逻辑：
      - 遇到 ## 或 ### 就开一个新章节
      - 标题文本本身作为 chapter 的一部分
      - 标题层级通过 # 的个数判断
    """
    lines = text.split("\n")
    sections = []
    current_level = 0       # 当前章节层级（2=##, 3=###）
    current_title = ""      # 当前章节标题文本
    current_lines = []
    chapter_stack = []      # 章节路径栈，用于构建 "第二章 > 2.1 交通费"

    for line in lines:
        header_match = re.match(r"^(#{2,3})\s+(.+)$", line)

        if header_match:
            # 保存上一个章节
            if current_lines:
                sections.append({
                    "chapter_path": " > ".join(chapter_stack) if chapter_stack else "未分类",
                    "content": "\n".join(current_lines).strip(),
                })

            # 开始新章节
            level = len(header_match.group(1))  # 2 or 3
            title = header_match.group(2).strip()

            # 维护章节路径栈
            if level == 2:
                chapter_stack = [title]       # ## 开新一级
            elif level == 3:
                if chapter_stack:
                    chapter_stack.append(title)  # ### 挂在当前 ## 下
                else:
                    chapter_stack = [title]      # 没有 ## 直接 ###

            current_lines = [line]  # 标题行本身也保留在内容里

        else:
            current_lines.append(line)

    # 最后一个章节
    if current_lines:
        sections.append({
            "chapter_path": " > ".join(chapter_stack) if chapter_stack else "未分类",
            "content": "\n".join(current_lines).strip(),
        })

    return sections


def _split_section(
    content: str,
    chapter_path: str,
    doc_id: str,
    start_seq: int,
) -> list[Chunk]:
    """
    单个章节内部按字数窗口切分

    规则：
      - 200 ≤ 章节 ≤ 600 字 → 直接作为一个 chunk
      - 章节 > 600 字 → 滑动窗口切分
    """
    char_count = len(content)

    # 正好在范围内：一个 chunk
    if char_count <= config.split.chunk_max_size:
        return [Chunk(
            chunk_id=f"{doc_id}_C{start_seq:02d}",
            content=content,
            chapter=chapter_path,
            char_count=char_count,
        )]

    # 超长：滑动窗口
    chunks = []
    window = config.split.chunk_max_size - config.split.overlap_size  # 520
    overlap = config.split.overlap_size                               # 80
    step = window                                                      # 每次前进 520 字
    seq = start_seq

    start = 0
    while start < char_count:
        end = min(start + config.split.chunk_max_size, char_count)
        chunk_text = content[start:end]

        # 如果不是最后一块，尝试在句号/换行处断开（让边界更自然）
        if end < char_count:
            chunk_text = _trim_to_sentence_boundary(chunk_text, content[end:end+20])

        # 检查：剩余部分是否太小 → 合并到当前块（即最后一块）
        # 判断：下一次 start + step 之后，剩余是否太小
        next_start = start + step
        if next_start >= char_count - config.split.chunk_min_size:
            # 把剩余内容全拼进来
            chunk_text = content[start:char_count]
            chunks.append(Chunk(
                chunk_id=f"{doc_id}_C{seq:02d}",
                content=chunk_text.strip(),
                chapter=chapter_path,
                char_count=len(chunk_text),
            ))
            break

        chunks.append(Chunk(
            chunk_id=f"{doc_id}_C{seq:02d}",
            content=chunk_text.strip(),
            chapter=chapter_path,
            char_count=len(chunk_text),
        ))

        seq += 1
        start += step


    return chunks


def _trim_to_sentence_boundary(text: str, lookahead: str) -> str:
    """
    尝试在句子边界截断，而不是硬切在半句话中间

    策略：从文本末尾往前找最近的句号/问号/换行
    如果找不到，就保持原样（硬切）
    """
    # 在 text 末尾 + lookahead 里找第一个句子结束符
    combined = text + lookahead
    for punct in ["\n\n", "。", "！", "？", "\n"]:
        idx = combined.rfind(punct)
        if idx > 0 and idx < len(text):
            return combined[:idx + len(punct)]

    return text