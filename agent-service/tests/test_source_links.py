import unittest
from agent_service.source_links import bound_source_links


class SourceLinkTests(unittest.TestCase):
    def test_allowlist_preserves_actual_source_and_learning_record(self):
        text = '[文档](https://docs.example/a) <https://docs.example/a> https://docs.example/a。 [旧记录](reviewtoday://memory/123)'
        self.assertEqual(bound_source_links(text, ['https://docs.example/a']), text)

    def test_unread_markdown_autolink_and_bare_urls_are_not_clickable_sources(self):
        text = '[文档](https://unknown.example/a) <https://unknown.example/b> https://unknown.example/c。'
        result = bound_source_links(text, [])
        self.assertNotIn('https://', result)
        self.assertEqual(result, '文档（链接未核验） （链接未核验） （链接未核验）。')

    def test_code_examples_are_not_citations_even_while_streaming(self):
        text = '`https://example.com/api`\n\n```python\nurl = "https://example.com/api"\n```\n\n正文 <https://unknown.example>'
        result = bound_source_links(text, [])
        self.assertEqual(result.count('https://example.com/api'), 2)
        self.assertNotIn('https://unknown', result)
        code = '```python\nurl = "https://example.com/api"\n```'
        for end in range(len(code) + 1):
            self.assertEqual(bound_source_links(code[:end], []), code[:end])

    def test_each_prose_stream_prefix_hides_unread_url_and_preserves_surrounding_text(self):
        for text in ['开头 [文档](https://unknown.example/a) 结尾', '开头 <https://unknown.example/a> 结尾', '开头 https://unknown.example/a 结尾']:
            for end in range(len(text) + 1):
                self.assertNotIn('https://', bound_source_links(text[:end], []))
            self.assertTrue(bound_source_links(text, []).endswith(' 结尾'))

    def test_url_prefix_is_not_an_allowed_source(self):
        self.assertNotIn('https://', bound_source_links('<https://docs.example>', ['https://docs.example/page']))
        self.assertNotIn('https://', bound_source_links('<https://docs.example/other>', ['https://docs.example']))

    def test_actual_source_with_parentheses_is_kept_exactly(self):
        url = 'https://en.wikipedia.org/wiki/Harness_(computing)'
        text = f'[Harness]({url}) <{url}> {url}。'
        self.assertEqual(bound_source_links(text, [url]), text)
