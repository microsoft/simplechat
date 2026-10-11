// dropdownPlacement.ts

export interface PickerViewport {
    left: number;
    top: number;
    width: number;
    height: number;
}

/** Fixed coordinates use the visual viewport's offset in the layout viewport. */
export function dropdownPlacement(
    trigger: { left: number; right: number; top: number; bottom: number },
    viewport: PickerViewport,
    align: 'left' | 'right',
) {
    const margin = Math.min(12, viewport.width / 2, viewport.height / 2);
    const gap = 8;
    const width = Math.max(0, Math.min(288, viewport.width - margin * 2));
    const left = Math.max(viewport.left + margin, Math.min(
        align === 'right' ? trigger.right - width : trigger.left,
        viewport.left + viewport.width - margin - width,
    ));
    const floor = viewport.top + viewport.height - margin;
    const ceiling = viewport.top + margin;
    const below = Math.max(0, floor - trigger.bottom - gap);
    const above = Math.max(0, trigger.top - gap - ceiling);
    const up = below < 320 && above > below;
    const maxHeight = Math.min(320, up ? above : below, Math.max(0, floor - ceiling));
    const anchor = up
        ? Math.max(ceiling, Math.min(floor, trigger.top - gap))
        : Math.max(ceiling, Math.min(floor, trigger.bottom + gap));
    return { left, width, maxHeight, top: anchor, up };
}
