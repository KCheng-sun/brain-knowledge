"""BaseAgent 基类测试 — 验证结构化/纯文本两种模式的选择逻辑。

不实际调用 LLM，用 mock 验证 run() 根据 output_model 是否为 None 走不同分支。
"""

from unittest.mock import MagicMock, patch

from brain.agents.base import BaseAgent
from brain.agents.classifier import ClassifierAgent


class TestModeSelection:
    """验证 run() 根据 output_model 选择结构化或纯文本模式。"""

    def test_structured_mode_when_output_model_set(self):
        """output_model 非 None 时走 with_structured_output 分支。"""
        agent = ClassifierAgent()  # output_model = ClassificationOutput
        assert agent.output_model is not None

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = "structured_result"
        mock_llm.with_structured_output.return_value = mock_structured

        with patch("brain.agents.base.get_chat_model", return_value=mock_llm):
            result = agent.run(note_title="测试", content="内容")

        # 应调用 with_structured_output（结构化模式）
        mock_llm.with_structured_output.assert_called_once()
        assert result == "structured_result"

    def test_text_mode_when_output_model_none(self):
        """output_model = None 时走普通 invoke 分支，不套结构化。"""

        class TextAgent(BaseAgent):
            name = "text_agent"
            output_model = None  # 纯文本模式

            def build_user_prompt(self, **kwargs) -> str:
                return "请生成一段摘要"

        agent = TextAgent()
        assert agent.output_model is None

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="这是摘要文本")

        with patch("brain.agents.base.get_chat_model", return_value=mock_llm):
            result = agent.run(text="内容")

        # 不应调用 with_structured_output
        mock_llm.with_structured_output.assert_not_called()
        # 应直接调 llm.invoke
        mock_llm.invoke.assert_called_once()
        # 返回 AIMessage（子类取 .content）
        assert result.content == "这是摘要文本"

    def test_text_mode_returns_aimessage_not_string(self):
        """纯文本模式返回 AIMessage 对象，子类需取 .content 获得文本。"""

        class TextAgent(BaseAgent):
            name = "text_agent"
            output_model = None

            def build_user_prompt(self, **kwargs) -> str:
                return "prompt"

        agent = TextAgent()
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="文本")

        with patch("brain.agents.base.get_chat_model", return_value=mock_llm):
            result = agent.run()

        # 返回的是 AIMessage（mock），不是字符串
        assert hasattr(result, "content")
        assert result.content == "文本"
