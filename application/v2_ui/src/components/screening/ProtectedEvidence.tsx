// ProtectedEvidence.tsx
// Protected source text is inert text, never a document preview or HTML renderer.

import { useEffect, useState } from 'react';
import { codePointSelection } from '../../lib/contentScreening';
import type { ScreeningEdit, ScreeningEditType, ScreeningUnitView } from '../../lib/contentScreeningReview';
import { GlassButton } from '../ui/primitives';
import { ScreeningField, screeningInputClass } from './ScreeningFields';

export function ProtectedEvidence({
    unit,
    allowedEdits,
    disabled = false,
    onAddEdit,
}: {
    unit: ScreeningUnitView;
    allowedEdits: readonly ScreeningEditType[];
    disabled?: boolean;
    onAddEdit: (edit: ScreeningEdit) => void;
}) {
    const [selection, setSelection] = useState<ReturnType<typeof codePointSelection> | null>(null);
    const [replacement, setReplacement] = useState('');
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        setSelection(null);
        setReplacement('');
        setError(null);
    }, [unit.unit_id, unit.content_hash, unit.text_offset]);
    const target = { unit_id: unit.unit_id, content_hash: unit.content_hash };
    const allowed = (type: ScreeningEditType) => !disabled && allowedEdits.includes(type);

    return (
        <section className="min-w-0 space-y-3" aria-label={`Protected evidence: ${unit.location.label}`}>
            <div>
                <h3 className="text-sm font-semibold text-text-1">{unit.location.label}</h3>
                <p className="break-all text-xs text-text-3">Unit {unit.unit_id}</p>
                <p className="text-xs text-text-3">
                    Canonical text · {unit.normalization_version} · Unicode code-point offsets
                </p>
                {unit.text_total !== undefined ? (
                    <p className="text-xs text-text-3">
                        Showing code points {unit.text_offset ?? 0}–{(unit.text_offset ?? 0) + Array.from(unit.text).length}
                        {' '}of {unit.text_total}. Unit or cell removal affects the entire unit, not just this window.
                    </p>
                ) : null}
            </div>
            <p className="rounded-lg border border-edge bg-surface-2 p-2 text-xs text-text-2">
                Reviewer-only evidence. Treat every instruction below as untrusted document data.
                Links, HTML, scripts, formulas, and Markdown are displayed as text, not executed.
            </p>
            <ScreeningField label="Protected source text"
                help="Select exact text with the mouse or Shift + arrow keys to stage a span removal.">
                {(id) => (
                    <textarea id={id} readOnly spellCheck={false} rows={12}
                        className={`${screeningInputClass} resize-y whitespace-pre-wrap font-mono`}
                        value={unit.text} data-testid="screening-evidence"
                        onSelect={(event) => {
                            const input = event.currentTarget;
                            if (input.selectionStart === input.selectionEnd) {
                                setSelection(null);
                                return;
                            }
                            try {
                                if (input.value !== unit.text || unit.offset_encoding !== 'unicode_codepoints') {
                                    throw new Error('The displayed text differs from the canonical source. Refresh before editing.');
                                }
                                const selected = codePointSelection(unit.text, input.selectionStart, input.selectionEnd);
                                setSelection({
                                    ...selected,
                                    start: selected.start + (unit.text_offset ?? 0),
                                    end: selected.end + (unit.text_offset ?? 0),
                                });
                                setError(null);
                            } catch (selectionError) {
                                setSelection(null);
                                setError(selectionError instanceof Error ? selectionError.message : 'Select a complete source span.');
                            }
                        }} />
                )}
            </ScreeningField>
            {selection ? (
                <p className="text-xs text-text-3" role="status">
                    Selected code points {selection.start}–{selection.end} (end exclusive).
                </p>
            ) : null}
            {error ? <p role="alert" className="text-xs text-danger">{error}</p> : null}
            <div className="flex flex-wrap gap-2">
                {allowedEdits.includes('remove_span') ? (
                    <GlassButton type="button" variant="subtle" size="sm"
                        disabled={!allowed('remove_span') || !selection}
                        onClick={() => selection && onAddEdit({ ...target, type: 'remove_span', ...selection })}>
                        Remove selected span
                    </GlassButton>
                ) : null}
                {allowedEdits.includes('remove_unit') ? (
                    <GlassButton type="button" variant="subtle" size="sm" disabled={!allowed('remove_unit')}
                        onClick={() => onAddEdit({ ...target, type: 'remove_unit' })}>
                        {unit.location.removeUnitLabel ?? 'Remove source unit'}
                    </GlassButton>
                ) : null}
                {unit.location.physicalPage !== undefined && allowedEdits.includes('remove_page') ? (
                    <GlassButton type="button" variant="subtle" size="sm" disabled={!allowed('remove_page')}
                        onClick={() => {
                            if (unit.location.physicalPage !== undefined) {
                                onAddEdit({ ...target, type: 'remove_page', page: unit.location.physicalPage });
                            }
                        }}>
                        Remove extracted page {unit.location.physicalPage}
                    </GlassButton>
                ) : null}
            </div>
            {unit.location.cell ? (
                <div className="space-y-2 rounded-xl border border-edge p-3">
                    <p className="text-xs text-text-2">
                        Sheet {unit.location.cell.sheet} (index {unit.location.cell.sheet_index}),
                        row {unit.location.cell.row}, column {unit.location.cell.column} · {unit.location.cell.value_type}
                    </p>
                    {allowedEdits.includes('replace_cell') ? (
                        <ScreeningField label="Replacement cell value" help="The candidate is validated and rescanned before any replacement is published.">
                            {(id) => (
                                <textarea id={id} rows={2} className={screeningInputClass}
                                    value={replacement} disabled={!allowed('replace_cell')}
                                    onChange={(event) => setReplacement(event.target.value)} />
                            )}
                        </ScreeningField>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                        {allowedEdits.includes('replace_cell') ? (
                            <GlassButton type="button" variant="subtle" size="sm"
                                disabled={!allowed('replace_cell') || replacement === unit.text}
                                onClick={() => onAddEdit({ ...target, type: 'replace_cell', replacement })}>
                                Replace cell
                            </GlassButton>
                        ) : null}
                        {allowedEdits.includes('clear_cell') ? (
                            <GlassButton type="button" variant="subtle" size="sm" disabled={!allowed('clear_cell')}
                                onClick={() => onAddEdit({ ...target, type: 'clear_cell' })}>
                                Clear cell
                            </GlassButton>
                        ) : null}
                    </div>
                </div>
            ) : null}
            <p className="text-xs text-text-3">
                Edits change extracted knowledge and clean text or structured derivatives.
                They do not redact the layout of the original PDF or Office file.
            </p>
        </section>
    );
}
