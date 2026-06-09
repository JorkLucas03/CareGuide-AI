import os
import re
import unicodedata
from dotenv import load_dotenv

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = None

# Cargamos las variables de entorno (.env)
load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SAVE_RECOMMENDATIONS = os.environ.get("SAVE_RECOMMENDATIONS", "false").lower() in {
    "1",
    "true",
    "yes",
}
DEBUG_SUPABASE = os.environ.get("DEBUG_SUPABASE", "false").lower() in {
    "1",
    "true",
    "yes",
}


def _log(message: str) -> None:
    print(message.encode("ascii", errors="replace").decode("ascii"))


# Inicializamos el cliente de la base de datos si esta disponible
db_client = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    db_client = create_client(SUPABASE_URL, SUPABASE_KEY)

FALLBACK_HOSPITALS = [
    {
        "id": "manta-1",
        "name": "Clinica Manta",
        "accepted_tiers": ["Oro", "Plata"],
    },
    {
        "id": "manta-2",
        "name": "Hospital del IESS Manta",
        "accepted_tiers": ["Oro", "Plata", "Bronce"],
    },
    {
        "id": "manta-3",
        "name": "Centro Medico del Pacifico",
        "accepted_tiers": ["Oro", "Plata"],
    },
    {
        "id": "manta-4",
        "name": "Clinica San Francisco",
        "accepted_tiers": ["Oro"],
    },
]


STOP_WORDS_PATTERN = r"\b(hospitales|hospital|hospita|clinicas|clinica|clinic|seguro|quiero|busco|necesito|un|una|en manta)\b"
TIERS = ["oro", "plata", "bronce"]
GENERAL_REQUEST_TOKENS = ["hospital", "clinica", "recomend", "diabet", "chequeo"]


def _not_found_message(query: str) -> str:
    return f"No se encontraron resultados para '{query}'. Intenta buscando por 'Oro', 'Plata' o nombres especificos."


def _extract_search_terms(query: str) -> tuple[str, str | None, bool]:
    lower_query = query.lower()
    cleaned_query = re.sub(STOP_WORDS_PATTERN, "", lower_query)
    keyword = cleaned_query.strip().capitalize()
    requested_tier = next((tier for tier in TIERS if tier in lower_query), None)
    is_general_request = any(token in lower_query for token in GENERAL_REQUEST_TOKENS)
    return keyword, requested_tier, is_general_request


def _filter_by_tier(hospitals: list[dict], requested_tier: str | None) -> list[dict]:
    if not requested_tier:
        return []

    requested_label = requested_tier.capitalize()
    return [
        hospital
        for hospital in hospitals
        if requested_label in (hospital.get("accepted_tiers") or [])
    ]


def _filter_by_name(hospitals: list[dict], keyword: str) -> list[dict]:
    if not keyword:
        return []

    keyword_lower = keyword.lower()
    return [
        hospital
        for hospital in hospitals
        if keyword_lower in (hospital.get("name") or "").lower()
    ]


def _select_hospitals(
    hospitals: list[dict],
    requested_tier: str | None,
    keyword: str,
    is_general_request: bool,
    query: str,
) -> list[dict] | str:
    tier_matches = _filter_by_tier(hospitals, requested_tier)
    if tier_matches:
        return tier_matches

    name_matches = _filter_by_name(hospitals, keyword)
    if name_matches:
        return name_matches

    if is_general_request and hospitals:
        return hospitals

    return _not_found_message(query)


def search_hospitals(query: str):
    """
    Busca hospitales en Manta por nombre o por nivel de seguro (Oro, Plata, Bronce).
    """
    # Limpiamos la consulta para extraer la palabra clave (ej: de 'Seguro Oro' a 'Oro')
    keyword, requested_tier, is_general_request = _extract_search_terms(query)
    
    # Usamos expresiones regulares para ignorar errores ortográficos comunes y palabras de relleno
    
    if DEBUG_SUPABASE:
        _log(f"DEBUG: searching hospitals with keyword '{keyword}'")
    
    if db_client is None:
        return _select_hospitals(FALLBACK_HOSPITALS, requested_tier, keyword, is_general_request, query)

    try:
        all_hospitals = db_client.table("hospitals").select("*").execute().data or []

        results = _select_hospitals(all_hospitals, requested_tier, keyword, is_general_request, query)
        if DEBUG_SUPABASE and isinstance(results, list):
            _log(f"DEBUG: found {len(results)} hospitals.")
        return results

    except Exception as e:
        _log(f"ERROR: database connection failed: {e}")
        results = _select_hospitals(FALLBACK_HOSPITALS, requested_tier, keyword, is_general_request, query)
        return results if isinstance(results, list) else []


