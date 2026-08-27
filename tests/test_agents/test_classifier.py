"""ClassifierAgent 单元测试 — 用 mock LLM 响应验证输出格式。"""

import json

import pytest

from brain.agents.classifier import ClassificationOutput, ClassifierAgent, TopicItem, TypeItem


class TestClassifierOutput:
    """验证 ClassificationOutput 的 Pydantic 模型"""

    def test_valid_output(self):
        """正常的分类结果能被正确解析。"""
        data = {
            "topics": [
                {"name": "LangGraph", "confidence": 0.95},
                {"name": "Agent 架构", "confidence": 0.80},
            ],
            "content_type": {"name": "总结/笔记", "confidence": 0.90},
        }
        output = ClassificationOutput(**data)
        assert len(output.topics) == 2
        assert output.topics[0].name == "LangGraph"
        assert output.topics[0].confidence == 0.95
        assert output.content_type.name == "总结/笔记"

    def test_empty_topics(self):
        """没有识别到主题时也不报错。"""
        data = {
            "topics": [],
            "content_type": {"name": "摘录/引用", "confidence": 0.99},
        }
        output = ClassificationOutput(**data)
        assert output.topics == []

    def test_to_tags(self):
        """to_tags 方法正确转换。"""
        output = ClassificationOutput(
            topics=[
                TopicItem(name="Python", confidence=0.95),
                TopicItem(name="RAG", confidence=0.70),
            ],
            content_type=TypeItem(name="教程/指南", confidence=0.90),
        )

        tags = ClassifierAgent.to_tags(output)
        assert len(tags) == 3  # 2 topics + 1 type

        # 验证主题标签
        topic_tags = [t for t in tags if t.category.value == "topic"]
        assert len(topic_tags) == 2
        assert topic_tags[0].name == "Python"
        assert topic_tags[0].is_ai_generated is True

        # 验证类型标签
        type_tags = [t for t in tags if t.category.value == "type"]
        assert len(type_tags) == 1
        assert type_tags[0].name == "教程/指南"


class TestClassifierPrompt:
    """验证 prompt 构建"""

    def test_build_user_prompt(self):
        """prompt 包含标题和内容。"""
        agent = ClassifierAgent()
        prompt = agent.build_user_prompt(
            note_title="Python 异步编程",
            content="asyncio 是 Python 的异步编程库...",
        )
        assert "Python 异步编程" in prompt
        assert "asyncio 是 Python" in prompt

    def test_full_prompt_includes_schema(self):
        """user prompt 包含 JSON 输出格式说明（system_prompt 已分离为单独角色）。"""
        from brain.prompts import get_prompt

        agent = ClassifierAgent()
        # system_prompt 从数据库读取（测试环境回退到默认值）
        sys_prompt = get_prompt("classifier")
        user_prompt = agent._build_user_prompt_with_schema("测试内容")
        assert "你是一个知识分类专家" in sys_prompt
        assert "测试内容" in user_prompt
        assert "topics" in user_prompt.lower()
        assert "content_type" in user_prompt.lower()


class TestJSONParsing:
    """验证 JSON 解析鲁棒性"""

    def test_parse_pure_json(self):
        """纯 JSON 正确解析。"""
        text = '{"topics": [], "content_type": {"name": "观点/思考", "confidence": 0.99}}'
        result = ClassifierAgent._parse_json(text)
        assert result["content_type"]["name"] == "观点/思考"

    def test_parse_json_with_markdown(self):
        """被 ```json``` 包裹的 JSON 正确解析。"""
        text = """```json
{"topics": [{"name": "AI", "confidence": 0.9}], "content_type": {"name": "教程/指南", "confidence": 0.8}}
```"""
        result = ClassifierAgent._parse_json(text)
        assert result["topics"][0]["name"] == "AI"

    def test_parse_json_with_surrounding_text(self):
        """前后有说明文字的 JSON 正确解析。"""
        text = """好的，这是分析结果：

{"topics": [{"name": "Docker", "confidence": 0.95}], "content_type": {"name": "实践/代码", "confidence": 0.9}}

希望这个结果对你有帮助。"""
        result = ClassifierAgent._parse_json(text)
        assert result["topics"][0]["name"] == "Docker"
