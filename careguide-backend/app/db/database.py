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

def search_hospitals(query: str):
    """
    Busca hospitales en Manta por nombre o por nivel de seguro (Oro, Plata, Bronce).
    """
    # Limpiamos la consulta para extraer la palabra clave (ej: de 'Seguro Oro' a 'Oro')
    lower_query = query.lower()
    
    # Usamos expresiones regulares para ignorar errores ortográficos comunes y palabras de relleno
    stop_words_pattern = r'\b(hospitales|hospital|hospita|clinicas|clinica|clinic|seguro|quiero|busco|necesito|un|una|en manta)\b'
    cleaned_query = re.sub(stop_words_pattern, '', lower_query)
    keyword = cleaned_query.strip()
    keyword = keyword.capitalize() if keyword else ""

    tiers = ["oro", "plata", "bronce"]
    requested_tier = next((tier for tier in tiers if tier in lower_query), None)
    is_general_request = any(
        token in lower_query for token in ["hospital", "clinica", "recomend", "diabet", "chequeo"]
    )
    
    if DEBUG_SUPABASE:
        _log(f"DEBUG: searching hospitals with keyword '{keyword}'")
    
    if db_client is None:
        if requested_tier:
            requested_label = requested_tier.capitalize()
            tier_matches = [
                hospital
                for hospital in FALLBACK_HOSPITALS
                if requested_label in hospital["accepted_tiers"]
            ]
            if tier_matches:
                return tier_matches

        if keyword:
            keyword_lower = keyword.lower()
            name_matches = [
                hospital
                for hospital in FALLBACK_HOSPITALS
                if keyword_lower in hospital["name"].lower()
            ]
            if name_matches:
                return name_matches

        if is_general_request:
            return FALLBACK_HOSPITALS

        return f"No se encontraron resultados para '{query}'. Intenta buscando por 'Oro', 'Plata' o nombres especificos."

    try:
        all_hospitals = db_client.table("hospitals").select("*").execute().data or []

        res_tier = []
        if requested_tier:
            requested_label = requested_tier.capitalize()
            res_tier = [
                hospital
                for hospital in all_hospitals
                if requested_label in (hospital.get("accepted_tiers") or [])
            ]
            if res_tier:
                if DEBUG_SUPABASE:
                    _log(f"DEBUG: found {len(res_tier)} hospitals by tier.")
                return res_tier

        if keyword:
            res_name = [
                hospital
                for hospital in all_hospitals
                if keyword.lower() in (hospital.get("name") or "").lower()
            ]
            if res_name:
                if DEBUG_SUPABASE:
                    _log(f"DEBUG: found {len(res_name)} hospitals by name.")
                return res_name

        if is_general_request:
            if all_hospitals:
                if DEBUG_SUPABASE:
                    _log(f"DEBUG: found {len(all_hospitals)} hospitals.")
                return all_hospitals

        return f"No se encontraron resultados para '{query}'. Intenta buscando por 'Oro', 'Plata' o nombres específicos."

    except Exception as e:
        _log(f"ERROR: database connection failed: {e}")
        if requested_tier:
            requested_label = requested_tier.capitalize()
            tier_matches = [
                hospital
                for hospital in FALLBACK_HOSPITALS
                if requested_label in hospital["accepted_tiers"]
            ]
            if tier_matches:
                return tier_matches

        if is_general_request:
            return FALLBACK_HOSPITALS

        return []


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
