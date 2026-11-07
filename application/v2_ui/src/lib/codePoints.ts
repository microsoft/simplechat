// codePoints.ts
// Measure and cut text in Unicode code points, the way the server counts it.
//
// JavaScript strings count UTF-16 code units, so an emoji outside the Basic Multilingual Plane
// counts twice. Python counts code points, and a surrogate pair cut in half is a lone surrogate
// the server refuses outright. Both helpers keep a pair together.

function isHighSurrogate(unit: number): boolean {
    return unit >= 0xd800 && unit <= 0xdbff;
}

function isLowSurrogate(unit: number): boolean {
    return unit >= 0xdc00 && unit <= 0xdfff;
}

/** How many UTF-16 units the code point starting at `index` takes: 2 for a surrogate pair. */
function codePointWidth(text: string, index: number): number {
    return isHighSurrogate(text.charCodeAt(index)) && index + 1 < text.length
        && isLowSurrogate(text.charCodeAt(index + 1)) ? 2 : 1;
}

/** The number of code points in `text`. A lone surrogate counts as one, as it does in Python. */
export function codePointLength(text: string): number {
    let count = 0;
    for (let index = 0; index < text.length; index += codePointWidth(text, index)) {
        count += 1;
    }
    return count;
}

/** The first `limit` code points of `text`, never splitting a surrogate pair. */
export function codePointPrefix(text: string, limit: number): string {
    if (limit <= 0) {
        return '';
    }
    let count = 0;
    let index = 0;
    while (index < text.length && count < limit) {
        index += codePointWidth(text, index);
        count += 1;
    }
    return index >= text.length ? text : text.slice(0, index);
}
