/** An explicit zero is an answer; an untouched zero is still a question. */
export interface OwnershipRow {
  cardId: string;
  have: number;
  needed: number;
  known: boolean;
}

export type RowState = "awaiting" | "gap" | "ready";

export function rowState(row: OwnershipRow, value: number, touched = false): RowState {
  const answered = row.known || touched || value !== row.have;
  if (!answered && value < row.needed) return "awaiting";
  return value < row.needed ? "gap" : "ready";
}

export function ownershipProgress(rows: OwnershipRow[], answers: Map<string, number>, touched: Set<string>) {
  let confirmed = 0;
  let missingCopies = 0;
  let assumed = 0;
  for (const row of rows) {
    const value = answers.get(row.cardId) ?? row.have;
    const answered = row.known || touched.has(row.cardId) || value !== row.have;
    if (answered) {
      confirmed += 1;
      missingCopies += Math.max(0, row.needed - value);
    } else if (value >= row.needed) assumed += 1;
  }
  return { confirmed, missingCopies, assumed, total: rows.length, unanswered: rows.length - confirmed - assumed };
}
