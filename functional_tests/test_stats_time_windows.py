# test_stats_time_windows.py
#!/usr/bin/env python3
"""
Functional test for stats time-window helpers.
Version: 0.241.111
Implemented in: 0.241.111

This test ensures personal, group, and public stats pages can share the same
7/30/90/custom date-window behavior without importing the full Flask app.
"""

import os
import sys


APP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
sys.path.append(APP_DIR)

from functions_stats_windows import (  # noqa: E402
    build_stats_date_series,
    resolve_stats_time_window,
    stats_window_response_payload,
    timestamp_to_stats_date_key,
)


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f'{message}: expected {expected!r}, got {actual!r}')


def test_predefined_windows():
    """Validate allowed predefined stats windows."""
    for days in (7, 30, 90):
        stats_window = resolve_stats_time_window({'days': str(days)})
        series = build_stats_date_series(stats_window['start_date'], stats_window['end_date'])

        assert_equal(stats_window['days'], days, f'{days}-day window days')
        assert_equal(stats_window['type'], 'days', f'{days}-day window type')
        assert_equal(stats_window['label'], f'Last {days} Days', f'{days}-day window label')
        assert_equal(len(series), days, f'{days}-day series length')

    invalid_window = resolve_stats_time_window({'days': '14'})
    assert_equal(invalid_window['days'], 30, 'invalid day values fall back to the default')


def test_custom_window():
    """Validate inclusive custom date windows and JSON payload shape."""
    stats_window = resolve_stats_time_window({
        'start_date': '2026-05-01',
        'end_date': '2026-05-07',
    })
    series = build_stats_date_series(stats_window['start_date'], stats_window['end_date'])
    payload = stats_window_response_payload(stats_window)

    assert_equal(stats_window['type'], 'custom', 'custom window type')
    assert_equal(stats_window['days'], 7, 'custom window inclusive day count')
    assert_equal(series[0]['date'], '2026-05-01', 'custom first date')
    assert_equal(series[-1]['date'], '2026-05-07', 'custom last date')
    assert_equal(payload['label'], '5/1/2026 - 5/7/2026', 'custom payload label')

    try:
        resolve_stats_time_window({'start_date': '2026-05-08', 'end_date': '2026-05-07'})
    except ValueError:
        pass
    else:
        raise AssertionError('reversed custom ranges must raise ValueError')


def test_timestamp_bucket_normalization():
    """Validate timestamp bucket keys for common stored activity formats."""
    assert_equal(
        timestamp_to_stats_date_key('2026-05-07T14:30:00Z'),
        '2026-05-07',
        'Z timestamp bucket',
    )
    assert_equal(
        timestamp_to_stats_date_key('2026-05-07T14:30:00'),
        '2026-05-07',
        'naive timestamp bucket',
    )
    assert_equal(timestamp_to_stats_date_key('not-a-date'), None, 'invalid timestamp bucket')


def run_tests():
    tests = [
        test_predefined_windows,
        test_custom_window,
        test_timestamp_bucket_normalization,
    ]
    results = []

    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print(f'Passed {test.__name__}')
            results.append(True)
        except Exception as ex:
            print(f'Failed {test.__name__}: {ex}')
            results.append(False)

    print(f'Results: {sum(results)}/{len(results)} tests passed')
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)