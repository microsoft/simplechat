# orchestration_scorecard.py
"""
Report how chat orchestration behaved in a deployed application, from its telemetry.

Version: 0.261.454
Implemented in: 0.261.451

The scorecard reads the content-free orchestration events the application already sends to
Application Insights and reports, for each application version seen in the period:

- requests accepted for planning, requests that could not be planned, correction rounds;
- runs, completed runs, and the completion rate;
- the validation rules that rejected plans and the failure codes that ended runs.

It is the acceptance measure for harness changes: run the same scenarios through the UI
before and after a change, then compare the two versions' rows. It reads telemetry only;
it starts no requests and changes nothing.

Usage (requires a signed-in Azure CLI with the application-insights extension):

    python scripts\\orchestration_scorecard.py --app APP_INSIGHTS_NAME --resource-group RG
    python scripts\\orchestration_scorecard.py --app NAME --resource-group RG --days 3 --json

Planning events carry no application version, so each is attributed to the version whose
first recorded run outcome most recently preceded it. Events before the first run outcome
in the period are reported as "unknown".
"""

import argparse
import bisect
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict

REQUEST = '[ORCHESTRATION] Initial planning question saved.'
CORRECTION = '[ORCHESTRATION_PLANNER] Asking the planner to correct a rejected plan.'
NOT_PLANNED = '[ORCHESTRATION_PLANNER] The request could not be planned.'
PLANNING_CRASH = '[ORCHESTRATION] Planning failed.'
OUTCOME = '[CHAT_EXECUTION] Execution outcome recorded.'
PROGRESS = '[ORCHESTRATION_PROGRESS] Progress recorded.'
MESSAGES = (REQUEST, CORRECTION, NOT_PLANNED, PLANNING_CRASH, OUTCOME, PROGRESS)
# A recovery is logged when applied and again when its step finishes; count the second.
PROGRESS_APPLIED = 'applied'
UNKNOWN_VERSION = 'unknown'


def build_query(days):
    names = ', '.join(f"'{message}'" for message in MESSAGES)
    return (
        f"traces | where timestamp > ago({int(days)}d) "
        "| extend m = tostring(customDimensions.sc_message) "
        f"| where m in ({names}) "
        "| project timestamp, m, "
        "version = tostring(customDimensions.sc_application_version), "
        "outcome = tostring(customDimensions.sc_outcome), "
        "failure_code = tostring(customDimensions.sc_failure_code), "
        "capability = tostring(customDimensions.sc_capability_id), "
        "rule = tostring(customDimensions.sc_validation_rule), "
        "error_type = tostring(customDimensions.sc_error_type), "
        "error_site = tostring(customDimensions.sc_error_site), "
        "recovery = tostring(customDimensions.sc_recovery), "
        "progress_outcome = tostring(customDimensions.sc_progress_outcome) "
        "| order by timestamp asc"
    )


def fetch_rows(app, resource_group, days, subscription=None):
    """Return the event rows as dictionaries, oldest first."""
    executable = shutil.which('az')
    if not executable:
        raise RuntimeError('The Azure CLI (az) was not found on PATH.')
    command = [
        executable, 'monitor', 'app-insights', 'query', '--app', app,
        '--resource-group', resource_group, '--analytics-query', build_query(days),
        '--offset', f'{int(days)}d', '--output', 'json',
    ]
    if subscription:
        command += ['--subscription', subscription]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f'The telemetry query failed: {completed.stderr.strip()[:500]}')
    table = json.loads(completed.stdout)['tables'][0]
    columns = [column['name'] for column in table['columns']]
    return [dict(zip(columns, row)) for row in table['rows']]


def version_starts(rows):
    """Each version's first recorded run outcome, as parallel sorted lists."""
    first_seen = {}
    for row in rows:
        if row['m'] == OUTCOME and row['version'] and row['version'] not in first_seen:
            first_seen[row['version']] = row['timestamp']
    ordered = sorted(first_seen.items(), key=lambda item: item[1])
    return [timestamp for _, timestamp in ordered], [version for version, _ in ordered]


