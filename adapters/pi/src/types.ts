export type MessageSourceKind =
  | "unknown"
  | "user_authored"
  | "assistant_response"
  | "attachment_content"
  | "tool_result"
  | "durable_tool_result"
  | "execution_noise"
  | "internal_metadata";

export type MessageProvenance = {
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
};

export type GuardianMessage = {
  role: string;
  content: string;
  id: string;
  is_error?: boolean;
  tool_name?: string;
  metadata?: Record<string, unknown>;
  provenance?: MessageProvenance;
};
export type MemoryCandidate = {
  id: string;
  content: string;
  category: string;
  importance: number;
  confidence: number;
  suggested_action: "keep" | "drop" | "review";
  reason?: string | null;
  source_message_ids?: string[];
};

export type InspectionResult = {
  candidates: MemoryCandidate[];
  auto_keep: MemoryCandidate[];
  auto_drop: MemoryCandidate[];
  review: MemoryCandidate[];
  mode: "rules" | "provider";
  policy_version: string;
};

export type AuditFinding = {
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
};

export type AuditTopic = {
  id: string;
  title: string;
  summary: string;
  finding_ids: string[];
  impact: number;
  confidence: number;
  relevance_to_main_goal: number;
  requires_user_preference: boolean;
  disposition: "auto_correct" | "accept_preview" | "ask_user";
  recommended_action: "keep" | "drop" | "correct" | "accept_preview";
  suggested_correction?: string | null;
  evidence_snippets?: string[];
};

export type ReviewOption = {
  id: "keep" | "drop";
  label: string;
  description: string;
};

export type ReviewQuestion = {
  id: string;
  topic_id: string;
  title: string;
  question: string;
  context: string;
  why_it_matters: string;
  recommendation: "keep" | "drop";
  options: ReviewOption[];
  evidence_snippets?: string[];
};

export type ReviewPlan = {
  language: "zh-CN" | "en";
  overview: string;
  auto_preserve_summary: string;
  findings: AuditFinding[];
  audit_topics: AuditTopic[];
  auto_corrections: string[];
  accepted_omissions: string[];
  review_questions: ReviewQuestion[];
  diagnostics?: string[];
};

export type ReviewedFact = {
  id: string;
  text: string;
  origin: "auto_correction" | "human_keep" | "carried_forward";
  topic_id?: string | null;
  category?: string | null;
};

export type ReviewedFactsAppendix = {
  version: "1";
  language: "zh-CN" | "en";
  facts: ReviewedFact[];
  text: string;
};

export type Guidance = {
  must_preserve: string[];
  can_discard: string[];
  unresolved: string[];
  text: string;
};

export type ProtocolFrame = {
  protocol_version?: number;
  type?: string;
  request_id?: string;
  ok?: boolean;
  operation?: string;
  result?: unknown;
  data?: unknown;
  error?: string;
  prompt?: string;
  schema?: Record<string, unknown>;
};
