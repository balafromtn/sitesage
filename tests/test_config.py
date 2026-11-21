"""Tests for config module — verify defaults and constraints."""

import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def test_max_pages_is_30():
    assert config.MAX_PAGES == 30


def test_db_path_is_pathlib():
    assert isinstance(config.DB_PATH, Path)


def test_blocked_ip_prefixes_not_empty():
    assert len(config.BLOCKED_IP_PREFIXES) > 0


def test_blocked_ports_not_empty():
    assert len(config.BLOCKED_PORTS) > 0


def test_bm25_params_positive():
    assert config.BM25_K1 > 0
    assert 0 < config.BM25_B <= 1


def test_ai_polish_disabled_by_default():
    assert config.AI_POLISH_ENABLED is False


def test_boost_values_non_negative():
    assert config.BOOST_TITLE_MATCH >= 0
    assert config.BOOST_HEADING_MATCH >= 0
    assert config.BOOST_POSITION >= 0
    assert config.BOOST_DEPTH_PENALTY >= 0
