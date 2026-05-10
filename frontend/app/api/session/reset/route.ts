export async function POST() {
  const response = Response.json({ ok: true });
  response.headers.append(
    "Set-Cookie",
    "cg_session_id=; Path=/; Max-Age=0; SameSite=Lax",
  );
  return response;
}
