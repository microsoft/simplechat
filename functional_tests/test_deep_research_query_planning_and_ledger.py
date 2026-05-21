#!/usr/bin/env python3
"""
Functional test for Deep Research query planning and ledger metadata.
Version: 0.241.066
Implemented in: 0.241.051
Updated in: 0.241.066

This test ensures Deep Research clamps admin budgets, caps user-provided URLs,
plans bounded current-message-only query variants, and records a research ledger
without exposing raw page content as instructions.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_deep_research_config_clamps():
    """Validate Deep Research admin settings are clamped to hard ceilings."""
    from functions_source_review import get_deep_research_config

    default_config = get_deep_research_config({})
    assert default_config['deep_research_max_user_urls_per_turn'] == 100
    assert default_config['deep_research_max_search_queries_per_turn'] == 8
    assert default_config['deep_research_enable_query_planning'] is True
    assert default_config['deep_research_enable_ledger_artifact'] is True
    assert default_config['source_review_allow_js_rendering'] is True
    assert default_config['source_review_js_load_more_clicks'] == 12

    config = get_deep_research_config({
        'enable_source_review': True,
        'deep_research_max_user_urls_per_turn': 999,
        'deep_research_max_search_queries_per_turn': 99,
        'deep_research_enable_query_planning': 'on',
        'deep_research_enable_ledger_artifact': 'true',
    })

    assert config['deep_research_max_user_urls_per_turn'] == 100
    assert config['deep_research_max_search_queries_per_turn'] == 8
    assert config['deep_research_enable_query_planning'] is True
    assert config['deep_research_enable_ledger_artifact'] is True
    return True


def test_user_url_cap_applies_before_search_citations():
    """Validate direct user URLs are capped before search-discovered URLs are added."""
    from functions_source_review import collect_source_review_seed_urls, get_deep_research_config

    message_urls = ' '.join(f'https://example.com/source-{index}' for index in range(5))
    settings = get_deep_research_config({
        'deep_research_max_user_urls_per_turn': 2,
    })
    seed_urls = collect_source_review_seed_urls(
        message_urls,
        [{'url': 'https://official.example.com/release'}],
        settings,
    )

    assert seed_urls[:2] == [
        'https://example.com/source-0',
        'https://example.com/source-1',
    ]
    assert 'https://example.com/source-2' not in seed_urls
    assert 'https://official.example.com/release' in seed_urls
    return True


def test_deterministic_query_plan_is_bounded():
    """Validate fallback query planning uses only the current request and respects max queries."""
    from functions_source_review import build_deep_research_query_plan

    user_message = 'Find 2026 press releases for JPMorgan Chase and Citi from official source pages.'
    plan = build_deep_research_query_plan(
        settings={
            'deep_research_max_search_queries_per_turn': 3,
            'deep_research_enable_query_planning': False,
        },
        user_message=user_message,
        base_query=user_message,
    )

    queries = plan.get('queries', [])
    assert len(queries) <= 3
    assert queries[0]['query'] == user_message
    assert any('official' in item['query'].lower() for item in queries)
    assert all('conversation history' not in item['query'].lower() for item in queries)
    return True


def test_deep_research_ledger_and_markdown():
    """Validate ledger metadata summarizes reviewed and skipped pages."""
    from functions_source_review import build_deep_research_ledger, build_deep_research_ledger_markdown

    source_review_result = {
        'enabled': True,
        'retrieved_at': '2026-01-01T00:00:00+00:00',
        'coverage': {
            'pages_reviewed': 1,
            'pages_skipped': 1,
            'seed_pages_reviewed': 1,
            'child_pages_reviewed': 0,
            'load_more_clicks_succeeded': 2,
        },
        'pages': [{
            'url': 'https://example.com/news/release',
            'title': 'Example Release',
            'published_date': '2026-01-01',
            'depth': 0,
            'source_type': 'official',
            'load_more_clicks_succeeded': 2,
        }],
        'skipped': [{
            'url': 'https://example.com/private',
            'reason': 'robots_txt_disallowed',
            'depth': 0,
        }],
        'citations': [],
        'planner': {},
        'config': {},
    }
    ledger = build_deep_research_ledger(
        settings={'deep_research_max_user_urls_per_turn': 10},
        user_message='Review https://example.com/news',
        query_plan={'queries': [{'query': 'Review https://example.com/news', 'reason': 'base', 'source': 'base'}]},
        web_search_runs=[{'query': 'Review https://example.com/news', 'success': True, 'new_seed_url_count': 1}],
        web_search_citations=[{'url': 'https://example.com/news/release', 'title': 'Example Release'}],
        source_review_result=source_review_result,
    )
    markdown = build_deep_research_ledger_markdown(ledger)

    assert ledger['direct_urls']['count'] == 1
    assert ledger['reviewed_pages'][0]['url'] == 'https://example.com/news/release'
    assert ledger['skipped_pages'][0]['reason'] == 'robots_txt_disallowed'
    assert '# Deep Research Ledger' in markdown
    assert 'Example Release' in markdown
    assert 'robots_txt_disallowed' in markdown
    return True


def run_all_tests():
    """Run all tests and report results."""
    tests = [
        test_deep_research_config_clamps,
        test_user_url_cap_applies_before_search_citations,
        test_deterministic_query_plan_is_bounded,
        test_deep_research_ledger_and_markdown,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
            print(f"PASS: {test.__name__}")
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
