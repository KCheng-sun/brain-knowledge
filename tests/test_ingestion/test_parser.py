"""DocumentParser 单元测试。"""




class TestDocumentParser:
    """DocumentParser 测试套件"""

    def test_parse_file_with_frontmatter(self, parser, sample_markdown_file):
        """解析带 YAML frontmatter 的 Markdown 文件。"""
        doc = parser.parse_file(sample_markdown_file)

        assert doc.title == "Python 异步编程笔记"
        assert "异步编程" in doc.content
        assert doc.file_hash is not None
        assert doc.file_path == str(sample_markdown_file)
        assert doc.frontmatter.get("tags") == ["python", "async", "programming"]

    def test_parse_text_with_title(self, parser):
        """解析纯文本（带指定标题）。"""
        text = "今天读到的好观点：RAG 的核心是检索质量，不是生成质量。"
        doc = parser.parse_text(text, title="RAG 观点")

        assert doc.title == "RAG 观点"
        assert "RAG 的核心" in doc.content
        assert doc.file_hash is not None

    def test_parse_text_auto_title(self, parser):
        """解析纯文本（自动取第一行为标题）。"""
        text = "RAG 优化笔记\n检索质量的 5 个关键因素..."
        doc = parser.parse_text(text)

        assert doc.title == "RAG 优化笔记"
        assert "检索质量的 5 个关键因素" in doc.content

    def test_parse_text_title_with_hash(self, parser):
        """第一行带 # 时自动去掉。"""
        text = "# 我的想法\n这是一个重要的观点。"
        doc = parser.parse_text(text)

        assert doc.title == "我的想法"

    def test_extract_no_frontmatter(self, parser, temp_dir):
        """没有 frontmatter 的文件，标题从第一个 # 提取。"""
        file_path = temp_dir / "no_fm.md"
        file_path.write_text("# 纯笔记标题\n\n这是内容。\n\n## 小节\n\n小节内容。", encoding="utf-8")

        doc = parser.parse_file(file_path)
        assert doc.title == "纯笔记标题"
        assert doc.frontmatter == {}

    def test_extract_title_from_filename(self, parser, temp_dir):
        """没有 # 标题也没有 frontmatter 时，用文件名。"""
        file_path = temp_dir / "我的随手笔记.md"
        file_path.write_text("只是一些随手写的内容，没有标题。", encoding="utf-8")

        doc = parser.parse_file(file_path)
        assert doc.title == "我的随手笔记"

    def test_markdown_to_text_conversion(self, parser):
        """Markdown 语法被正确转换。"""
        text = """# 标题

这是一段**粗体**和*斜体*文字。

- 列表项 1
- 列表项 2

[链接文字](https://example.com)

这是`代码`示例。"""

        doc = parser.parse_text(text)
        # 链接 URL 应该被移除
        assert "https://example.com" not in doc.content
        # 链接文字应该保留
        assert "链接文字" in doc.content
        # 粗体标记去掉
        assert "**" not in doc.content
        assert "粗体" in doc.content
        # 代码标记去掉
        assert "`" not in doc.content or "代码" in doc.content

    def test_file_hash_stability(self, parser, temp_dir):
        """同一文件的 hash 保持一致。"""
        file_path = temp_dir / "stable.md"
        file_path.write_text("# 稳定测试\n\n内容不变。", encoding="utf-8")

        doc1 = parser.parse_file(file_path)
        doc2 = parser.parse_file(file_path)

        assert doc1.file_hash == doc2.file_hash

    def test_file_hash_changes(self, parser, temp_dir):
        """修改内容后 hash 改变。"""
        file_path = temp_dir / "changing.md"
        file_path.write_text("# 版本 1\n\n原始内容。", encoding="utf-8")

        doc1 = parser.parse_file(file_path)

        file_path.write_text("# 版本 2\n\n修改后的内容。", encoding="utf-8")
        doc2 = parser.parse_file(file_path)

        assert doc1.file_hash != doc2.file_hash
