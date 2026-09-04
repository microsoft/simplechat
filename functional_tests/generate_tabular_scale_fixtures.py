# generate_tabular_scale_fixtures.py
"""
Functional fixture generator for tabular row orchestration scale tiers.
Version: 0.250.132
Implemented in: 0.250.132

This utility streams synthetic CSV rows for the 30, 300, 3,000, 30,000,
and 100,000-row validation tiers without holding full fixture contents in memory.
"""

import argparse
import csv
from pathlib import Path


SCALE_TIERS = (30, 300, 3000, 30000, 100000)
FIELD_NAMES = ('Case ID', 'Score', 'Risk', 'Question')


def iter_synthetic_rows(row_count):
    """Yield deterministic tabular scale rows one at a time."""
    for row_number in range(1, int(row_count) + 1):
        risk = 'high' if row_number % 17 == 0 else 'medium' if row_number % 5 == 0 else 'low'
        yield {
            'Case ID': f'SC-{row_number:06d}',
            'Score': row_number,
            'Risk': risk,
            'Question': f'What is the risk disposition for case {row_number}?',
        }


def write_synthetic_csv(output_path, row_count):
    """Write a deterministic CSV fixture by streaming rows to disk."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', newline='', encoding='utf-8') as output_file:
        writer = csv.DictWriter(output_file, fieldnames=FIELD_NAMES)
        writer.writeheader()
        for row in iter_synthetic_rows(row_count):
            writer.writerow(row)
    return output_path


def main():
    """Generate one CSV fixture per supported scale tier."""
    parser = argparse.ArgumentParser(description='Generate tabular scale fixtures.')
    parser.add_argument('output_dir', help='Directory that will receive generated CSV fixtures.')
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    for row_count in SCALE_TIERS:
        write_synthetic_csv(
            output_dir / f'simplechat_row_orchestration_dataset_{row_count}.csv',
            row_count,
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())