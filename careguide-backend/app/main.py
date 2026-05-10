from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
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
        return "No pude procesar tu mensaje. Intenta otra vez."

    lowered = reply.lower()
    if "tool_use_failed" in lowered or "failed_generation" in lowered:
        return "No pude procesar tu mensaje. Intenta otra vez."

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


def _max_historical_urgency(messages: list[str]) -> int:
    max_level = 1
    for text in messages:
        if not text:
            continue
        level = analyze_message(text).urgency_level
        if level > max_level:
            max_level = level
    return max_level


def _resolve_insurance_from_payload(value: str | None) -> tuple[str | None, bool | None]:
    if not value:
        return None, None

    normalized = value.strip().lower()
    if normalized in {"sin seguro", "particular", "sin cobertura", "no tengo seguro", "no estoy afiliado"}:
        return None, False

    if normalized in TIER_MAP:
        return TIER_MAP[normalized], True

    return None, None


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, http_request: Request, response: Response):
    started_at = time.time()
    cookie_session = http_request.cookies.get("cg_session_id")
    session_id = payload.sessionId or cookie_session or str(uuid4())
    response.set_cookie(key="cg_session_id", value=session_id, httponly=False, samesite="lax")
    if DEBUG_TRIAGE:
        if payload.sessionId:
            session_source = "body"
        elif cookie_session:
            session_source = "cookie"
        else:
            session_source = "new"
        _log(f"DEBUG: session_source={session_source} session={session_id}")
    try:
        message = payload.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")

        history_text = get_chat_history(session_id)

        # Acumulamos todos los sintomas previos del paciente para que el Triage no olvide emergencias
        patient_messages = get_patient_messages(session_id)
        full_symptoms = " ".join([*patient_messages, message]).strip()

        analysis = analyze_message(full_symptoms)
        historical_urgency = _max_historical_urgency(patient_messages)
        urgency_level = max(analysis.urgency_level, historical_urgency)
        if DEBUG_TRIAGE:
            _log(
                f"DEBUG: session={session_id} historical={historical_urgency} current={analysis.urgency_level} total={urgency_level} messages={len(patient_messages)}"
            )
        payload_tier, payload_has_insurance = _resolve_insurance_from_payload(payload.insuranceTier)
        insurance_tier = payload_tier or analysis.insurance_tier
        if payload_has_insurance is None:
            insurance_available = analysis.has_insurance
        else:
            insurance_available = payload_has_insurance

        specialty = analysis.specialty
        cost_model = _build_cost_model(urgency_level, specialty, insurance_tier)
        use_db_cost = cost_model and (not insurance_available or cost_model.get("has_coverage_data"))
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
        show_cost = urgency_level < 4
        analysis_for_cost = TriageResult(
            urgency_level=urgency_level,
            specialty=specialty,
            insurance_tier=insurance_tier,
            has_insurance=insurance_available,
        )

        # Inyectamos el contexto médico calculado a la IA
        contextual_message = f"{history_text}Contexto interno: El paciente tiene urgencia {urgency_level}/5 y requiere {specialty}. \n\nMensaje original del paciente: {message}"
        
        raw_reply = None
        if GROQ_API_KEY_PRESENT:
            try:
                result = careguide_ai.run(contextual_message)
                raw_reply = result.content if hasattr(result, "content") else str(result)
            except Exception:
                raw_reply = None

        if not isinstance(raw_reply, str):
            raw_reply = "" if raw_reply is None else str(raw_reply)

        reply = _sanitize_reply(raw_reply)

        hospitals: list[dict] = []
        suggest_hospitals = True
        if suggest_hospitals:
            hospital_tier = insurance_tier or ("General" if not insurance_available else None)
            search_query = f"{message} hospital en Manta"
            if insurance_tier and insurance_tier.lower() not in message.lower():
                search_query = f"{message} seguro {insurance_tier}"
            raw = search_hospitals(search_query)
            if DEBUG_TRIAGE:
                _log(f"DEBUG /chat: search_hospitals returned {len(raw) if isinstance(raw, list) else 'ERROR'} items")
            if isinstance(raw, list):
                hospitals = _build_hospital_payload(raw, hospital_tier)
                if DEBUG_TRIAGE:
                    _log(f"DEBUG /chat: after _build_hospital_payload: {len(hospitals)} hospitals")
                contract_map: dict = {}
                if cost_model and cost_model.get("policy_id"):
                    hospital_ids = [hospital.get("id") for hospital in hospitals if hospital.get("id") is not None]
                    contract_map = get_contracts_for_policy(cost_model.get("policy_id"), hospital_ids)
                if show_cost:
                    if use_db_cost:
                        hospitals = _attach_hospital_costs_db(
                            hospitals,
                            raw,
                            analysis_for_cost,
                            cost_model,
                            contract_map,
                            insurance_available,
                        )
                        if DEBUG_TRIAGE:
                            _log(f"DEBUG /chat: after _attach_hospital_costs_db: {len(hospitals)} hospitals")
                    else:
                        hospitals = _attach_hospital_costs(hospitals, raw, analysis_for_cost)
                        if DEBUG_TRIAGE:
                            _log(f"DEBUG /chat: after _attach_hospital_costs: {len(hospitals)} hospitals")

        if DEBUG_TRIAGE:
            _log(f"DEBUG /chat: returning {len(hospitals)} hospitals in response")

        if hospitals:
            save_recommendations(message, hospitals)

            if "hospital" not in reply.lower():
                top = hospitals[:3]
                suggestion_text = ", ".join(f"{hospital['name']} ({hospital['tier']})" for hospital in top)
                reply = f"{reply}\n\nSugerencias: {suggestion_text}."

        save_chat_message(session_id, "Paciente", message)
        save_chat_message(session_id, "IA", reply)

        latency_ms = int((time.time() - started_at) * 1000)

        return {
            "id": str(uuid4()),
            "sessionId": session_id,
            "reply": reply,
            "urgencyLevel": urgency_level,
            "specialty": specialty,
            "latencyMs": latency_ms,
            "cost": cost,
            "showCost": show_cost,
            "hospitals": hospitals,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _log(f"ERROR /chat: {exc}")
        latency_ms = int((time.time() - started_at) * 1000)
        fallback_cost = estimate_cost("Medicina general", 2, None, True)
        return {
            "id": str(uuid4()),
            "sessionId": session_id,
            "reply": "No pude procesar tu mensaje. Intenta otra vez.",
            "urgencyLevel": 2,
            "specialty": "Medicina general",
            "latencyMs": latency_ms,
            "cost": fallback_cost,
            "showCost": True,
            "hospitals": [],
        }
