export type MessageSourceKind =
  | "unknown"
  | "user_authored"
  | "assistant_response"
  | "attachment_content"
  | "tool_result"
  | "durable_tool_result"
  | "execution_noise"
  | "internal_metadata";

export interface MessageProvenance {
  source_kind: MessageSourceKind;
  user_authored?: boolean;
  assistant_response?: boolean;
  attachment_content?: boolean;
  tool_call?: boolean;
  tool_result?: boolean;
  system?: boolean;
  developer?: boolean;
  plugin_internal?: boolean;
  planning?: boolean;
  compaction_metadata?: boolean;
  bookkeeping?: boolean;
}

export interface GuardianMessage {
  role: string;
  content: string;
  id: string;
  tool_name?: string;
  is_error?: boolean;
  metadata?: Record<string, unknown>;
  provenance?: MessageProvenance;
}

export interface MemoryCandidate {
  id: string;
  content: string;
  category: string;
  importance: number;
  confidence: number;
  suggested_action: "keep" | "drop" | "review";
  reason?: string | null;
  source_message_ids: string[];
}

export interface InspectionResult {
  candidates: MemoryCandidate[];
  auto_keep: MemoryCandidate[];
  auto_drop: MemoryCandidate[];
  review: MemoryCandidate[];
  mode: "rules" | "provider";
  policy_version: string;
  degraded?: boolean;
  diagnostics?: string[];
}

export interface AuditFinding {
  id: string;
  issue_type: "missing" | "incorrect" | "stale" | "ambiguous";
  category: string;
  summary: string;
  display_summary?: string | null;
  why_it_matters: string;
  suggested_correction: string;
  importance: number;
  confidence: number;
  source_message_ids: string[];
  evidence_snippets: string[];
  task_relation?: "primary" | "related" | "background";
  operation?: "add" | "replace" | "keep_preview";
  requires_user_confirmation?: boolean;
  current_summary_text?: string | null;
  current_summary_target?: string | null;
  proposed_text?: string | null;
  effect_if_rejected?: string | null;
}

export interface AuditTopic {
  id: string;
  title: string;
  summary: string;
  finding_ids: string[];
  impact: number;
  confidence: number;
  relevance_to_main_goal: number;
  requires_user_preference: boolean;
  disposition: "auto_correct" | "accept_preview" | "ask_user";
  recommended_action: "keep" | "drop" | "correct" | "accept_preview" | "add" | "keep_preview";
  suggested_correction?: string | null;
  evidence_snippets?: string[];
  task_relation?: "primary" | "related" | "background";
  operation?: "add" | "replace" | "keep_preview";
  current_summary_text?: string | null;
  current_summary_target?: string | null;
  proposed_text?: string | null;
  effect_if_rejected?: string | null;
}

export interface ReviewOption {
  id: "keep" | "drop" | "correct" | "keep_preview" | "add";
  label: string;
  description: string;
}

export interface ReviewQuestion {
  id: string;
  topic_id: string;
  title: string;
  question: string;
  context: string;
  why_it_matters: string;
  recommendation: "keep" | "drop" | "correct" | "keep_preview" | "add";
  options: ReviewOption[];
  evidence_snippets?: string[];
  task_relation?: "primary" | "related" | "background";
  operation?: "add" | "replace" | "keep_preview";
  current_summary_text?: string | null;
  current_summary_target?: string | null;
  proposed_text?: string | null;
  effect_if_rejected?: string | null;
}

export interface AuditCoverage {
  total_source_messages: number;
  attempted_source_messages: number;
  covered_source_messages: number;
  failed_chunks: number;
  chunks: number;
  complete: boolean;
}

export interface ReviewPlan {
  language: "zh-CN" | "en";
  overview: string;
  auto_preserve_summary: string;
  findings: AuditFinding[];
  audit_topics: AuditTopic[];
  auto_corrections: string[];
  accepted_omissions: string[];
  review_questions: ReviewQuestion[];
  diagnostics?: string[];
  audit_status?: "success" | "no_issues" | "budget_exhausted" | "source_rejected" | "model_failed" | "rules_fallback" | "incomplete";
  degraded?: boolean;
  degradation_reason?: string | null;
  coverage?: AuditCoverage;
  preview_fingerprint?: string | null;
}

export interface ReviewedFact {
  id: string;
  text: string;
  origin: "auto_correction" | "human_keep" | "carried_forward";
  topic_id?: string | null;
  category?: string | null;
}

export interface ReviewedFactsAppendix {
  version: "1";
  language: "zh-CN" | "en";
  facts: ReviewedFact[];
  text: string;
}

export interface PreviewEdit {
  id: string;
  operation: "replace";
  target: string;
  replacement: string;
  topic_id?: string | null;
  finding_id?: string | null;
  status: "applied" | "skipped";
  reason: string;
}

export interface PreviewFinalization {
  original_preview: string;
  final_summary: string;
  appendix: ReviewedFactsAppendix;
  changed: boolean;
  edits: PreviewEdit[];
  diagnostics: string[];
}

export interface Guidance {
  must_preserve: string[];
  can_discard: string[];
  unresolved: string[];
  text: string;
}

export interface ProtocolFrame {
  protocol_version?: number;
  type?: string;
  request_id?: string;
  ok?: boolean;
  error?: string;
  result?: unknown;
  prompt?: string;
  schema?: Record<string, unknown>;
}
