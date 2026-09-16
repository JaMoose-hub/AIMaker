import {
  applyHomography,
  type HomographyMatrix,
  type Letterbox,
} from "./geometry";

export type PointTuple = readonly [number, number];
export type Quad = readonly [PointTuple, PointTuple, PointTuple, PointTuple];

export interface OpticalHudCalibration {
  /** Camera-source pixels in canonical board order: TL, TR, BR, BL. */
  sourceCorners: Quad;
  /** Through-the-lens HUD positions normalized to the active display. */
  targetCornersNormalized: Quad;
}

type MutableMatrix3 = [
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
  number,
];

function multiplyMatrix3(left: HomographyMatrix, right: HomographyMatrix): MutableMatrix3 {
  const result = Array<number>(9).fill(0) as MutableMatrix3;
  for (let row = 0; row < 3; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      result[row * 3 + column] =
        left[row * 3] * right[column]
        + left[row * 3 + 1] * right[column + 3]
        + left[row * 3 + 2] * right[column + 6];
    }
  }
  return result;
}

function solveLinearSystem(rows: number[][], values: number[]): number[] | null {
  const size = values.length;
  const augmented = rows.map((row, index) => [...row, values[index]]);

  for (let column = 0; column < size; column += 1) {
    let pivotRow = column;
    for (let row = column + 1; row < size; row += 1) {
      if (Math.abs(augmented[row][column]) > Math.abs(augmented[pivotRow][column])) {
        pivotRow = row;
      }
    }
    const pivot = augmented[pivotRow][column];
    if (!Number.isFinite(pivot) || Math.abs(pivot) < 1e-10) return null;
    [augmented[column], augmented[pivotRow]] = [augmented[pivotRow], augmented[column]];

    for (let index = column; index <= size; index += 1) {
      augmented[column][index] /= pivot;
    }
    for (let row = 0; row < size; row += 1) {
      if (row === column) continue;
      const factor = augmented[row][column];
      if (Math.abs(factor) < 1e-14) continue;
      for (let index = column; index <= size; index += 1) {
        augmented[row][index] -= factor * augmented[column][index];
      }
    }
  }

  const solution = augmented.map((row) => row[size]);
  return solution.every(Number.isFinite) ? solution : null;
}

function normalizeQuad(points: Quad): {
  points: Quad;
  transform: HomographyMatrix;
  inverse: HomographyMatrix;
} | null {
  const centerX = points.reduce((sum, point) => sum + point[0], 0) / 4;
  const centerY = points.reduce((sum, point) => sum + point[1], 0) / 4;
  const meanDistance = points.reduce(
    (sum, point) => sum + Math.hypot(point[0] - centerX, point[1] - centerY),
    0,
  ) / 4;
  if (!Number.isFinite(meanDistance) || meanDistance < 1e-8) return null;

  const scale = Math.SQRT2 / meanDistance;
  const transform: HomographyMatrix = [
    scale, 0, -scale * centerX,
    0, scale, -scale * centerY,
    0, 0, 1,
  ];
  const inverse: HomographyMatrix = [
    1 / scale, 0, centerX,
    0, 1 / scale, centerY,
    0, 0, 1,
  ];
  const normalized = points.map((point) => [
    scale * (point[0] - centerX),
    scale * (point[1] - centerY),
  ] as PointTuple) as unknown as Quad;
  return { points: normalized, transform, inverse };
}

function quadArea(points: Quad): number {
  let doubledArea = 0;
  for (let index = 0; index < 4; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % 4];
    doubledArea += current[0] * next[1] - next[0] * current[1];
  }
  return Math.abs(doubledArea) / 2;
}

/** Solve the unique projective mapping between two non-degenerate quads. */
export function solveHomography(source: Quad, target: Quad): HomographyMatrix | null {
  if (quadArea(source) < 1e-4 || quadArea(target) < 1e-4) return null;
  const normalizedSource = normalizeQuad(source);
  const normalizedTarget = normalizeQuad(target);
  if (!normalizedSource || !normalizedTarget) return null;

  const rows: number[][] = [];
  const values: number[] = [];
  for (let index = 0; index < 4; index += 1) {
    const [x, y] = normalizedSource.points[index];
    const [u, v] = normalizedTarget.points[index];
    rows.push([x, y, 1, 0, 0, 0, -u * x, -u * y]);
    values.push(u);
    rows.push([0, 0, 0, x, y, 1, -v * x, -v * y]);
    values.push(v);
  }
  const solution = solveLinearSystem(rows, values);
  if (!solution) return null;

  const normalizedMatrix: HomographyMatrix = [
    solution[0], solution[1], solution[2],
    solution[3], solution[4], solution[5],
    solution[6], solution[7], 1,
  ];
  const denormalized = multiplyMatrix3(
    normalizedTarget.inverse,
    multiplyMatrix3(normalizedMatrix, normalizedSource.transform),
  );
  const magnitude = Math.max(...denormalized.map((value) => Math.abs(value)));
  if (!Number.isFinite(magnitude) || magnitude < 1e-12) return null;
  const matrix = denormalized.map((value) => value / magnitude) as MutableMatrix3;

  for (let index = 0; index < 4; index += 1) {
    const projected = applyHomography(matrix, source[index][0], source[index][1]);
    if (!projected || Math.hypot(projected.x - target[index][0], projected.y - target[index][1]) > 0.05) {
      return null;
    }
  }
  return matrix;
}

export function createOpticalHudTransform(
  base: Letterbox,
  calibration: OpticalHudCalibration | null,
  width: number,
  height: number,
): Letterbox | null {
  if (!calibration || width <= 0 || height <= 0) return null;
  const target = calibration.targetCornersNormalized.map(([x, y]) => [
    x * width,
    y * height,
  ] as PointTuple) as unknown as Quad;
  // Reject accidental double-clicks and nearly collinear through-the-lens points.
  if (quadArea(target) < 400) return null;
  const sourceToDisplay = solveHomography(calibration.sourceCorners, target);
  const displayToSource = solveHomography(target, calibration.sourceCorners);
  if (!sourceToDisplay || !displayToSource) return null;
  return {
    ...base,
    mirrorX: false,
    mirrorY: false,
    sourceToDisplay,
    displayToSource,
  };
}
