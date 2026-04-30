# test_profile_fact_memory_script_dedup.py
"""
Functional test for the profile fact-memory script deduplication fix.
Version: 0.241.004
Implemented in: 0.241.003; 0.241.004

This test ensures the profile page only includes one Chart.js script tag and one
copy of the fact-memory inline helpers so browser parsing does not fail.
"""

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
PROFILE_TEMPLATE = ROOT_DIR / 'application' / 'single_app' / 'templates' / 'profile.html'


def read_profile_template():
    return PROFILE_TEMPLATE.read_text(encoding='utf-8')


def assert_occurs_once(source_text, marker):
    occurrence_count = source_text.count(marker)
    assert occurrence_count == 1, (
        f'Expected marker to appear once, found {occurrence_count}: {marker}'
    )


def test_profile_fact_memory_script_blocks_are_not_duplicated():
    """Verify the profile template keeps fact-memory script markers unique."""
    print('🔍 Testing profile fact-memory script deduplication...')

    profile_template = read_profile_template()

    unique_markers = [
        "<script src=\"{{ url_for('static', filename='js/chart.min.js') }}\"></script>",
        '<div class="section-card" id="tutorial-preferences">',
        '<div class="section-card" id="fact-memory-settings">',
        '<div class="modal fade" id="factMemoryDeleteModal" tabindex="-1" aria-labelledby="factMemoryDeleteModalLabel" aria-hidden="true">',
        '<div class="modal fade" id="factMemoryManagerModal" tabindex="-1" aria-labelledby="factMemoryManagerModalLabel" aria-hidden="true">',
        'let factMemoryEntries = [];',
        'let filteredFactMemoryEntries = [];',
        'let factMemoryCurrentPage = 1;',
        'const FACT_MEMORY_PAGE_SIZE = 5;',
        "const factMemorySearchInput = document.getElementById('fact-memory-search-input');",
        "function updateFactMemoryStatus(message, type = 'muted') {",
        'function getFilteredFactMemoryEntries() {',
        'async function loadFactMemory() {',
        'async function createFactMemory() {',
        'async function saveFactMemory(factId) {',
        'async function confirmDeleteFactMemory() {',
        'async function loadRetentionSettings() {',
        'function saveRetentionSettings() {',
        'function showSuccessToast(message) {',
        'function loadTutorialPreferences() {',
        'function saveTutorialPreferences() {',
    ]

    for marker in unique_markers:
        assert_occurs_once(profile_template, marker)

    print('✅ Profile fact-memory script markers are unique')


if __name__ == '__main__':
    test_profile_fact_memory_script_blocks_are_not_duplicated()
    print('📊 Results: 1/1 tests passed')