def save_recommendations(message: str, hospitals: list[dict], user_id: str | None = None) -> None:
    if not SAVE_RECOMMENDATIONS:
        return
    if db_client is None:
        return

    if not hospitals:
        return

    payload = {
        "query": message,
        "hospitals": hospitals,
    }

    if user_id:
        payload["user_id"] = user_id

    try:
        db_client.table("hospital_recommendations").insert(payload).execute()
    except Exception as e:
        _log(f"ERROR: saving recommendations failed: {e}")


def get_patient_messages(session_id: str) -> list[str]:
    if db_client is None:
        if DEBUG_SUPABASE:
            _log("DEBUG: Supabase client not initialized; cannot read chat_history.")
        return []

    try:
        res = (
            db_client.table("chat_history")
            .select("role, content")
            .eq("session_id", session_id)
            .order("created_at", desc=False)
            .execute()
        )
        if DEBUG_SUPABASE and getattr(res, "error", None):
            _log(f"DEBUG: reading patient messages failed: {res.error}")
            return []

        if not res.data:
            return []

        return [
            row["content"]
            for row in res.data
            if row.get("role") == "Paciente" and row.get("content")
        ]
    except Exception as e:
        _log(f"ERROR: reading patient messages failed: {e}")
        return []

def get_chat_history(session_id: str) -> str:
    if db_client is None:
        if DEBUG_SUPABASE:
            _log("DEBUG: Supabase client not initialized; cannot read history.")
        return ""
    try:
        res = db_client.table("chat_history").select("*").eq("session_id", session_id).order("created_at", desc=False).execute()
        if not res.data: return ""
        history = "\n".join([f"{row['role']}: {row['content']}" for row in res.data])
        return f"\n\n--- HISTORIAL DE CONVERSACIÓN PREVIA ---\n{history}\n----------------------------------------\n"
    except Exception as e:
        _log(f"ERROR: reading history failed: {e}")
        return ""

def save_chat_message(session_id: str, role: str, content: str):
    if db_client is None:
        if DEBUG_SUPABASE:
            _log("DEBUG: Supabase client not initialized; cannot save chat_history.")
        return
    try:
        res = db_client.table("chat_history").insert({
            "session_id": session_id,
            "role": role,
            "content": content
        }).execute()
        if DEBUG_SUPABASE and getattr(res, "error", None):
            _log(f"DEBUG: saving message failed: {res.error}")
    except Exception as e:
        _log(f"ERROR: saving message failed: {e}")


def get_policy_by_tier(tier: str):
    if db_client is None or not tier:
        return None

    try:
        res = (
            db_client.table("insurance_policies")
            .select("*")
            .eq("tier", tier)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]

        res = (
            db_client.table("insurance_policies")
            .select("*")
            .ilike("tier", tier)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        _log(f"ERROR: reading insurance_policies failed: {e}")
        return None


def get_insurance_policies() -> list[dict]:
    if db_client is None:
        return []

    try:
        res = (
            db_client.table("insurance_policies")
            .select("id, provider_name, tier, deductible, max_out_of_pocket")
            .execute()
        )
        return res.data or []
    except Exception as e:
        _log(f"ERROR: reading insurance_policies list failed: {e}")
        return []


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "")
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return stripped.lower().strip()


def get_specialty_by_name(name: str):
    if db_client is None or not name:
        return None

    try:
        res = (
            db_client.table("specialties")
            .select("*")
            .eq("name", name)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]

        res = (
            db_client.table("specialties")
            .select("*")
            .ilike("name", name)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]

        normalized_target = _normalize_text(name)
        if not normalized_target:
            return None

        res = db_client.table("specialties").select("*").execute()
        for row in res.data or []:
            if _normalize_text(row.get("name") or "") == normalized_target:
                return row

        return None
    except Exception as e:
        _log(f"ERROR: reading specialties failed: {e}")
        return None


def get_coverage_for_policy(policy_id, specialty_id):
    if db_client is None or policy_id is None or specialty_id is None:
        return None

    try:
        res = (
            db_client.table("coverages")
            .select("*")
            .eq("policy_id", policy_id)
            .eq("specialty_id", specialty_id)
            .order("coverage_percentage", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        _log(f"ERROR: reading coverages failed: {e}")
        return None


def get_contracts_for_policy(policy_id, hospital_ids: list):
    if db_client is None or policy_id is None or not hospital_ids:
        return {}

    try:
        res = (
            db_client.table("hospital_insurance_contracts")
            .select("*")
            .eq("policy_id", policy_id)
            .in_("hospital_id", hospital_ids)
            .execute()
        )
        if not res.data:
            return {}

        return {str(row.get("hospital_id")): row for row in res.data if row.get("hospital_id") is not None}
    except Exception as e:
        _log(f"ERROR: reading hospital_insurance_contracts failed: {e}")
        return {}
