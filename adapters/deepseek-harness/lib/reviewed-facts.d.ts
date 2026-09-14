import type { ReviewedFactsAppendix } from "./types.js";
export declare const REVIEWED_FACTS_START = "<!-- context-guardian:reviewed-facts:v1 -->";
export declare const REVIEWED_FACTS_END = "<!-- /context-guardian:reviewed-facts -->";
/** Append facts while preserving native result fields and all text outside legal blocks. */
export declare function appendReviewedFacts(preview: string, appendix: ReviewedFactsAppendix): string;
//# sourceMappingURL=reviewed-facts.d.ts.map