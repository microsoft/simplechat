# test_source_review_deep_traversal.py
"""
Functional test for Deep Source Review archive traversal and link planning.
Version: 0.241.063
Implemented in: 0.241.062

This test ensures Deep Source Review prioritizes source-archive child links over
generic navigation pages without relying on company-specific heuristics, can use
structured archive/list rows as candidates, and that model-assisted planning can
only rank already-extracted candidate URLs.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_source_review import (  # noqa: E402
    extract_source_review_evidence_from_html,
    get_source_review_config,
    _plan_child_candidates_with_llm,
    _pop_next_child_candidate,
    _reorder_child_candidates_from_planner,
    _select_child_links,
    _should_follow_links,
)


class FakePlannerMessage:
    def __init__(self, content):
        self.content = content


class FakePlannerChoice:
    def __init__(self, content):
        self.message = FakePlannerMessage(content)


class FakePlannerResponse:
    def __init__(self, content):
        self.choices = [FakePlannerChoice(content)]


class FakePlannerCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakePlannerResponse(self.content)


class FakePlannerChat:
    def __init__(self, content):
        self.completions = FakePlannerCompletions(content)


class FakePlannerClient:
    def __init__(self, content):
        self.chat = FakePlannerChat(content)


def test_deep_source_review_prioritizes_archive_child_links():
    """Validate archive-style requests favor release/detail links over generic site navigation."""
    print("Testing Deep Source Review archive child-link prioritization...")

    page_result = {
        "url": "https://www.example.com/newsroom/press-releases",
        "links": [
            {
                "url": "https://www.example.com/about/awards-and-recognition",
                "anchor_text": "Awards and recognition",
                "nearby_text": "Learn more about our awards and recognition.",
                "published_date": "2026-05-18",
                "same_domain": True,
            },
            {
                "url": "https://www.example.com/newsroom/press-releases/2026-05-19-new-product",
                "anchor_text": "May 19, 2026 New product press release",
                "nearby_text": "Press release announcing a new product for analysts.",
                "published_date": "2026-05-19",
                "same_domain": True,
            },
            {
                "url": "https://www.example.com/newsroom/stories/customer-story",
                "anchor_text": "Customer story",
                "nearby_text": "A story about a customer implementation.",
                "published_date": "2026-05-17",
                "same_domain": True,
            },
        ],
    }

    child_candidates = _select_child_links(
        page_result=page_result,
        user_message="Find the press releases from the past three years.",
        current_depth=0,
        existing_urls=set(),
        limit=10,
    )
    selected_child = _pop_next_child_candidate(
        child_candidates,
        "Find the press releases from the past three years.",
    )

    assert selected_child is not None
    assert selected_child["url"] == "https://www.example.com/newsroom/press-releases/2026-05-19-new-product"
    assert selected_child["score"] > 0


def test_deep_source_review_selects_across_multiple_seed_archives():
    """Validate child candidates from later seed pages can win remaining review budget."""
    print("Testing Deep Source Review cross-seed child selection...")

    first_seed = {
        "url": "https://www.first.example/newsroom/press-releases",
        "links": [
            {
                "url": "https://www.first.example/about/diversity",
                "anchor_text": "Diversity and inclusion",
                "nearby_text": "Corporate information page.",
                "published_date": "2026-05-19",
                "same_domain": True,
            }
        ],
    }
    second_seed = {
        "url": "https://www.second.example/global/news",
        "links": [
            {
                "url": "https://www.second.example/global/news/press-release/2026/product-launch",
                "anchor_text": "2026 product launch press release",
                "nearby_text": "Official press release for the product launch.",
                "published_date": "2026-05-18",
                "same_domain": True,
            }
        ],
    }

    child_candidates = []
    for seed_page in (first_seed, second_seed):
        child_candidates.extend(_select_child_links(
            page_result=seed_page,
            user_message="Find the press releases from the past three years.",
            current_depth=0,
            existing_urls=set(),
            limit=10,
        ))

    selected_child = _pop_next_child_candidate(
        child_candidates,
        "Find the press releases from the past three years.",
    )

    assert selected_child is not None
    assert selected_child["url"] == "https://www.second.example/global/news/press-release/2026/product-launch"


def test_llm_planner_can_reorder_only_existing_candidates():
    """Validate model planning is constrained to already-extracted candidate URLs."""
    print("Testing Source Review LLM planner candidate constraints...")

    child_candidates = [
        {
            "url": "https://www.example.com/newsroom/press-releases/first",
            "parent_url": "https://www.example.com/newsroom/press-releases",
            "anchor_text": "First release",
            "nearby_text": "A lower-priority release.",
            "published_date": "2026-05-18",
            "score": 20,
            "date_sort_value": "2026-05-18T00:00:00",
            "reason": "child_link:first",
        },
        {
            "url": "https://www.example.com/newsroom/press-releases/second",
            "parent_url": "https://www.example.com/newsroom/press-releases",
            "anchor_text": "Second release",
            "nearby_text": "A release that best matches the request.",
            "published_date": "2026-05-17",
            "score": 10,
            "date_sort_value": "2026-05-17T00:00:00",
            "reason": "child_link:second",
        },
    ]
    fake_client = FakePlannerClient(
        '{"selected_urls":[{"url":"https://www.example.com/newsroom/press-releases/second","reason":"best match"},'
        '{"url":"https://attacker.example/not-a-candidate","reason":"not allowed"}],"reason":"ranked by relevance"}'
    )

    planner_result = _plan_child_candidates_with_llm(
        planner_client=fake_client,
        planner_model="test-model",
        user_message="Find the relevant press releases.",
        reviewed_pages=[{"url": "https://www.example.com/newsroom/press-releases", "title": "Press releases"}],
        child_candidates=child_candidates,
        max_select=1,
        source_settings={"source_review_enable_llm_planning": True, "enable_deep_source_review": True},
    )
    reordered_candidates = _reorder_child_candidates_from_planner(
        child_candidates,
        planner_result,
        "Find the relevant press releases.",
    )
    selected_child = _pop_next_child_candidate(reordered_candidates, "Find the relevant press releases.")

    assert planner_result["attempted"] is True
    assert planner_result["used"] is True
    assert planner_result["accepted_urls"] == ["https://www.example.com/newsroom/press-releases/second"]
    assert selected_child["url"] == "https://www.example.com/newsroom/press-releases/second"


def test_deep_source_review_prioritizes_relevant_links_before_truncation():
    """Validate relevant archive links survive noisy navigation before link limits apply."""
    print("Testing Source Review link prioritization before truncation...")

    nav_links = "".join(
        f'<a href="/about/nav-{index}">About navigation {index}</a>'
        for index in range(35)
    )
    html_content = f"""
    <html>
        <head><title>Press release archive</title></head>
        <body>
            <nav>{nav_links}</nav>
            <main>
                <a href="/newsroom/press-releases/2026-05-19-important-release">
                    May 19, 2026 Important press release
                </a>
            </main>
        </body>
    </html>
    """

    page_result = extract_source_review_evidence_from_html(
        html_content=html_content,
        url="https://www.example.com/newsroom/press-releases",
        user_message="Find the press releases from the past three years.",
    )
    retained_urls = [link["url"] for link in page_result["links"]]
    child_candidates = _select_child_links(
        page_result=page_result,
        user_message="Find the press releases from the past three years.",
        current_depth=0,
        existing_urls=set(),
        limit=10,
    )

    expected_url = "https://www.example.com/newsroom/press-releases/2026-05-19-important-release"
    assert expected_url in retained_urls
    assert child_candidates[0]["url"] == expected_url


def test_deep_source_review_rejects_generic_archive_navigation_links():
    """Validate generic same-domain navigation is not enough for archive traversal."""
    print("Testing Source Review generic navigation suppression...")

    page_result = {
        "url": "https://www.example.com/newsroom/press-releases",
        "links": [
            {
                "url": "https://www.example.com/about",
                "anchor_text": "About",
                "nearby_text": "Learn about the company.",
                "same_domain": True,
            },
            {
                "url": "https://www.example.com/careers",
                "anchor_text": "Careers",
                "nearby_text": "Open roles.",
                "same_domain": True,
            },
        ],
    }

    child_candidates = _select_child_links(
        page_result=page_result,
        user_message="Find the press releases from the past three years.",
        current_depth=0,
        existing_urls=set(),
        limit=10,
    )

    assert child_candidates == []


def test_deep_source_review_uses_structured_archive_items_as_candidates():
    """Validate structured dated rows feed traversal even when raw link text is generic."""
    print("Testing Source Review structured archive traversal candidates...")

    page_result = {
        "url": "https://www.example.com/news",
        "links": [],
        "structured_items": [
            {
                "url": "https://www.example.com/news/2026/product-launch",
                "title": "Example Announces Product Launch",
                "nearby_text": "Example Announces Product Launch May 18, 2026 Learn more",
                "published_date": "2026-05-18",
                "same_domain": True,
            },
        ],
    }

    child_candidates = _select_child_links(
        page_result=page_result,
        user_message="Find the press releases from the past three years.",
        current_depth=0,
        existing_urls=set(),
        limit=10,
    )

    assert len(child_candidates) == 1
    assert child_candidates[0]["url"] == "https://www.example.com/news/2026/product-launch"
    assert child_candidates[0]["anchor_text"] == "Example Announces Product Launch"


def test_deep_source_review_allows_bounded_second_hop_with_seed_budget():
    """Validate Source Review can reserve budget for child pages and follow one extra hop."""
    print("Testing Source Review bounded second-hop traversal config...")

    source_settings = get_source_review_config({
        "enable_deep_source_review": True,
        "source_review_max_pages_per_turn": 5,
        "source_review_max_seed_pages_per_turn": 3,
        "source_review_max_depth": 2,
    })
    over_limit_settings = get_source_review_config({
        "source_review_max_pages_per_turn": 5,
        "source_review_max_seed_pages_per_turn": 99,
        "source_review_max_depth": 99,
    })
    page_result = {
        "links": [{"url": "https://www.example.com/news/press-release/2026/detail"}],
    }

    assert source_settings["source_review_max_seed_pages_per_turn"] == 3
    assert source_settings["source_review_max_depth"] == 2
    assert over_limit_settings["source_review_max_seed_pages_per_turn"] == 5
    assert over_limit_settings["source_review_max_depth"] == 2
    assert _should_follow_links(page_result, source_settings, 0) is True
    assert _should_follow_links(page_result, source_settings, 1) is True
    assert _should_follow_links(page_result, source_settings, 2) is False


if __name__ == "__main__":
    tests = [
        test_deep_source_review_prioritizes_archive_child_links,
        test_deep_source_review_selects_across_multiple_seed_archives,
        test_llm_planner_can_reorder_only_existing_candidates,
        test_deep_source_review_prioritizes_relevant_links_before_truncation,
        test_deep_source_review_rejects_generic_archive_navigation_links,
        test_deep_source_review_uses_structured_archive_items_as_candidates,
        test_deep_source_review_allows_bounded_second_hop_with_seed_budget,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"Test passed: {test.__name__}")
            results.append(True)
        except Exception as test_error:
            print(f"Test failed: {test.__name__}: {test_error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)