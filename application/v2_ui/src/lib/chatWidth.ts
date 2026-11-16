// chatWidth.ts
// The reading width of the message thread and composer.
//
// The thread and the composer must agree: widening one without the other leaves the
// composer controls just as crowded, which is the problem this exists to solve.

import type { ChatWidth } from '../stores/uiStore';

/**
 * Container width class for a given preference.
 *
 * "comfortable" holds a fixed reading measure, which is easier to read but leaves the
 * composer cramped on a wide screen. "wide" lets both fill the pane.
 */
export function chatWidthClass(width: ChatWidth): string {
    return width === 'wide' ? 'max-w-none' : 'max-w-4xl';
}

/**
 * Bubble width class.
 *
 * Bubbles stay narrower than the container so a long line never runs the full width of a
 * large monitor, which is unreadable regardless of the preference.
 */
export function bubbleWidthClass(width: ChatWidth): string {
    return width === 'wide' ? 'max-w-[min(64rem,90%)]' : 'max-w-[min(46rem,85%)]';
}
