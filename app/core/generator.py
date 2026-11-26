"""
DeepSeek LLM 调用封装（LangChain 版）

职责：
- 用 LangChain 的 ChatOpenAI 调用 DeepSeek（兼容 OpenAI 格式）
- 用 LangChain 的 ChatPromptTemplate 组装 Prompt
- 用 LCEL 管道（prompt | llm | parser）串联
- 返回生成文本 + 引用来源

为什么用 LangChain：
  1. Prompt 模板管理更规范（变量插值、系统/用户角色分离）
  2. 流式输出、重试、回调等开箱即用
  3. 后续切模型（Qwen / Ollama）只改一行
"""

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.config import config

# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_TEMPLATE = """你是企业知识库助手。请严格基于以下提供的知识片段回答用户问题。

## 回答要求

1. 只基于知识片段回答，不要编造未提供的信息
2. 如果知识库中没有相关信息，明确告知"知识库中未找到相关内容"
3. 引用来源时使用 [1]、[2] 等编号对应上方片段
4. 回答简洁清晰，适合企业内部使用
5. 如果检索到的知识片段与问题明显无关，明确告知"知识库中未找到确切相关信息"，不要强行从无关内容中推断答案"""

USER_TEMPLATE = """## 知识库内容

{context}

---

## 用户问题

{question}"""


def _build_prompt_template() -> ChatPromptTemplate:
    """构建 LangChain Prompt 模板（系统 + 用户两条消息）"""
    return ChatPromptTemplate.from_messages([
        ("system", SYSTEM_TEMPLATE),
        ("user", USER_TEMPLATE),
    ])


# ============================================================
# LLM 实例（单例）
# ============================================================

_llm = None


def _get_llm() -> ChatOpenAI:
    """
    懒加载 LangChain 的 ChatOpenAI（指向 DeepSeek）
    全局单例，连接池和内部 httpx client 复用
    """
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=config.llm.model,                 # "deepseek-chat"
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,           # "https://api.deepseek.com"
            temperature=config.llm.temperature,     # 0.1
            max_tokens=config.llm.max_tokens,       # 800
            streaming=False,
            max_retries=2,                          # 自动重试
            request_timeout=60,                     # 超时秒数
        )
    return _llm


# ============================================================
# 上下文格式化
# ============================================================

def _format_contexts(contexts: list[dict]) -> str:
    """
    把检索结果格式化成 Prompt 里的上下文字符串

    参数 contexts: [{"content": "...", "metadata": {...}}, ...]
    """
    parts = []
    for i, ctx in enumerate(contexts, 1):
        meta = ctx.get("metadata", {})
        source = meta.get("source", "未知文档")
        chapter = meta.get("chapter", "")
        ref_label = f"[{i}] {source}"
        if chapter:
            ref_label += f" · {chapter}"
        parts.append(f"{ref_label}\n{ctx['content']}")

    return "\n\n---\n\n".join(parts)


# ============================================================
# 主入口
# ============================================================

async def generate(question: str, contexts: list[dict]) -> dict:
    """
    调用 DeepSeek 生成回答（LangChain LCEL 管道）

    流程：
      prompt_template.format(context, question)
        → ChatOpenAI 调用 DeepSeek
        → StrOutputParser 提取文本

    返回：
    {
        "answer": "生成的回答文本",
        "sources": [{"source": "...", "chapter": "...", "doc_id": "..."}, ...]
    }
    """
    llm = _get_llm()
    prompt_template = _build_prompt_template()
    parser = StrOutputParser()

    # LCEL 管道：prompt → llm → parser
    chain = prompt_template | llm | parser

    # 格式化上下文
    context_str = _format_contexts(contexts)

    # 异步调用（ainvoke 是 LangChain 的异步接口）
    answer = await chain.ainvoke({
        "context": context_str,
        "question": question,
    })

    # 提取引用来源（去重）
    sources = []
    seen = set()
    for ctx in contexts:
        meta = ctx.get("metadata", {})
        key = meta.get("doc_id", "")
        if key and key not in seen:
            seen.add(key)
            sources.append({
                "doc_id": key,
                "source": meta.get("source", ""),
                "chapter": meta.get("chapter", ""),
            })

    return {
        "answer": answer,
        "sources": sources,
    }