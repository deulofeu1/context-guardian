export type GuardianMessage = {
  role: string;
  content: string;
  id: string;
  is_error?: boolean;
  tool_name?: string;
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
