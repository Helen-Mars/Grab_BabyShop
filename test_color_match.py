"""
颜色匹配功能测试
"""
import re
import pytest


def test_pink_japanese_match():
    """测试能匹配日文ピンク"""
    test_colors = [
        "ピンク",
        "Pink", 
        "ピンク×オフ白 Pink×White",
        "サックス×ピンク Saxe blue×Pink",
        "ブルー Blue",
        "レッド Red",
    ]
    
    pattern = re.compile(r"ピンク", re.IGNORECASE)
    matches = [c for c in test_colors if pattern.search(c)]
    
    assert "ピンク" in matches
    assert "ピンク×オフ白 Pink×White" in matches
    assert "サックス×ピンク Saxe blue×Pink" in matches
    assert len(matches) == 3


def test_pink_english_match():
    """测试能匹配英文Pink"""
    test_colors = [
        "ピンク",
        "Pink", 
        "ピンク×オフ白 Pink×White",
        "サックス×ピンク Saxe blue×Pink",
        "ブルー Blue",
        "レッド Red",
    ]
    
    pattern = re.compile(r"Pink", re.IGNORECASE)
    matches = [c for c in test_colors if pattern.search(c)]
    
    assert "Pink" in matches
    assert "ピンク×オフ白 Pink×White" in matches
    assert "サックス×ピンク Saxe blue×Pink" in matches
    assert len(matches) == 3


def test_combined_pattern_match():
    """测试组合模式匹配（ピンク|Pink）"""
    test_colors = [
        "ピンク",
        "Pink", 
        "ピンク×オフ白 Pink×White",
        "サックス×ピンク Saxe blue×Pink",
        "ブルー Blue",
        "レッド Red",
    ]
    
    pattern = re.compile(r"ピンク|Pink", re.IGNORECASE)
    matches = [c for c in test_colors if pattern.search(c)]
    
    assert len(matches) == 4  # 应该匹配到4个


def test_primary_match_priority():
    """测试主匹配优先级（以颜色开头）"""
    test_colors = [
        "ピンク",
        "Pink", 
        "ピンク×オフ白 Pink×White",
        "サックス×ピンク Saxe blue×Pink",
    ]
    
    primary_pattern = re.compile(r"^\s*(?:ピンク|Pink)", re.IGNORECASE)
    fuzzy_pattern = re.compile(r"ピンク|Pink", re.IGNORECASE)
    
    primary_matches = []
    fuzzy_matches = []
    
    for color in test_colors:
        if primary_pattern.search(color):
            primary_matches.append(color)
        elif fuzzy_pattern.search(color):
            fuzzy_matches.append(color)
    
    # 主匹配应该包含：ピンク, Pink, ピンク×オフ白 Pink×White
    assert "ピンク" in primary_matches
    assert "Pink" in primary_matches
    assert "ピンク×オフ白 Pink×White" in primary_matches
    
    # 模糊匹配应该包含：サックス×ピンク Saxe blue×Pink
    assert "サックス×ピンク Saxe blue×Pink" in fuzzy_matches
