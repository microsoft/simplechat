# functions_workflow_merge_schema.py
"""Bootstrap-free, closed Merge options shared by workflow authoring surfaces."""


def workflow_merge_options_schema():
    name = {'type': 'string', 'minLength': 1, 'maxLength': 256}
    names = {'type': 'array', 'items': name, 'minItems': 1, 'uniqueItems': True}
    return {
        'type': 'object', 'additionalProperties': False,
        'description': (
            'Tabular accepts column, sheet, duplicate and sort settings. Workbook takes only sheets and sheet; '
            'pdf only bookmarks; docx only formatting, page_breaks and source_headings; pptx only formatting and sections.'
        ),
        'properties': {
            'bookmarks': {'type': 'boolean'}, 'formatting': {'enum': ['keep_source', 'use_first']},
            'page_breaks': {'type': 'boolean'}, 'source_headings': {'type': 'boolean'}, 'sections': {'type': 'boolean'},
            'schema_policy': {'enum': ['by_name', 'exact_order', 'union', 'mapped']},
            'columns': {**names, 'maxItems': 255},
            'column_aliases': {
                'type': 'array', 'minItems': 1, 'maxItems': 256,
                'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['column', 'aliases'],
                    'properties': {'column': name, 'aliases': {**names, 'maxItems': 32}},
                },
            },
            'sheet': {'type': 'string', 'minLength': 1, 'maxLength': 31},
            'sheets': {'enum': ['first', 'all']}, 'header_row': {'type': 'integer', 'minimum': 1, 'maximum': 1000},
            'include_source_column': {'type': 'boolean'},
            'source_column_name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'on_incompatible': {'enum': ['fail', 'exclude']},
            'dedupe': {'enum': ['none', 'exact_rows', 'key_columns']},
            'dedupe_columns': {**names, 'maxItems': 16}, 'dedupe_keep': {'enum': ['first', 'last']},
            'sort_by': {
                'type': 'array', 'maxItems': 3,
                'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['column'],
                    'properties': {'column': name, 'descending': {'type': 'boolean'},
                                   'value_type': {'enum': ['text', 'number', 'date']}},
                },
            },
        },
    }
