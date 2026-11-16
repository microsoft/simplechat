// csvPreview.ts
// Reading the CSV the server returns for a spreadsheet uploaded into a conversation.
//
// `/api/get_file_content` hands back the extracted content as CSV text with `is_table` set,
// not as structured rows, so something has to parse it before it can be drawn as a table.
// Rendering it as raw text instead would be technically honest and practically useless: a
// spreadsheet's whole value is its shape.
//
// Quoting follows RFC 4180 as far as the server produces it — quoted fields may contain
// commas, and a doubled quote inside a quoted field is a literal quote.

export interface CsvPreview {
    columns: string[];
    rows: string[][];
    /** Rows beyond the display limit, so the reader knows the table is partial. */
    hiddenRowCount: number;
}

export function parseCsvLine(line: string): string[] {
    const fields: string[] = [];
    let current = '';
    let inQuotes = false;

    for (let index = 0; index < line.length; index += 1) {
        const char = line[index];

        if (char === '"') {
            if (inQuotes && line[index + 1] === '"') {
                current += '"';
                index += 1;
            } else {
                inQuotes = !inQuotes;
            }
        } else if (char === ',' && !inQuotes) {
            fields.push(current.trim());
            current = '';
        } else {
            current += char;
        }
    }

    fields.push(current.trim());
    return fields;
}

/**
 * Parse CSV text into a bounded table, or return null when there is nothing tabular in it.
 *
 * Rows are capped because an uploaded spreadsheet can be very large and this is a preview
 * shown in a dialog; the original file is a download away for anyone who needs all of it.
 * Short rows are padded rather than dropped, since a trailing empty cell is far more likely
 * than a genuinely malformed file.
 */
export function parseCsvPreview(content: string, maxRows = 200): CsvPreview | null {
    const lines = String(content ?? '')
        .trim()
        .split(/\r?\n/)
        .filter((line) => line.trim());

    if (lines.length === 0) {
        return null;
    }

    const columns = parseCsvLine(lines[0]);
    const dataLines = lines.slice(1);
    const rows = dataLines.slice(0, maxRows).map((line) => {
        const cells = parseCsvLine(line);
        while (cells.length < columns.length) {
            cells.push('');
        }
        return cells.slice(0, columns.length);
    });

    return {
        columns,
        rows,
        hiddenRowCount: Math.max(0, dataLines.length - rows.length),
    };
}
