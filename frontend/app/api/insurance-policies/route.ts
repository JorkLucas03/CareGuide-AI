const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");

type InsurancePolicy = {
  id?: number;
  provider_name?: string;
  tier?: string;
  deductible?: number;
  max_out_of_pocket?: number;
};

export async function GET() {
  try {
    const response = await fetch(`${backendUrl}/api/insurance-policies`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return Response.json({ policies: [] }, { status: 502 });
    }

    const data = (await response.json()) as { policies?: InsurancePolicy[] };
    const policies = Array.isArray(data.policies) ? data.policies : [];
    return Response.json({ policies });
  } catch {
    return Response.json({ policies: [] }, { status: 502 });
  }
}
