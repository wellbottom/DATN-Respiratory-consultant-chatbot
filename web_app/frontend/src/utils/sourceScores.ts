export function formatSourceScore(score: number): string {
  if (!Number.isFinite(score)) return "0";
  if (score === 0) return "0";
  if (Math.abs(score) < 0.01) return score.toPrecision(2);
  return score.toFixed(2);
}

export function sourceScoreBarWidth(score: number): string {
  if (!Number.isFinite(score) || score <= 0) return "0%";
  return `${Math.min(Math.max(score * 100, 3), 100)}%`;
}

// ponytail: tiny dev check, no test runner just for two display edge cases.
if ((import.meta as any).env?.DEV) {
  console.assert(formatSourceScore(0.004022) === "0.0040", "source score keeps small non-zero values visible");
  console.assert(formatSourceScore(0.0168) === "0.02", "source score rounds normal values");
}
