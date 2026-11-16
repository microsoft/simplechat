// ClassificationCategoriesEditor.tsx
// The categories users choose from when they classify a document.
//
// The classic pane edits these in a table with an Edit and a Save button per row, and
// keeps the list in a hidden JSON field. Here each row is edited in place and the list
// flows into the page's draft like any other setting, so the save bar saves it with the
// rest of the section.
//
// Order matters: it is the order users see wherever they pick a category, so rows move.
// The preview draws each category with the same badge documents and conversations use.

import { clsx } from 'clsx';
import { AlertCircle, ArrowDown, ArrowUp, Plus, Tags, Trash2 } from 'lucide-react';
import type { AdminField } from '../../lib/adminFields';
import {
    CLASSIFICATION_DEFAULT_COLOR,
    CLASSIFICATION_LABEL_MAX_LENGTH,
    describeCategoryProblems,
    readClassificationCategories,
    safeBadgeColor,
    type ClassificationCategory,
} from '../../lib/classificationCategories';
import { ClassificationBadge } from '../documents/documentPresentation';
import { GlassButton } from '../ui/primitives';

const inputClass = clsx(
    'min-h-9 rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5',
    'text-sm text-text-1 placeholder:text-text-3',
    'focus:border-accent focus:outline-none',
    'disabled:cursor-not-allowed disabled:opacity-60',
);

const iconButtonClass = clsx(
    'rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1',
    'disabled:cursor-not-allowed disabled:opacity-40',
);

export function ClassificationCategoriesEditor({
    field,
    value,
    error,
    disabled,
    onChange,
}: {
    field: AdminField;
    value: unknown;
    error?: string;
    disabled?: boolean;
    onChange: (next: ClassificationCategory[]) => void;
}) {
    const categories = readClassificationCategories(value);
    const problems = describeCategoryProblems(categories);
    const previewable = categories.filter(
        (category, index) => !problems[index] && category.label.trim(),
    );

    const replace = (index: number, patch: Partial<ClassificationCategory>) => {
        onChange(categories.map((category, i) => (i === index ? { ...category, ...patch } : category)));
    };

    const move = (index: number, delta: number) => {
        const target = index + delta;
        if (target < 0 || target >= categories.length) {
            return;
        }
        const next = [...categories];
        [next[index], next[target]] = [next[target], next[index]];
        onChange(next);
    };

    return (
        <div className="py-3" data-testid="classification-categories-editor">
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <span className="text-sm font-semibold text-text-1">{field.label}</span>
                <span className="text-xs text-text-3">
                    {categories.length} {categories.length === 1 ? 'category' : 'categories'}
                </span>
            </div>

            {field.help ? (
                <p className="mb-2 max-w-[72ch] text-[0.8125rem] leading-relaxed text-text-3">{field.help}</p>
            ) : null}

            {categories.length === 0 ? (
                <div className="flex items-center gap-2 rounded-lg border border-dashed border-edge px-3 py-4 text-sm text-text-3">
                    <Tags size={15} aria-hidden="true" className="shrink-0" />
                    No categories yet. Users cannot classify a document until there is at least one.
                </div>
            ) : (
                <ul className="space-y-2">
                    {categories.map((category, index) => {
                        const problem = problems[index];
                        const swatch = safeBadgeColor(category.color) ?? CLASSIFICATION_DEFAULT_COLOR;
                        const position = index + 1;
                        return (
                            <li key={index} className="rounded-lg border border-edge bg-surface-1 p-2">
                                {/* The label leads, so DOM order matches what is seen: one line on a
                                    wide card; on a narrow one, or at a large text size, the label
                                    takes its own line and the rest wrap beneath it. */}
                                <div className="flex flex-wrap items-center gap-2">
                                    <input
                                        type="text"
                                        aria-label={`Category ${position} label`}
                                        placeholder="Label, such as Confidential"
                                        className={clsx(inputClass, 'min-w-0 basis-full @min-[36rem]:basis-0 @min-[36rem]:flex-1')}
                                        value={category.label}
                                        maxLength={CLASSIFICATION_LABEL_MAX_LENGTH}
                                        disabled={disabled}
                                        onChange={(event) => replace(index, { label: event.target.value })}
                                    />
                                    <input
                                        type="color"
                                        aria-label={`Category ${position} colour`}
                                        className="h-9 w-11 shrink-0 cursor-pointer rounded-lg border border-edge bg-surface-1 p-1 disabled:cursor-not-allowed"
                                        value={swatch.toLowerCase()}
                                        disabled={disabled}
                                        onChange={(event) => replace(index, { color: event.target.value })}
                                    />
                                    <input
                                        type="text"
                                        aria-label={`Category ${position} colour hex value`}
                                        className={clsx(inputClass, 'w-24 min-w-0 font-mono text-xs')}
                                        value={category.color}
                                        maxLength={7}
                                        spellCheck={false}
                                        disabled={disabled}
                                        onChange={(event) => replace(index, { color: event.target.value })}
                                    />
                                    <div className="ml-auto flex items-center">
                                        <button
                                            type="button"
                                            title="Move up"
                                            aria-label={`Move category ${position} up`}
                                            disabled={disabled || index === 0}
                                            onClick={() => move(index, -1)}
                                            className={iconButtonClass}
                                        >
                                            <ArrowUp size={14} aria-hidden="true" />
                                        </button>
                                        <button
                                            type="button"
                                            title="Move down"
                                            aria-label={`Move category ${position} down`}
                                            disabled={disabled || index === categories.length - 1}
                                            onClick={() => move(index, 1)}
                                            className={iconButtonClass}
                                        >
                                            <ArrowDown size={14} aria-hidden="true" />
                                        </button>
                                        <button
                                            type="button"
                                            title="Remove"
                                            aria-label={`Remove category ${position}`}
                                            disabled={disabled}
                                            onClick={() => onChange(categories.filter((_, i) => i !== index))}
                                            className={clsx(iconButtonClass, 'hover:bg-danger-soft hover:text-danger')}
                                        >
                                            <Trash2 size={14} aria-hidden="true" />
                                        </button>
                                    </div>
                                </div>

                                {problem ? (
                                    <p className="mt-1.5 flex items-center gap-1.5 text-xs text-warn">
                                        <AlertCircle size={12} className="shrink-0" aria-hidden="true" />
                                        {problem}
                                    </p>
                                ) : null}
                            </li>
                        );
                    })}
                </ul>
            )}

            <GlassButton
                type="button"
                variant="subtle"
                size="sm"
                className="mt-2"
                disabled={disabled}
                onClick={() => onChange([...categories, { label: '', color: CLASSIFICATION_DEFAULT_COLOR }])}
            >
                <Plus size={14} aria-hidden="true" />
                Add category
            </GlassButton>

            {previewable.length ? (
                <div className="mt-3">
                    <p className="text-xs font-medium text-text-3">As users will see them</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5" data-testid="classification-categories-preview">
                        {previewable.map((category, index) => (
                            <ClassificationBadge
                                key={`${category.label}-${index}`}
                                classification={category.label.trim()}
                                color={safeBadgeColor(category.color)}
                            />
                        ))}
                    </div>
                </div>
            ) : null}

            {error ? (
                <p role="alert" className="mt-1.5 flex items-start gap-1.5 text-xs text-danger">
                    <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}
