"""ClassifierAgent 单元测试 — 用 mock LLM 响应验证输出格式。"""

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
        """run() 用 with_structured_output 绑定 output_model，SDK 层强制结构化。"""
        from brain.prompts import get_prompt

        agent = ClassifierAgent()
        # system_prompt 从数据库读取（测试环境回退到默认值）
        sys_prompt = get_prompt("classifier")
        assert "你是一个知识分类专家" in sys_prompt
        # output_model 是 ClassificationOutput，含 topics/content_type 字段
        fields = agent.output_model.model_fields
        assert "topics" in fields
        assert "content_type" in fields


class TestStructuredOutput:
    """验证 with_structured_output 绑定（不实际调用 API）。

    with_structured_output 在 SDK 层用 function calling 强制结构化，
    invoke 直接返回 Pydantic 实例，不存在「解析」环节，
    无需测试 JSON 解析鲁棒性（原手写 _parse_json 的场景已不适用）。
    """

    def test_output_model_is_classification_output(self):
        """ClassifierAgent 的 output_model 配置正确。"""
        agent = ClassifierAgent()
        assert agent.output_model.__name__ == "ClassificationOutput"

    def test_structured_method_is_function_calling(self):
        """默认用 function_calling（DeepSeek 实测稳定支持）。"""
        agent = ClassifierAgent()
        assert agent._structured_method == "function_calling"

    def test_to_tags_with_valid_output(self):
        """to_tags 能正确处理 with_structured_output 返回的 Pydantic 实例。"""
        output = ClassificationOutput(
            topics=[TopicItem(name="Python", confidence=0.95)],
            content_type=TypeItem(name="教程/指南", confidence=0.90),
        )
        tags = ClassifierAgent.to_tags(output)
        assert len(tags) == 2
        assert tags[0].name == "Python"
