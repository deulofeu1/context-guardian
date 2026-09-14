import { createHash } from "node:crypto";
import type { ReviewedFact, ReviewedFactsAppendix } from "./types.js";

export const REVIEWED_FACTS_START = "<!-- context-guardian:reviewed-facts:v1 -->";
export const REVIEWED_FACTS_END = "<!-- /context-guardian:reviewed-facts -->";
const BLOCK = new RegExp(
  `${escapeRegExp(REVIEWED_FACTS_START)}([\\s\\S]*?)${escapeRegExp(REVIEWED_FACTS_END)}`,
  "g",
);
const SUBJECTS = ["postgresql", "sqlite", "mysql", "redis", "mongodb", "oauth", "auth.py", "callback"];
const POSITIVE = /\b(?:selected|chosen|final|adopted?|use|using|complete|completed)\b/i;
const NEGATIVE = /\b(?:abandoned|rejected|stop using|not use|incomplete|unfinished|failed)\b/i;

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalize(value: string): string {
  return value
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(REVIEWED_FACTS_START, "[reviewed-facts marker removed]")
    .replace(REVIEWED_FACTS_END, "[reviewed-facts end marker removed]")
    .slice(0, 500);
}

function idFor(text: string): string {
  return `reviewed_fact_${createHash("sha256").update(text.toLocaleLowerCase()).digest("hex").slice(0, 16)}`;
}

function addFact(facts: ReviewedFact[], seen: Set<string>, text: string): void {
  const normalized = normalize(text);
  if (!normalized || seen.has(normalized.toLocaleLowerCase())) return;
  seen.add(normalized.toLocaleLowerCase());
  facts.push({ id: idFor(normalized), text: normalized, origin: "carried_forward" });
}

function conflicts(left: ReviewedFact, right: ReviewedFact): boolean {
  const leftSubject = SUBJECTS.find((subject) => left.text.toLocaleLowerCase().includes(subject));
  const rightSubject = SUBJECTS.find((subject) => right.text.toLocaleLowerCase().includes(subject));
  if (!leftSubject || leftSubject !== rightSubject) return false;
  const leftPositive = POSITIVE.test(left.text);
  const rightPositive = POSITIVE.test(right.text);
  const leftNegative = NEGATIVE.test(left.text);
  const rightNegative = NEGATIVE.test(right.text);
  return (leftPositive && rightNegative) || (leftNegative && rightPositive);
}

function priority(origin: ReviewedFact["origin"]): number {
  return origin === "human_keep" ? 3 : origin === "auto_correction" ? 2 : 1;
}

function mergeFacts(base: ReviewedFact[], incoming: ReviewedFact[]): ReviewedFact[] {
  const merged = [...base];
  for (const candidate of incoming) {
    if (merged.some((fact) => fact.text.toLocaleLowerCase() === candidate.text.toLocaleLowerCase())) continue;
    const conflictIndexes = merged
      .map((fact, index) => conflicts(fact, candidate) ? index : -1)
      .filter((index) => index >= 0);
    if (conflictIndexes.length === 0) {
      merged.push(candidate);
    } else if (conflictIndexes.every((index) => priority(candidate.origin) >= priority(merged[index].origin))) {
      for (const index of conflictIndexes.sort((left, right) => right - left)) merged.splice(index, 1);
      merged.push(candidate);
    }
  }
  return merged;
}

function render(language: "zh-CN" | "en", facts: ReviewedFact[]): string {
  if (facts.length === 0) return "";
  const title = language === "zh-CN" ? "## Context Guardian 已确认事实" : "## Context Guardian Reviewed Facts";
  const intro = language === "zh-CN"
    ? "以下是经过自动校正或人工确认、供后续任务优先参考的关键事实；不代表保留完整原始对话。"
    : "The following reviewed facts should take priority for future work; this does not preserve the full original conversation.";
  return [
    REVIEWED_FACTS_START,
    title,
    intro,
    ...facts.map((fact) => `- ${fact.text}`),
    REVIEWED_FACTS_END,
  ].join("\n");
}

/** Append facts while preserving native result fields and all text outside legal blocks. */
export function appendReviewedFacts(preview: string, appendix: ReviewedFactsAppendix): string {
  const matches = [...preview.matchAll(BLOCK)];
  if (matches.length === 0 && appendix.facts.length === 0) return preview;

  const carried: ReviewedFact[] = [];
  const seen = new Set<string>();
  for (const match of matches) {
    for (const line of (match[1] ?? "").split("\n")) {
      if (line.trim().startsWith("- ")) addFact(carried, seen, line.trim().slice(2));
    }
  }
  const merged = mergeFacts(carried, appendix.facts.map((fact) => ({ ...fact, text: normalize(fact.text) })));
  if (
    matches.length > 0
    && merged.length === carried.length
    && merged.every((fact, index) => fact.text === carried[index]?.text)
  ) return preview;
  const block = render(appendix.language, merged);
  if (matches.length > 0) {
    const first = matches[0];
    const last = matches[matches.length - 1];
    return preview.slice(0, first.index) + block + preview.slice((last.index ?? 0) + last[0].length);
  }
  return preview + (preview ? "\n\n" : "") + block;
}
