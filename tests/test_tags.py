"""
Tests for tag parsing and joining utilities.
"""
from app.utils.tags import parse_tags, join_tags


class TestParseTags:
    """parse_tags() splits comma-separated strings into trimmed lists."""

    def test_normal_input(self):
        assert parse_tags("python, fastapi, web") == ["python", "fastapi", "web"]

    def test_extra_whitespace(self):
        assert parse_tags("  tag1  ,  tag2  ") == ["tag1", "tag2"]

    def test_empty_string(self):
        assert parse_tags("") == []

    def test_whitespace_only(self):
        assert parse_tags("   ") == []

    def test_single_tag(self):
        assert parse_tags("alone") == ["alone"]

    def test_trailing_comma(self):
        # Trailing comma produces an empty split element, which should be filtered
        assert parse_tags("a, b, ") == ["a", "b"]

    def test_consecutive_commas(self):
        assert parse_tags("a,,b") == ["a", "b"]


class TestJoinTags:
    """join_tags() joins tag lists with ', ' separator."""

    def test_normal_list(self):
        assert join_tags(["python", "fastapi", "web"]) == "python, fastapi, web"

    def test_empty_list(self):
        assert join_tags([]) == ""

    def test_single_tag(self):
        assert join_tags(["single"]) == "single"

    def test_strips_whitespace(self):
        assert join_tags(["  a  ", "  b  "]) == "a, b"

    def test_filters_empty_strings(self):
        assert join_tags(["a", "", "  ", "b"]) == "a, b"