def summarize(rows):
    """Aggregate event rows into one record per application version."""
    starts, versions = version_starts(rows)

    def version_at(timestamp):
        index = bisect.bisect_right(starts, timestamp) - 1
        return versions[index] if index >= 0 else UNKNOWN_VERSION

    summary = defaultdict(lambda: {
        'first_seen': None, 'requests': 0, 'not_planned': 0, 'planning_crashes': 0,
        'corrections': 0, 'runs': 0, 'completed': 0, 'waiting': 0,
        'rejection_rules': Counter(), 'run_failures': Counter(), 'crash_sites': Counter(),
        'recoveries': Counter(),
    })
    for row in rows:
        version = row['version'] if row['m'] == OUTCOME and row['version'] else version_at(row['timestamp'])
        record = summary[version]
        record['first_seen'] = record['first_seen'] or row['timestamp']
        message = row['m']
        if message == REQUEST:
            record['requests'] += 1
        elif message == CORRECTION:
            record['corrections'] += 1
            record['rejection_rules'][row['rule'] or 'unspecified'] += 1
        elif message == NOT_PLANNED:
            record['not_planned'] += 1
        elif message == PLANNING_CRASH:
            record['planning_crashes'] += 1
            record['crash_sites'][
                f"{row['error_type'] or 'unrecorded'} at {row['error_site'] or 'unrecorded'}"
            ] += 1
        elif message == PROGRESS:
            outcome = row.get('progress_outcome') or 'unspecified'
            if outcome != PROGRESS_APPLIED:
                record['recoveries'][
                    f"{row.get('failure_code') or 'unspecified'} -> "
                    f"{row.get('recovery') or 'none'}: {outcome}"
                ] += 1
        elif message == OUTCOME:
            if row['outcome'] == 'waiting':
                record['waiting'] += 1
                continue
            record['runs'] += 1
            if row['outcome'] == 'completed':
                record['completed'] += 1
            else:
                record['run_failures'][
                    f"{row['capability'] or 'run'}: {row['failure_code'] or row['outcome'] or 'unspecified'}"
                ] += 1
    return dict(sorted(summary.items(), key=lambda item: item[1]['first_seen'] or ''))


def _rate(part, whole):
    return f'{100 * part / whole:.0f}%' if whole else '-'


def render(summary):
    """Render the per-version table and the leading causes as plain text."""
    lines = [
        'version      requests  not planned  crashes  corrections  runs  completed  completion',
    ]
    for version, record in summary.items():
        lines.append(
            f"{version:<12} {record['requests']:>8} {record['not_planned']:>12} "
            f"{record['planning_crashes']:>8} {record['corrections']:>12} {record['runs']:>5} "
            f"{record['completed']:>10} {_rate(record['completed'], record['runs']):>11}"
        )
    for title, field in (
        ('Plan rejection rules', 'rejection_rules'), ('Run failures', 'run_failures'),
        ('Planning crashes', 'crash_sites'), ('Step recoveries', 'recoveries'),
    ):
        total = Counter()
        for record in summary.values():
            total.update(record[field])
        if total:
            lines += ['', f'{title} (all versions):']
            lines += [f'  {count:>4}  {name}' for name, count in total.most_common(15)]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Chat orchestration scorecard from Application Insights.')
    parser.add_argument('--app', required=True, help='Application Insights resource name.')
    parser.add_argument('--resource-group', required=True)
    parser.add_argument('--subscription')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--json', action='store_true', help='Print the summary as JSON.')
    arguments = parser.parse_args(argv)
    try:
        rows = fetch_rows(arguments.app, arguments.resource_group, arguments.days, arguments.subscription)
    except (RuntimeError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 1
    summary = summarize(rows)
    if arguments.json:
        print(json.dumps({
            version: {key: dict(value) if isinstance(value, Counter) else value for key, value in record.items()}
            for version, record in summary.items()
        }, indent=2))
    else:
        print(render(summary))
    return 0


if __name__ == '__main__':
    sys.exit(main())
