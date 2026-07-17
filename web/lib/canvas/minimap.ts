/**
 * G7 — corner mini-map geometry.
 *
 * Projects the field's graph-space extent into a small fixed box (aspect
 * preserved, centred) and marks the camera viewport as a rect inside it, so a
 * dense field is orientable. Pure geometry, unit-tested; the canvas paints the
 * projected points/blobs and the viewport rect.
 */

export interface XY {
  x: number;
  y: number;
}

export interface MinimapBox {
  width: number;
  height: number;
}

export interface MinimapLayout {
  /** graph-px → box-px scale (wider axis fits the box). */
  scale: number;
  /** Project a graph-space point into box coordinates. */
  project: (x: number, y: number) => XY;
  box: MinimapBox;
}

/**
 * Fit the points' extent into the box, aspect preserved, centred. The limiting
 * axis fills its box dimension; the other is letterboxed. An empty field
 * collapses to the box centre (no divide-by-zero).
 */
export function minimapLayout(points: XY[], box: MinimapBox): MinimapLayout {
  if (points.length === 0) {
    return {
      scale: 1,
      project: () => ({ x: box.width / 2, y: box.height / 2 }),
      box,
    };
  }
  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.y > maxY) maxY = p.y;
  }
  const extentX = maxX - minX;
  const extentY = maxY - minY;
  const scale =
    extentX === 0 && extentY === 0
      ? 1
      : Math.min(
          extentX === 0 ? Number.POSITIVE_INFINITY : box.width / extentX,
          extentY === 0 ? Number.POSITIVE_INFINITY : box.height / extentY,
        );
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const project = (x: number, y: number): XY => ({
    x: box.width / 2 + (x - cx) * scale,
    y: box.height / 2 + (y - cy) * scale,
  });
  return { scale, project, box };
}

export interface GraphExtent {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export interface MinimapRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The camera viewport as a rect inside the mini-map box, clamped to it. */
export function viewportRect(
  layout: MinimapLayout,
  view: GraphExtent,
): MinimapRect {
  const tl = layout.project(view.minX, view.minY);
  const br = layout.project(view.maxX, view.maxY);
  const rawX = Math.min(tl.x, br.x);
  const rawY = Math.min(tl.y, br.y);
  const rawW = Math.abs(br.x - tl.x);
  const rawH = Math.abs(br.y - tl.y);
  const x = Math.max(0, rawX);
  const y = Math.max(0, rawY);
  const width = Math.min(layout.box.width - x, rawW - (x - rawX));
  const height = Math.min(layout.box.height - y, rawH - (y - rawY));
  return {
    x,
    y,
    width: Math.max(0, width),
    height: Math.max(0, height),
  };
}
