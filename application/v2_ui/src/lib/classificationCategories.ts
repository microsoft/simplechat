// classificationCategories.ts
// Reading and checking the document classification categories edited in Admin Settings.
//
// The server is authoritative (admin_settings_fields._normalize_document_classification_categories)
// and refuses a bad list on save. These checks run while typing so each problem is shown
// on the row that has it, before Save is ever pressed.

export interface ClassificationCategory {
    label: string;
    color: string;
}

/** Mirrors DOCUMENT_CLASSIFICATION_LABEL_MAX_LENGTH in admin_settings_fields.py. */
export const CLASSIFICATION_LABEL_MAX_LENGTH = 80;

/** The colour a new category starts with, matching the classic editor. */
export const CLASSIFICATION_DEFAULT_COLOR = '#808080';

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export function isHexColor(value: string): boolean {
    return HEX_COLOR.test(value.trim());
}

/**
 * A colour safe to paint with, or undefined.
 *
 * The stored list is administrator data from the database and may predate validation, so
 * only a six-digit hex ever reaches a style; anything else falls back to the neutral badge.
 */
export function safeBadgeColor(value: string): string | undefined {
    return isHexColor(value) ? value.trim() : undefined;
}

/** Read the stored value defensively. */
export function readClassificationCategories(value: unknown): ClassificationCategory[] {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .map((item) => ({
            label: typeof item.label === 'string' ? item.label : '',
            color: typeof item.color === 'string' ? item.color : '',
        }));
}

/**
 * The problem with each row, or null when it would save.
 *
 * A repeated label is reported on the later row, naming the earlier one, because documents
 * store the label itself: two categories with one label could never be told apart.
 */
export function describeCategoryProblems(categories: ClassificationCategory[]): (string | null)[] {
    const firstUse = new Map<string, number>();
    return categories.map((category, index) => {
        const label = category.label.trim();
        if (!label) {
            return 'Give this category a label.';
        }
        if (label.length > CLASSIFICATION_LABEL_MAX_LENGTH) {
            return `Keep the label to ${CLASSIFICATION_LABEL_MAX_LENGTH} characters.`;
        }
        const folded = label.toLocaleLowerCase();
        const earlier = firstUse.get(folded);
        if (earlier !== undefined) {
            return `Same label as category ${earlier + 1}. Each label must be unique.`;
        }
        firstUse.set(folded, index);
        if (!isHexColor(category.color)) {
            return 'Use a six-digit hex colour, such as #808080.';
        }
        return null;
    });
}
