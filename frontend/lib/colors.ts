/**
 * High-visibility palette: 16 maximally perceptually distinct colors.
 * Designed for white/light-grey backgrounds. Ordered by hue.
 */
export const VISIBILITY_PALETTE = [
  "#E63946", // Red
  "#E76F51", // Burnt orange
  "#F4A261", // Sandy gold
  "#8AB17D", // Leaf green
  "#2A9D8F", // Teal
  "#457B9D", // Steel blue
  "#5E60CE", // Indigo
  "#9B5DE5", // Violet
  "#F15BB5", // Hot pink
  "#264653", // Dark teal
  "#6A994E", // Olive green
  "#BC6C25", // Rust brown
  "#3A86A8", // Ocean blue
  "#7209B7", // Deep purple
  "#C1121F", // Crimson
  "#606C38", // Army green
];

/**
 * Strip trailing instance suffix (_2, _3, etc.) to get base part type.
 * "mr63zz_bearing_v1_2" → "mr63zz_bearing_v1"
 */
function basePartName(id: string): string {
  return id.replace(/_(\d+)$/, "");
}

/**
 * Build a map of partId → visibility color.
 * Same base name → same color. Different base names → different colors.
 */
export function buildVisibilityColorMap(
  partIds: string[],
): Record<string, string> {
  // Group by base name, preserving first-seen order
  const baseToIds = new Map<string, string[]>();
  for (const id of partIds) {
    const base = basePartName(id);
    if (!baseToIds.has(base)) baseToIds.set(base, []);
    baseToIds.get(base)!.push(id);
  }

  const colorMap: Record<string, string> = {};
  let colorIdx = 0;
  for (const [, ids] of baseToIds) {
    const color = VISIBILITY_PALETTE[colorIdx % VISIBILITY_PALETTE.length]!;
    for (const id of ids) {
      colorMap[id] = color;
    }
    colorIdx++;
  }
  return colorMap;
}
