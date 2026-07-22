# functions_tabular_csv_query.py
"""Shared bounded CSV query evaluation for foreground tools and durable exports."""

import ast

import pandas


TABULAR_ROW_LOCAL_QUERY_AST_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.BitAnd,
    ast.BitOr,
    ast.BitXor,
    ast.USub,
    ast.UAdd,
    ast.Invert,
)


def _replace_backtick_column_references(expression):
    """Replace pandas backtick column labels with parseable placeholder names."""
    output = []
    placeholder_index = 0
    character_index = 0
    active_quote = None
    escaped = False
    while character_index < len(expression):
        character = expression[character_index]
        if escaped:
            output.append(character)
            escaped = False
            character_index += 1
            continue
        if character == '\\' and active_quote:
            output.append(character)
            escaped = True
            character_index += 1
            continue
        if active_quote:
            output.append(character)
            if character == active_quote:
                active_quote = None
            character_index += 1
            continue
        if character in {'\'', '"'}:
            active_quote = character
            output.append(character)
            character_index += 1
            continue
        if character != '`':
            output.append(character)
            character_index += 1
            continue

        closing_index = expression.find('`', character_index + 1)
        if closing_index < 0 or not expression[character_index + 1:closing_index].strip():
            raise ValueError('Source query contains an invalid backtick column reference')
        output.append(f'__simplechat_column_{placeholder_index}')
        placeholder_index += 1
        character_index = closing_index + 1

    return ''.join(output)


def validate_tabular_csv_query_expression(query_expression):
    """Return a row-local expression or reject operations that change across chunks."""
    normalized_expression = str(query_expression or '').strip()
    if not normalized_expression:
        raise ValueError('Source query expression is required')
    if '@' in normalized_expression:
        raise ValueError(
            'Source query variables cannot be replayed in bounded chunks'
        )

    parseable_expression = _replace_backtick_column_references(normalized_expression)
    try:
        parsed_expression = ast.parse(parseable_expression, mode='eval')
    except SyntaxError as exc:
        raise ValueError('Source query is not a valid row-local expression') from exc

    unsupported_nodes = [
        node.__class__.__name__
        for node in ast.walk(parsed_expression)
        if not isinstance(node, TABULAR_ROW_LOCAL_QUERY_AST_NODES)
    ]
    if unsupported_nodes:
        raise ValueError(
            'Source query uses an operation that cannot be replayed equivalently in bounded chunks: '
            f'{unsupported_nodes[0]}'
        )
    for node in ast.walk(parsed_expression):
        if isinstance(node, ast.Name) and node.id.startswith('__') and not node.id.startswith('__simplechat_column_'):
            raise ValueError('Source query contains an unsupported private identifier')
    return normalized_expression


def detect_tabular_csv_numeric_columns(csv_stream, source_chunk_rows, tabular_plugin):
    """Find columns that pandas can convert to numeric across every bounded chunk."""
    numeric_columns = None
    csv_stream.seek(0)
    for source_chunk in pandas.read_csv(
        csv_stream,
        keep_default_na=False,
        dtype=str,
        chunksize=max(1, int(source_chunk_rows or 1)),
    ):
        source_chunk = tabular_plugin._normalize_dataframe_columns(source_chunk)
        if numeric_columns is None:
            numeric_columns = set(source_chunk.columns)
        for column_name in list(numeric_columns):
            try:
                pandas.to_numeric(source_chunk[column_name])
            except (TypeError, ValueError):
                numeric_columns.discard(column_name)
    csv_stream.seek(0)
    return numeric_columns or set()


def iter_tabular_csv_query_rows(
    csv_stream,
    query_expression,
    return_columns,
    source_chunk_rows,
    tabular_plugin,
    start_source_row=0,
    replay_stats=None,
):
    """Yield physical source row numbers and query-matched records in bounded chunks."""
    source_chunk_rows = max(1, int(source_chunk_rows or 1))
    start_source_row = max(0, int(start_source_row or 0))
    normalized_query_expression = validate_tabular_csv_query_expression(query_expression)
    numeric_columns = detect_tabular_csv_numeric_columns(
        csv_stream,
        source_chunk_rows,
        tabular_plugin,
    )
    parsed_return_columns = tabular_plugin._parse_optional_column_list_argument(return_columns)

    csv_stream.seek(0)
    read_options = {
        'keep_default_na': False,
        'dtype': str,
        'chunksize': source_chunk_rows,
    }
    if start_source_row:
        read_options['skiprows'] = lambda row_index: 0 < row_index <= start_source_row

    source_row_offset = start_source_row
    for source_chunk in pandas.read_csv(csv_stream, **read_options):
        source_chunk = tabular_plugin._normalize_dataframe_columns(source_chunk)
        source_chunk.index = range(source_row_offset, source_row_offset + len(source_chunk))
        source_row_offset += len(source_chunk)
        for column_name in numeric_columns:
            if column_name in source_chunk.columns:
                source_chunk[column_name] = pandas.to_numeric(source_chunk[column_name])

        filtered_chunk, used_reviewer_style_fallback = tabular_plugin._apply_query_expression_with_fallback(
            source_chunk,
            query_expression=normalized_query_expression,
            normalize_match=False,
        )
        if isinstance(replay_stats, dict) and used_reviewer_style_fallback:
            replay_stats['used_reviewer_style_fallback'] = True
        selected_columns = [
            column_name
            for column_name in (parsed_return_columns or list(filtered_chunk.columns))
            if column_name in filtered_chunk.columns
        ]
        output_records = tabular_plugin._build_row_output_records(
            filtered_chunk,
            selected_columns,
        )
        for source_row_index, output_record in zip(filtered_chunk.index, output_records):
            yield int(source_row_index) + 1, output_record
