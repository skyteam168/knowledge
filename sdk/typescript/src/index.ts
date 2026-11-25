/** Minimal Open API client for Ontology Action (Wave C). */

export type ActionInvokeResult = {
  status: string;
  action_type: string;
  execution_id?: string | null;
  result?: Record<string, unknown>;
  error?: string | null;
  approval_id?: string | null;
  rule_verdict?: string | null;
};

export class OntologyClient {
  constructor(
    private readonly baseUrl: string,
    private readonly apiKey: string,
  ) {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${this.baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers: {
        "X-API-Key": this.apiKey,
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    if (!res.ok) {
      throw new Error(`Open API ${path} failed: ${res.status}`);
    }
    return (await res.json()) as T;
  }

  listActions() {
    return this.request<{ items: Array<Record<string, unknown>> }>("/open/actions");
  }

  approveAction(
    actionType: string,
    input: Record<string, unknown>,
    acknowledgeRisk = true,
  ) {
    return this.request<{ approval_id: string; expires_at: string; action_type: string }>(
      "/open/actions/approve",
      {
        method: "POST",
        body: JSON.stringify({
          action_type: actionType,
          input,
          acknowledge_risk: acknowledgeRisk,
        }),
      },
    );
  }

  invokeAction(
    actionType: string,
    input: Record<string, unknown>,
    opts: { idempotencyKey: string; approvalId?: string; dryRun?: boolean },
  ) {
    return this.request<ActionInvokeResult>("/open/actions/invoke", {
      method: "POST",
      body: JSON.stringify({
        action_type: actionType,
        input,
        idempotency_key: opts.idempotencyKey,
        approval_id: opts.approvalId,
        dry_run: opts.dryRun ?? false,
      }),
    });
  }
}
