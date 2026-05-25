export async function fetchState(threadId, pricingTier) {
  const params = new URLSearchParams();
  if (threadId) params.set("thread_id", threadId);
  if (pricingTier) params.set("pricing_tier", pricingTier);

  const response = await fetch(`/api/state?${params.toString()}`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Erreur API");
  return payload;
}

export async function fetchTaskRun(threadId, runId, pricingTier) {
  const params = new URLSearchParams();
  if (threadId) params.set("thread_id", threadId);
  if (pricingTier) params.set("pricing_tier", pricingTier);
  params.set("run_id", runId);

  const response = await fetch(`/api/task-run?${params.toString()}`, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Erreur API task run");
  return payload;
}
