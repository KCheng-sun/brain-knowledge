"""将本地 prompts 表的提示词迁移到 Langfuse Prompt Management（Phase 5G FR66）。

按 Langfuse skill 的 prompt-migration 流程：
  1. 凭证校验（只检查存在性，不打印 secret key）
  2. 读取 DEFAULT_PROMPTS 全部 10 条
  3. {var} → {{var}} 转换（Langfuse 只认双花括号）
  4. create_prompt(name, type="text", labels=["production"])
     - 同名 prompt 会作为新版本追加，不覆盖历史
  5. 验证：get_prompt(name, label="production") 能取回

幂等：重复运行只会新增版本（Langfuse 设计如此），production 标签移到最新版。
迁移后应用侧 brain.prompts.get_prompt 改为优先从 Langfuse 读。

用法::

    python -m brain.scripts.migrate_prompts_to_langfuse

设计依据：https://langfuse.com/docs/prompt-management/get-started
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from brain.storage.prompt_defaults import DEFAULT_PROMPTS


def _check_credentials() -> bool:
    """校验 Langfuse 凭证存在（不打印值）。"""
    has_pub = bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))
    has_sec = bool(os.environ.get("LANGFUSE_SECRET_KEY"))
    has_url = bool(os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST"))
    if not (has_pub and has_sec and has_url):
        print("❌ Langfuse 凭证缺失：")
        print(f"   LANGFUSE_PUBLIC_KEY: {'set' if has_pub else 'missing'}")
        print(f"   LANGFUSE_SECRET_KEY: {'set' if has_sec else 'missing'}")
        print(f"   LANGFUSE_BASE_URL:   {'set' if has_url else 'missing'}")
        print("   请在 .env 配置后重试")
        return False
    print("✅ Langfuse 凭证已配置")
    return True


def _to_langfuse_syntax(content: str, is_template: int) -> str:
    """把 str.format 的 {var} 转成 Langfuse 的 {{var}}。

    纯文本（is_template=0）无占位符，原样返回。
    模板（is_template=1）含 {var}，需转成 {{var}}。

    注意：judge 等提示词的 JSON 示例里有 {{ }}（str.format 的字面花括号转义），
    这些在 Langfuse 里应还原为单层 { }（JSON 语法本身的花括号），不是变量。
    转换规则：
      - str.format 中 {{ → 字面 { ，}} → 字面 }
      - str.format 中 {name} → 变量 {{name}}
    实现思路：先做 str.format 的逆操作（{{ → { 不行，会和变量混），
    改用正则：把 {word} 形式（word 是合法标识符）转成 {{word}}，
    把 {{ 和 }} 还原成 { 和 }（字面花括号）。
    """
    if not is_template:
        return content

    import re

    # 第一步：先把 str.format 的字面花括号转义 {{ }} 还原为 { }
    # （这些是 JSON 示例/代码块里的真实花括号，不是变量）
    text = content.replace("{{", "\x00LBRACE\x00").replace("}}", "\x00RBRACE\x00")
    # 第二步：剩余的 {identifier} 是变量，转成 {{identifier}}
    text = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", r"{{\1}}", text)
    # 第三步：还原字面花括号
    text = text.replace("\x00LBRACE\x00", "{").replace("\x00RBRACE\x00", "}")
    return text


def migrate() -> int:
    """执行迁移，返回迁移条数。"""
    # 确保从项目根目录加载 .env（脚本可能从任意目录运行）
    project_root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(dotenv_path=project_root / ".env", override=True)

    if not _check_credentials():
        return 0

    try:
        from langfuse import get_client
    except ImportError:
        print("❌ langfuse 未安装，请先 pip install langfuse")
        return 0

    lf = get_client()
    if not lf.auth_check():
        print("❌ Langfuse 认证失败，请检查凭证和 LANGFUSE_BASE_URL")
        return 0
    print(f"✅ Langfuse 连接正常 (base_url={os.environ.get('LANGFUSE_BASE_URL')})")

    migrated = 0
    failed = 0
    for key, _name, desc, content, is_template in DEFAULT_PROMPTS:
        # Langfuse prompt name 用 lowercase-hyphenated（skill 要求）
        # 现有 key 已是 snake_case，转成 hyphen（如 query_rewriter → query-rewriter）
        lf_name = key.replace("_", "-")
        lf_content = _to_langfuse_syntax(content, is_template)

        try:
            lf.create_prompt(
                name=lf_name,
                type="text",
                prompt=lf_content,
                labels=["production"],
                commit_message=f"迁移自 brain prompts 表（{desc}）",
            )
            print(f"  ✅ {lf_name} ({'模板' if is_template else '纯文本'})")
            migrated += 1
        except Exception as e:
            print(f"  ❌ {lf_name} 失败: {e}")
            failed += 1

    print(f"\n迁移完成：成功 {migrated}，失败 {failed}")

    # 验证：取回 production 版本确认
    if migrated > 0:
        print("\n=== 验证（get_prompt label=production）===")
        verified = 0
        for key, *_ in DEFAULT_PROMPTS:
            lf_name = key.replace("_", "-")
            try:
                p = lf.get_prompt(lf_name, label="production")
                preview = (p.prompt[:50] + "...") if len(p.prompt) > 50 else p.prompt
                print(f"  ✅ {lf_name} v{p.version}: {preview!r}")
                verified += 1
            except Exception as e:
                print(f"  ❌ {lf_name} 验证失败: {e}")
        print(f"验证通过：{verified}/{migrated}")

    return migrated


if __name__ == "__main__":
    count = migrate()
    sys.exit(0 if count > 0 else 1)
