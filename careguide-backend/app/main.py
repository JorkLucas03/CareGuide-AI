from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
from dataclasses import dataclass
import time
import re
import os

from app.agents.medical_agent import careguide_ai
from app.db.database import (
    FALLBACK_HOSPITALS,
    db_client,
    save_recommendations,
    search_hospitals,
    get_chat_history,
    get_patient_messages,
    save_chat_message,
    get_policy_by_tier,
    get_insurance_policies,
    get_specialty_by_name,
    get_coverage_for_policy,
    get_contracts_for_policy,
)
from app.models.chat import ChatRequest, ChatResponse
from app.services.triage import (
    GENERAL_SPECIALTY,
    TIER_MAP,
    TriageResult,
    analyze_message,
    estimate_cost,
    estimate_cost_with_factor,
    URGENCY_MULTIPLIER,
)

app = FastAPI(title="CareGuide AI Backend")

DEBUG_TRIAGE = os.environ.get("DEBUG_TRIAGE", "false").lower() in {"1", "true", "yes"}
GROQ_API_KEY_PRESENT = bool(os.environ.get("GROQ_API_KEY"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
DEFAULT_ERROR_REPLY = "No pude procesar tu mensaje. Intenta otra vez."


@dataclass
class ChatContext:
    message: str
    session_id: str
    history_text: str
    full_symptoms: str
    urgency_level: int
    specialty: str
    insurance_tier: str | None
    insurance_available: bool
    cost_model: dict | None
    use_db_cost: bool
    cost: dict
    show_cost: bool
    analysis_for_cost: TriageResult


def _log(message: str) -> None:
    print(message.encode("ascii", errors="replace").decode("ascii"))


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def leer_raiz():
    return {"mensaje": "CareGuide AI backend activo."}


@app.get("/api/hospitales")
def obtener_hospitales():
    if db_client is None:
        return {"hospitales": FALLBACK_HOSPITALS}

    respuesta = db_client.table("hospitals").select("*").execute()
    return {"hospitales": respuesta.data}


@app.get("/api/insurance-policies")
def obtener_policies():
    policies = get_insurance_policies()
    return {"policies": policies}


def _sanitize_reply(reply: str | None) -> str:
    if not reply:
        return DEFAULT_ERROR_REPLY

    lowered = reply.lower()
    if "tool_use_failed" in lowered or "failed_generation" in lowered:
        return DEFAULT_ERROR_REPLY

    # Limpiar código técnico o llamadas a herramientas que la IA pueda "alucinar" en el texto final
    clean_reply = re.sub(r"<function=.*?</function>", "", reply, flags=re.DOTALL)
    clean_reply = re.sub(r"<function=.*?>.*", "", clean_reply)

    def _dedupe_paragraphs(text: str) -> str:
        parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        deduped: list[str] = []
        last_norm = None
        for part in parts:
            normalized = re.sub(r"\s+", " ", part).strip().lower()
            if normalized == last_norm:
                continue
            deduped.append(part)
            last_norm = normalized
        return "\n\n".join(deduped)

    clean_reply = _dedupe_paragraphs(clean_reply)

    return clean_reply.strip()


def _build_hospital_payload(raw: list[dict], fallback_tier: str | None) -> list[dict]:
    hospitals: list[dict] = []
    for index, item in enumerate(raw, start=1):
        name = item.get("name") or item.get("nombre") or f"Hospital {index}"
        address = item.get("address") or item.get("direccion") or "Manta"
        tiers = item.get("accepted_tiers") or []
        tier = fallback_tier or (tiers[0] if tiers else "General")
        distance = item.get("distanceKm") or item.get("distance_km") or 0.0
        try:
            distance_value = float(distance) if distance is not None else 0.0
        except (TypeError, ValueError):
            distance_value = 0.0

        raw_id = item.get("id") or f"hospital-{index}"
        hospitals.append(
            {
                "id": str(raw_id),
                "name": name,
                "address": address,
                "distanceKm": distance_value,
                "tier": tier,
            }
        )
    return hospitals


def _extract_cost_factor(item: dict) -> float:
    raw_multiplier = item.get("price_multiplier") or item.get("priceMultiplier")
    if raw_multiplier is not None:
        try:
            multiplier = float(raw_multiplier)
        except (TypeError, ValueError):
            multiplier = 1.0

        if multiplier > 0:
            return multiplier

    raw_discount = item.get("network_discount") or item.get("networkDiscount")
    if raw_discount is not None:
        try:
            discount = float(raw_discount)
        except (TypeError, ValueError):
            discount = 0.0

        if discount > 1:
            discount = discount / 100.0

        if 0 < discount < 1:
            return max(1.0 - discount, 0.01)

    return 1.0


def _extract_price_multiplier(item: dict) -> float:
    raw_multiplier = item.get("price_multiplier") or item.get("priceMultiplier")
    if raw_multiplier is None:
        return 1.0

    try:
        multiplier = float(raw_multiplier)
    except (TypeError, ValueError):
        return 1.0

    return multiplier if multiplier > 0 else 1.0


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_rate(value):
    if value is None:
        return None

    rate = _safe_float(value)
    if rate is None:
        return None

    if rate > 1:
        rate = rate / 100.0

    return min(max(rate, 0.0), 1.0)


def _normalize_discount(value) -> float:
    if value is None:
        return 0.0

    discount = _safe_float(value)
    if discount is None:
        return 0.0

    if discount > 1:
        discount = discount / 100.0

    return min(max(discount, 0.0), 1.0)


def _is_in_network(status) -> bool:
    if not status:
        return True

    normalized = str(status).strip().lower()
    if "out" in normalized or "fuera" in normalized or "extern" in normalized:
        return False

    return True


def _apply_coverage(base_cost: float, coverage_rate, flat_copay, insurance_available: bool) -> dict:
    base = round(max(base_cost, 0.0), 2)
    if not insurance_available:
        return {"base": base, "coverage": 0.0, "copay": base}

    flat = _safe_float(flat_copay)
    if flat is not None and flat > 0:
        copay = min(flat, base)
        coverage = round(max(base - copay, 0.0), 2)
        return {"base": base, "coverage": coverage, "copay": round(copay, 2)}

    rate = _normalize_rate(coverage_rate) or 0.0
    coverage = round(base * rate, 2)
    copay = round(max(base - coverage, 0.0), 2)
    return {"base": base, "coverage": coverage, "copay": copay}


def _build_cost_model(urgency_level: int, specialty: str, insurance_tier: str | None):
    specialty_row = get_specialty_by_name(specialty)
    if not specialty_row:
        return None

    base_value = _safe_float(specialty_row.get("base_consultation_cost"))
    if base_value is None:
        return None

    multiplier = URGENCY_MULTIPLIER.get(urgency_level, 1.0)
    base_cost = round(max(base_value * multiplier, 15.0), 2)

    policy = get_policy_by_tier(insurance_tier) if insurance_tier else None
    coverage_row = None
    if policy:
        coverage_row = get_coverage_for_policy(policy.get("id"), specialty_row.get("id"))

    coverage_rate = coverage_row.get("coverage_percentage") if coverage_row else None
    flat_copay = coverage_row.get("flat_copay") if coverage_row else None

    return {
        "base_cost": base_cost,
        "coverage_rate": coverage_rate,
        "flat_copay": flat_copay,
        "policy_id": policy.get("id") if policy else None,
        "has_coverage_data": coverage_row is not None,
    }


def _attach_hospital_costs(hospitals: list[dict], raw: list[dict], analysis) -> list[dict]:
    for index, hospital in enumerate(hospitals):
        raw_item = raw[index] if index < len(raw) else {}
        factor = _extract_cost_factor(raw_item)
        hospital["estimatedCost"] = estimate_cost_with_factor(
            analysis.specialty,
            analysis.urgency_level,
            analysis.insurance_tier,
            analysis.has_insurance,
            factor,
        )

    hospitals.sort(key=lambda item: item.get("estimatedCost", {}).get("copay", float("inf")))
    return hospitals


def _attach_hospital_costs_db(
    hospitals: list[dict],
    raw: list[dict],
    analysis: TriageResult,
    cost_model: dict,
    contracts: dict,
    insurance_available: bool,
) -> list[dict]:
    base_cost = cost_model.get("base_cost")
    coverage_rate = cost_model.get("coverage_rate")
    flat_copay = cost_model.get("flat_copay")
    has_coverage = cost_model.get("has_coverage_data")

    for index, hospital in enumerate(hospitals):
        raw_item = raw[index] if index < len(raw) else {}
        price_multiplier = _extract_price_multiplier(raw_item)
        contract = contracts.get(str(hospital.get("id")))
        discount = _normalize_discount(contract.get("negotiated_discount")) if contract else 0.0
        if contract and not _is_in_network(contract.get("network_status")):
            discount = 0.0

        factor = price_multiplier * (1.0 - discount)
        if base_cost is None or (insurance_available and not has_coverage):
            hospital["estimatedCost"] = estimate_cost_with_factor(
                analysis.specialty,
                analysis.urgency_level,
                analysis.insurance_tier,
                analysis.has_insurance,
                factor,
            )
            continue

        adjusted_base = round(max(base_cost * factor, 10.0), 2)
        hospital["estimatedCost"] = _apply_coverage(
            adjusted_base,
            coverage_rate,
            flat_copay,
            insurance_available,
        )

    hospitals.sort(key=lambda item: item.get("estimatedCost", {}).get("copay", float("inf")))
    return hospitals


def _build_best_option(
    hospitals: list[dict],
    specialty: str,
    insurance_tier: str | None,
    insurance_available: bool,
    show_cost: bool,
) -> dict | None:
    if not show_cost:
        return None

    priced_hospitals = [
        hospital
        for hospital in hospitals
        if isinstance(hospital.get("estimatedCost"), dict)
        and isinstance(hospital["estimatedCost"].get("copay"), (int, float))
    ]
    if not priced_hospitals:
        return None

    best = min(priced_hospitals, key=lambda item: item["estimatedCost"]["copay"])
    plan_label = insurance_tier if insurance_available and insurance_tier else "pago particular"
    reason = f"Menor copago estimado para {specialty} con {plan_label}."

    return {
        "hospitalId": str(best.get("id")),
        "hospitalName": best.get("name") or "Hospital recomendado",
        "address": best.get("address") or "Manta",
        "tier": best.get("tier") or plan_label,
        "estimatedCost": best["estimatedCost"],
        "reason": reason,
    }


def _max_historical_urgency(messages: list[str]) -> int:
    max_level = 1
    for text in messages:
        if not text:
            continue
        level = analyze_message(text).urgency_level
        if level > max_level:
            max_level = level
    return max_level


def _resolve_specialty(current_analysis: TriageResult, accumulated_analysis: TriageResult) -> str:
    if current_analysis.specialty != GENERAL_SPECIALTY:
        return current_analysis.specialty

    return accumulated_analysis.specialty


def _resolve_insurance_from_payload(value: str | None) -> tuple[str | None, bool | None]:
    if not value:
        return None, None

    normalized = value.strip().lower()
    if normalized in {"sin seguro", "particular", "sin cobertura", "no tengo seguro", "no estoy afiliado"}:
        return None, False

    if normalized in TIER_MAP:
        return TIER_MAP[normalized], True

    return None, None


def _resolve_session(payload: ChatRequest, http_request: Request, response: Response) -> str:
    cookie_session = http_request.cookies.get("cg_session_id")
    session_id = payload.sessionId or cookie_session or str(uuid4())
    response.set_cookie(
        key="cg_session_id",
        value=session_id,
        httponly=False,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    if DEBUG_TRIAGE:
        _log(f"DEBUG: session_source={_session_source(payload.sessionId, cookie_session)} session={session_id}")
    return session_id


def _session_source(payload_session: str | None, cookie_session: str | None) -> str:
    if payload_session:
        return "body"
    if cookie_session:
        return "cookie"
    return "new"


def _validate_message(payload: ChatRequest) -> str:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    return message


def _resolve_urgency(
    current_analysis: TriageResult,
    accumulated_analysis: TriageResult,
    patient_messages: list[str],
    session_id: str,
) -> int:
    historical_urgency = _max_historical_urgency(patient_messages)
    urgency_level = max(accumulated_analysis.urgency_level, historical_urgency, current_analysis.urgency_level)
    if DEBUG_TRIAGE:
        _log(
            f"DEBUG: session={session_id} historical={historical_urgency} current={current_analysis.urgency_level} accumulated={accumulated_analysis.urgency_level} total={urgency_level} messages={len(patient_messages)}"
        )
    return urgency_level


def _resolve_insurance(payload: ChatRequest, current_analysis: TriageResult, accumulated_analysis: TriageResult):
    payload_tier, payload_has_insurance = _resolve_insurance_from_payload(payload.insuranceTier)
    insurance_tier = payload_tier or current_analysis.insurance_tier or accumulated_analysis.insurance_tier
    insurance_available = payload_has_insurance
    if insurance_available is None:
        insurance_available = current_analysis.has_insurance and accumulated_analysis.has_insurance
    return insurance_tier, insurance_available


def _resolve_cost(
    urgency_level: int,
    specialty: str,
    insurance_tier: str | None,
    insurance_available: bool,
) -> tuple[dict | None, bool, dict]:
    cost_model = _build_cost_model(urgency_level, specialty, insurance_tier)
    use_db_cost = bool(cost_model and (not insurance_available or cost_model.get("has_coverage_data")))
    if use_db_cost:
        cost = _apply_coverage(
            cost_model.get("base_cost"),
            cost_model.get("coverage_rate"),
            cost_model.get("flat_copay"),
            insurance_available,
        )
    else:
        cost = estimate_cost(
            specialty,
            urgency_level,
            insurance_tier,
            insurance_available,
        )
    return cost_model, use_db_cost, cost


def _build_chat_context(payload: ChatRequest, session_id: str) -> ChatContext:
    message = _validate_message(payload)
    history_text = get_chat_history(session_id)
    patient_messages = get_patient_messages(session_id)
    full_symptoms = " ".join([*patient_messages, message]).strip()
    current_analysis = analyze_message(message)
    accumulated_analysis = analyze_message(full_symptoms)
    urgency_level = _resolve_urgency(current_analysis, accumulated_analysis, patient_messages, session_id)
    insurance_tier, insurance_available = _resolve_insurance(payload, current_analysis, accumulated_analysis)
    specialty = _resolve_specialty(current_analysis, accumulated_analysis)
    cost_model, use_db_cost, cost = _resolve_cost(
        urgency_level,
        specialty,
        insurance_tier,
        insurance_available,
    )
    show_cost = urgency_level < 4
    analysis_for_cost = TriageResult(
        urgency_level=urgency_level,
        specialty=specialty,
        insurance_tier=insurance_tier,
        has_insurance=insurance_available,
    )
    return ChatContext(
        message=message,
        session_id=session_id,
        history_text=history_text,
        full_symptoms=full_symptoms,
        urgency_level=urgency_level,
        specialty=specialty,
        insurance_tier=insurance_tier,
        insurance_available=insurance_available,
        cost_model=cost_model,
        use_db_cost=use_db_cost,
        cost=cost,
        show_cost=show_cost,
        analysis_for_cost=analysis_for_cost,
    )


def _build_contextual_message(context: ChatContext) -> str:
    return (
        f"{context.history_text}"
        f"Contexto interno: El paciente tiene urgencia {context.urgency_level}/5 y requiere {context.specialty}. "
        f"Sintomas acumulados reportados: {context.full_symptoms}. "
        f"Usa el ultimo mensaje para ajustar el foco clinico sin olvidar sintomas previos.\n\n"
        f"Mensaje original del paciente: {context.message}"
    )


def _get_ai_reply(contextual_message: str) -> str:
    raw_reply = None
    if GROQ_API_KEY_PRESENT:
        try:
            result = careguide_ai.run(contextual_message)
            raw_reply = result.content if hasattr(result, "content") else str(result)
        except Exception:
            raw_reply = None

    if not isinstance(raw_reply, str):
        raw_reply = "" if raw_reply is None else str(raw_reply)

    return _sanitize_reply(raw_reply)


def _build_hospital_search_query(message: str, insurance_tier: str | None) -> str:
    if insurance_tier and insurance_tier.lower() not in message.lower():
        return f"{message} seguro {insurance_tier}"
    return f"{message} hospital en Manta"


def _build_contract_map(cost_model: dict | None, hospitals: list[dict]) -> dict:
    if not cost_model or not cost_model.get("policy_id"):
        return {}
    hospital_ids = [hospital.get("id") for hospital in hospitals if hospital.get("id") is not None]
    return get_contracts_for_policy(cost_model.get("policy_id"), hospital_ids)


def _attach_costs_to_hospitals(context: ChatContext, hospitals: list[dict], raw: list[dict]) -> list[dict]:
    if not context.show_cost:
        return hospitals

    if context.use_db_cost:
        hospitals = _attach_hospital_costs_db(
            hospitals,
            raw,
            context.analysis_for_cost,
            context.cost_model,
            _build_contract_map(context.cost_model, hospitals),
            context.insurance_available,
        )
        if DEBUG_TRIAGE:
            _log(f"DEBUG /chat: after _attach_hospital_costs_db: {len(hospitals)} hospitals")
        return hospitals

    hospitals = _attach_hospital_costs(hospitals, raw, context.analysis_for_cost)
    if DEBUG_TRIAGE:
        _log(f"DEBUG /chat: after _attach_hospital_costs: {len(hospitals)} hospitals")
    return hospitals


def _get_hospital_recommendations(context: ChatContext) -> list[dict]:
    hospital_tier = context.insurance_tier or ("General" if not context.insurance_available else None)
    raw = search_hospitals(_build_hospital_search_query(context.message, context.insurance_tier))
    if DEBUG_TRIAGE:
        count = len(raw) if isinstance(raw, list) else "ERROR"
        _log(f"DEBUG /chat: search_hospitals returned {count} items")

    if not isinstance(raw, list):
        return []

    hospitals = _build_hospital_payload(raw, hospital_tier)
    if DEBUG_TRIAGE:
        _log(f"DEBUG /chat: after _build_hospital_payload: {len(hospitals)} hospitals")
    return _attach_costs_to_hospitals(context, hospitals, raw)


def _append_hospital_suggestions(reply: str, hospitals: list[dict]) -> str:
    if not hospitals or "hospital" in reply.lower():
        return reply

    top = hospitals[:3]
    suggestion_text = ", ".join(f"{hospital['name']} ({hospital['tier']})" for hospital in top)
    return f"{reply}\n\nSugerencias: {suggestion_text}."


def _build_chat_response(context: ChatContext, reply: str, hospitals: list[dict], started_at: float) -> dict:
    best_option = _build_best_option(
        hospitals,
        context.specialty,
        context.insurance_tier,
        context.insurance_available,
        context.show_cost,
    )
    latency_ms = int((time.time() - started_at) * 1000)

    return {
        "id": str(uuid4()),
        "sessionId": context.session_id,
        "reply": reply,
        "urgencyLevel": context.urgency_level,
        "specialty": context.specialty,
        "latencyMs": latency_ms,
        "cost": context.cost,
        "showCost": context.show_cost,
        "hospitals": hospitals,
        "bestOption": best_option,
    }


def _build_error_response(session_id: str, started_at: float) -> dict:
    latency_ms = int((time.time() - started_at) * 1000)
    fallback_cost = estimate_cost("Medicina general", 2, None, True)
    return {
        "id": str(uuid4()),
        "sessionId": session_id,
        "reply": DEFAULT_ERROR_REPLY,
        "urgencyLevel": 2,
        "specialty": "Medicina general",
        "latencyMs": latency_ms,
        "cost": fallback_cost,
        "showCost": True,
        "hospitals": [],
        "bestOption": None,
    }


@app.post("/chat", response_model=ChatResponse, responses={400: {"description": "message is required"}})
def chat(payload: ChatRequest, http_request: Request, response: Response):
    started_at = time.time()
    session_id = _resolve_session(payload, http_request, response)
    try:
        context = _build_chat_context(payload, session_id)
        reply = _get_ai_reply(_build_contextual_message(context))
        hospitals = _get_hospital_recommendations(context)

        if DEBUG_TRIAGE:
            _log(f"DEBUG /chat: returning {len(hospitals)} hospitals in response")

        if hospitals:
            save_recommendations(context.message, hospitals)
            reply = _append_hospital_suggestions(reply, hospitals)

        save_chat_message(session_id, "Paciente", context.message)
        save_chat_message(session_id, "IA", reply)
        return _build_chat_response(context, reply, hospitals, started_at)
    except HTTPException:
        raise
    except Exception as exc:
        _log(f"ERROR /chat: {exc}")
        return _build_error_response(session_id, started_at)
