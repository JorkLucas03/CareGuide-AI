import { randomUUID } from "crypto";

const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const buildId = () => randomUUID();

export async function POST(request: Request) {
  const startedAt = Date.now();
  let body: { message?: string; sessionId?: string; insuranceTier?: string };

  try {
    body = (await request.json()) as { message?: string; sessionId?: string; insuranceTier?: string };
  } catch {
    return Response.json({ error: "invalid JSON body" }, { status: 400 });
  }

  const message = (body.message ?? "").trim();

  if (!message) {
    return Response.json({ error: "message is required" }, { status: 400 });
  }

  let reply = "No pude procesar tu mensaje. Intenta otra vez.";
  let data: Record<string, unknown> = {};

  try {
    const response = await fetch(`${backendUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, sessionId: body.sessionId, insuranceTier: body.insuranceTier }),
    });

    if (!response.ok) {
      return Response.json({ error: "Backend unavailable" }, { status: 502 });
    }

    data = (await response.json()) as Record<string, unknown>;
    if (typeof data.reply === "string") {
      reply = data.reply;
    }
  } catch {
    return Response.json({ error: "Backend unavailable" }, { status: 502 });
  }

  const latencyMs = Date.now() - startedAt;

  return Response.json({
    id: (data.id as string | undefined) ?? buildId(),
    sessionId: (data.sessionId as string | undefined) ?? body.sessionId,
    reply,
    urgencyLevel: (data.urgencyLevel as number | undefined) ?? 2,
    specialty: (data.specialty as string | undefined) ?? "Medicina general",
    latencyMs: (data.latencyMs as number | undefined) ?? latencyMs,
    cost: (data.cost as { base: number; coverage: number; copay: number } | undefined) ?? {
      base: 0,
      coverage: 0,
      copay: 0,
    },
    showCost: (data.showCost as boolean | undefined) ?? true,
    hospitals: (data.hospitals as unknown[]) ?? [],
  });
}
