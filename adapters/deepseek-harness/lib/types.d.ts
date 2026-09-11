export interface GuardianMessage {
    role: string;
    content: string;
    id: string;
    tool_name?: string;
    is_error?: boolean;
    metadata?: Record<string, unknown>;
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
//# sourceMappingURL=types.d.ts.map