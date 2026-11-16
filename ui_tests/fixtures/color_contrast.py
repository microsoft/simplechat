# color_contrast.py
"""Browser contrast measurement against the actual composited ancestor surfaces.

Version: 0.261.305
Implemented in: 0.261.305
"""

CONTRAST_RATIO_SCRIPT = """
(element, property) => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    const rgba = (color) => {
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        const pixel = context.getImageData(0, 0, 1, 1).data;
        return [pixel[0], pixel[1], pixel[2], pixel[3] / 255];
    };
    const over = (top, bottom) => {
        const alpha = top[3] + bottom[3] * (1 - top[3]);
        return [0, 1, 2].map((index) =>
            (top[index] * top[3] + bottom[index] * bottom[3] * (1 - top[3])) / alpha
        ).concat(alpha);
    };
    let background = [0, 0, 0, 0];
    for (let parent = element; parent; parent = parent.parentElement) {
        const color = rgba(getComputedStyle(parent).backgroundColor);
        if (color[3]) {
            background = over(background, color);
        }
        if (background[3] === 1) break;
    }
    if (background[3] !== 1) throw new Error('Contrast requires an opaque ancestor');
    const foreground = over(rgba(getComputedStyle(element)[property]), background);
    const luminance = (color) => color.slice(0, 3).reduce((sum, value, index) => {
        const channel = value / 255;
        const linear = channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
        return sum + linear * [0.2126, 0.7152, 0.0722][index];
    }, 0);
    const light = Math.max(luminance(background), luminance(foreground));
    const dark = Math.min(luminance(background), luminance(foreground));
    return (light + 0.05) / (dark + 0.05);
}
"""
