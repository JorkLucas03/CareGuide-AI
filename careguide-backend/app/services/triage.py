from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class TriageResult:
    urgency_level: int
    specialty: str
    insurance_tier: str | None
    has_insurance: bool


GENERAL_SPECIALTY = "Medicina general"

TIER_MAP = {
    "oro": "Oro",
    "plata": "Plata",
    "bronce": "Bronce",
}

NO_INSURANCE_PHRASES = [
    "sin seguro",
    "sin cobertura",
    "particular",
    "no tengo seguro",
    "no estoy afiliado",
]

SPECIALTY_RULES: list[tuple[str, list[str]]] = [
    ("Cardiologia", [
        "paro cardiaco",
        "paro del corazon",
        "ataque cardiaco",
        "ataque al corazon",
        "dolor de pecho",
        "dolor toracico",
        "pecho",
        "cardio",
        "corazon",
        "palpitacion",
        "palpitaciones",
        "taquicardia",
        "bradicardia",
        "arritmia",
        "latidos irregulares",
        "opresion",
        "presion en el pecho",
        "dolor en el brazo izquierdo",
        "hipertension",
        "presion alta",
        "edema",
        "hinchazon de piernas",
        "angina",
        "insuficiencia cardiaca",
        "isquemia",
        "infarto",
    ]),
    ("Neurologia", [
        "dolor de cabeza",
        "duele la cabeza",
        "cabeza",
        "cefalea",
        "migra",
        "migrana",
        "convulsion",
        "convulsiones",
        "epilep",
        "neurolog",
        "mareo",
        "vertigo",
        "desmayo",
        "temblor",
        "tremor",
        "hormigueo",
        "entumecimiento",
        "debilidad",
        "paralisis",
        "acv",
        "ictus",
        "memoria",
        "confusion",
        "vision doble",
        "ataxia",
        "neuropatia",
        "nervio",
        "tics",
    ]),
    ("Neumologia", [
        "asma",
        "bronqu",
        "pulmon",
        "respirar",
        "respiracion",
        "disnea",
        "ahogo",
        "falta de aire",
        "tos",
        "tos seca",
        "tos con flema",
        "flema",
        "esputo",
        "sibilancias",
        "neumonia",
        "dolor al respirar",
        "opresion toracica",
        "apnea",
        "ronquidos",
        "tuberculosis",
        "tb",
    ]),
    ("Gastroenterologia", [
        "estomago",
        "abdominal",
        "dolor abdominal",
        "barriga",
        "panza",
        "gastr",
        "gastritis",
        "reflujo",
        "acidez",
        "indigestion",
        "colitis",
        "colon",
        "ulcera",
        "diarrea",
        "vomito",
        "nausea",
        "estrenimiento",
        "flatulencia",
        "heces",
        "sangre en heces",
    ]),
    ("Hepatologia", [
        "higado",
        "hepatic",
        "hepatitis",
        "ictericia",
        "cirrosis",
        "transaminasas",
        "bilis",
        "coluria",
    ]),
    ("Nefrologia", [
        "rinon",
        "renal",
        "insuficiencia renal",
        "dialisis",
        "creatinina",
        "proteinuria",
        "edema",
        "dolor renal",
        "litiasis",
        "calculos renales",
    ]),
    ("Urologia", [
        "pene",
        "peniano",
        "testiculo",
        "testiculos",
        "testicular",
        "escroto",
        "dolor genital",
        "orina",
        "orinar",
        "urin",
        "vejiga",
        "prostata",
        "cistitis",
        "hematuria",
        "ardor al orinar",
        "infeccion urinaria",
        "dolor al orinar",
        "retencion urinaria",
        "eyaculacion",
        "ereccion",
    ]),
    ("Obstetricia", [
        "embarazo",
        "embarazada",
        "gestacion",
        "prenatal",
        "parto",
        "contracciones",
        "bebe en camino",
        "movimientos del bebe",
        "dolor en el embarazo",
        "hemorragia en embarazo",
        "perdida de liquido",
    ]),
    ("Ginecologia", [
        "gine",
        "menstruacion",
        "periodo",
        "regla",
        "ovario",
        "uterino",
        "flujo vaginal",
        "vaginal",
        "dolor pelvico",
        "quiste",
        "endometriosis",
        "mioma",
        "papanicolau",
        "sangrado vaginal",
    ]),
    ("Pediatria", [
        "bebe",
        "nino",
        "nina",
        "nene",
        "pediatra",
        "pediatria",
        "infantil",
        "lactante",
        "recien nacido",
        "vacunas",
        "fiebre en bebe",
        "llanto",
    ]),
    ("Endocrinologia", [
        "diabetes",
        "glucosa",
        "azucar",
        "insulina",
        "tiroid",
        "hipotiroid",
        "hipertiroid",
        "hormona",
        "metabolismo",
        "colesterol",
        "trigliceridos",
        "obesidad",
        "hipoglucemia",
        "sop",
    ]),
    ("Dermatologia", [
        "piel",
        "erupcion",
        "sarpullido",
        "ronchas",
        "urticaria",
        "prurito",
        "picazon",
        "dermatitis",
        "eczema",
        "psoriasis",
        "acne",
        "herpes",
        "verruga",
        "hongos",
        "micosis",
        "mancha",
        "lunar",
        "alopecia",
        "alergia en la piel",
    ]),
    ("Reumatologia", [
        "artritis",
        "articulacion",
        "dolor articular",
        "rigidez",
        "inflamacion articular",
        "lupus",
        "gota",
        "fibromialgia",
        "reuma",
        "osteoartritis",
    ]),
    ("Traumatologia", [
        "fractura",
        "esguince",
        "luxacion",
        "torcedura",
        "contusion",
        "golpe",
        "trauma",
        "lesion",
        "rodilla",
        "tobillo",
        "hombro",
        "cadera",
        "columna",
        "espalda",
        "hernia discal",
    ]),
    ("Otorrinolaringologia", [
        "garganta",
        "amigdal",
        "amigdalitis",
        "otitis",
        "oido",
        "nariz",
        "sinus",
        "sinusitis",
        "rinitis",
        "congestion",
        "ronquera",
        "laringitis",
        "faringitis",
        "tinnitus",
        "zumbido",
    ]),
    ("Odontologia", [
        "muela",
        "diente",
        "dientes",
        "caries",
        "encia",
        "encias",
        "gingivitis",
        "absceso",
        "dolor dental",
        "sangrado encias",
        "bruxismo",
        "dolor de muela",
        "dolor de dientes",
    ]),
    ("Oftalmologia", [
        "ojo",
        "vision",
        "vista",
        "ojo rojo",
        "conjuntivitis",
        "catarata",
        "glaucoma",
        "dolor ocular",
        "fotofobia",
        "lagrimeo",
        "vision borrosa",
        "moscas volantes",
        "destellos",
        "parpado",
    ]),
    ("Psiquiatria", [
        "ansiedad",
        "depresion",
        "panico",
        "insomnio",
        "estres",
        "bipolar",
        "esquizof",
        "psicosis",
        "alucinacion",
        "ideacion suicida",
        "autolesion",
        "crisis nerviosa",
        "ataque de panico",
    ]),
    ("Alergologia", [
        "alergia",
        "rinitis alergica",
        "urticaria",
        "anafilaxia",
        "asma alergica",
        "prurito",
        "picazon",
        "hinchazon",
        "angioedema",
    ]),
    ("Infectologia", [
        "infeccion",
        "fiebre prolongada",
        "sepsis",
        "virus",
        "bacteria",
        "covid",
        "dengue",
        "zika",
        "chikungunya",
        "malaria",
        "tifoidea",
        "tuberculosis",
        "vih",
        "sida",
    ]),
    ("Hematologia", [
        "anemia",
        "hemoglobina",
        "plaquetas",
        "leucemia",
        "linfoma",
        "sangrado facil",
        "moretones",
        "coagulacion",
        "trombosis",
        "hemofilia",
    ]),
    ("Oncologia", [
        "cancer",
        "tumor",
        "metastasis",
        "quimioterapia",
        "radioterapia",
        "bulto",
        "masa",
        "ganglio",
        "nodo",
    ]),
    ("Geriatria", [
        "adulto mayor",
        "anciano",
        "geriatria",
        "demencia",
        "alzheimer",
        "fragilidad",
    ]),
    ("Nutricion", [
        "nutricion",
        "dieta",
        "peso",
        "imc",
        "sobrepeso",
        "obesidad",
        "bajo peso",
        "apetito",
        "nutricional",
    ]),
    ("Toxicologia", [
        "intoxicacion",
        "envenenamiento",
        "veneno",
        "sobredosis",
        "ingestion",
        "drogas",
        "alcohol",
        "sustancias",
    ]),
    ("Medicina interna", [
        "medicina interna",
        "enfermedad cronica",
        "hipertension",
        "diabetes",
        "colesterol alto",
        "control de enfermedades",
    ]),
    ("Cirugia general", [
        "apendicitis",
        "hernia",
        "dolor abdominal agudo",
        "vesicula",
        "colecistitis",
        "cirugia",
        "abdomen agudo",
    ]),
]

URGENCY_RULES: list[tuple[int, list[str]]] = [
    (5, [
        "infarto",
        "paro cardiaco",
        "paro del corazon",
        "ataque cardiaco",
        "ataque al corazon",
        "me va a dar un paro",
        "me va a dar un infarto",
        "no puedo respirar",
        "falta de aire",
        "falta de aire severa",
        "ahogo",
        "me ahogo",
        "no respiro",
        "sangrado abundante",
        "hemorragia",
        "sangrado imparable",
        "vomito con sangre",
        "heces negras",
        "convulsion",
        "convulsiones",
        "desmayo",
        "inconsciente",
        "no responde",
        "perdi el conocimiento",
        "perdida de conocimiento",
        "trauma craneal",
        "fractura expuesta",
        "quemadura grave",
        "quemadura extensa",
        "accidente",
        "dolor de pecho intenso",
        "duele mucho el pecho",
        "dolor en el brazo izquierdo",
        "paralisis",
        "ictus",
        "acv",
        "cianosis",
        "shock",
        "choque",
        "sepsis",
        "anafilaxia",
        "suicidio",
        "autolesion",
        "sobredosis",
        "intoxicacion severa",
    ]),
    (4, [
        "dolor de pecho",
        "duele el pecho",
        "opresion en el pecho",
        "presion en el pecho",
        "dolor en el corazon",
        "duele el corazon",
        "dificultad para respirar",
        "dolor abdominal severo",
        "dolor abdominal intenso",
        "dolor renal intenso",
        "dolor testicular",
        "dolor pelvico intenso",
        "vomito persistente",
        "vomitos persistentes",
        "fiebre muy alta",
        "fiebre alta persistente",
        "sangrado",
        "fractura",
        "quemadura",
        "presion alta",
        "mareo intenso",
        "vision borrosa",
        "perdida de vision",
        "dolor de cabeza intenso",
        "confusion",
        "deshidratacion",
        "palpitaciones fuertes",
    ]),
    (3, [
        "fiebre alta",
        "fiebre",
        "vomito",
        "vomita",
        "diarrea",
        "diarre",
        "diarrea persistente",
        "dolor fuerte",
        "infeccion",
        "dolor abdominal",
        "dolor de barriga",
        "duele la barriga",
        "dolor de cabeza",
        "dolor de garganta",
        "dolor de oido",
        "nausea",
        "mareo",
        "mareado",
        "dolor lumbar",
        "dolor en la espalda",
        "ardor al orinar",
        "infeccion urinaria",
        "gastroenteritis",
        "bronquitis",
        "sinusitis",
        "otitis",
        "tos con flema",
        "dolor articular",
        "dolor muscular",
        "hinchazon",
    ]),
    (2, [
        "tos",
        "tos leve",
        "gripe",
        "resfriado",
        "malestar",
        "me siento mal",
        "no me siento bien",
        "chequeo",
        "control",
        "consulta",
        "congestion",
        "alergia",
        "estornudos",
        "cansancio",
        "fatiga",
        "debilidad",
        "dolor muscular",
        "dolor leve",
        "irritacion",
        "picazon",
        "dolor leve de estomago",
    ]),
]

INTENSITY_WORDS = [
    "intenso",
    "fuerte",
    "severo",
    "agudo",
    "muy",
    "durisimo",
    "fuertisimo",
    "insoportable",
]

HEART_PAIN_PATTERNS = [
    r"dolor\s+.*corazon",
    r"duele\s+.*corazon",
    r"corazon\s+.*duele",
    r"dolor\s+.*pecho",
    r"opresion\s+.*pecho",
    r"presion\s+.*pecho",
    r"pecho\s+.*apret",
]

EMERGENCY_PATTERNS = [
    r"paro\s+cardiac",
    r"paro\s+del\s+corazon",
    r"ataque\s+cardiac",
    r"ataque\s+al\s+corazon",
    r"me\s+va\s+a?\s+dar\s+un\s+paro",
    r"me\s+esta\s+dando\s+un\s+paro",
    r"me\s+va\s+a?\s+dar\s+un\s+infarto",
    r"no\s+puedo\s+respirar",
    r"no\s+respiro",
    r"me\s+ahogo",
    r"falta\s+de\s+aire\s+severa",
    r"cianosis",
    r"inconsciente",
    r"no\s+responde",
    r"sangrado\s+abundante",
    r"sangrado\s+imparable",
    r"hemorragia",
    r"vomito\s+con\s+sangre",
    r"heces\s+negras",
    r"convulsion",
    r"convulsiona",
    r"perdida\s+de\s+conocimiento",
    r"perdi\s+el\s+conocimiento",
    r"paralisis",
    r"no\s+puedo\s+mover",
    r"cara\s+caid",
    r"habla\s+rara",
    r"ictus",
    r"acv",
    r"fractura\s+expuesta",
    r"trauma\s+craneal",
    r"quemadura\s+grave",
    r"shock",
    r"choque",
    r"sepsis",
    r"anafilax",
    r"sobredosis",
    r"intoxicacion\s+severa",
    r"suicid",
    r"autolesion",
]

HIGH_URGENCY_PATTERNS = [
    r"dolor\s+.*pecho",
    r"duele\s+.*pecho",
    r"opresion\s+.*pecho",
    r"presion\s+.*pecho",
    r"dolor\s+.*corazon",
    r"duele\s+.*corazon",
    r"corazon\s+.*duele",
    r"dolor\s+.*brazo\s+izquierdo",
    r"dificultad\s+para\s+respirar",
    r"dolor\s+abdominal\s+intenso",
    r"dolor\s+abdominal\s+severo",
    r"dolor\s+de\s+cabeza\s+intenso",
    r"vision\s+borrosa",
    r"perdida\s+de\s+vision",
    r"fiebre\s+muy\s+alta",
    r"vomito\s+persistente",
    r"palpitaciones\s+fuertes",
    r"dolor\s+renal\s+intenso",
    r"dolor\s+testicular",
    r"dolor\s+pelvico\s+intenso",
    r"quemadura",
    r"fractura",
    r"presion\s+alta",
    r"mareo\s+intenso",
]

AMBIGUOUS_SYMPTOM_PATTERNS = [
    r"no\s+me\s+siento\s+bien",
    r"me\s+siento\s+mal",
    r"me\s+siento\s+raro",
    r"me\s+siento\s+extrano",
    r"me\s+pasa\s+algo",
    r"algo\s+raro",
    r"algo\s+mal",
    r"ayuda",
    r"ayudame",
    r"estoy\s+enfermo",
    r"estoy\s+enferma",
    r"me\s+siento\s+debil",
    r"mucho\s+cansancio",
    r"cansancio\s+extremo",
    r"fatiga\s+extrema",
]

BASE_COSTS = {
    "Cardiologia": 60.0,
    "Neurologia": 70.0,
    "Neumologia": 55.0,
    "Gastroenterologia": 45.0,
    "Hepatologia": 50.0,
    "Nefrologia": 60.0,
    "Urologia": 55.0,
    "Obstetricia": 55.0,
    "Ginecologia": 45.0,
    "Pediatria": 35.0,
    "Endocrinologia": 50.0,
    "Dermatologia": 40.0,
    "Reumatologia": 50.0,
    "Traumatologia": 55.0,
    "Otorrinolaringologia": 40.0,
    "Oftalmologia": 45.0,
    "Odontologia": 40.0,
    "Psiquiatria": 55.0,
    "Alergologia": 45.0,
    "Infectologia": 60.0,
    "Hematologia": 60.0,
    "Oncologia": 70.0,
    "Geriatria": 50.0,
    "Nutricion": 35.0,
    "Toxicologia": 60.0,
    "Medicina interna": 50.0,
    "Cirugia general": 65.0,
    "Medicina general": 30.0,
}

URGENCY_MULTIPLIER = {
    1: 1.0,
    2: 1.1,
    3: 1.25,
    4: 1.5,
    5: 2.0,
}

COVERAGE_BY_TIER = {
    "Oro": 0.8,
    "Plata": 0.6,
    "Bronce": 0.4,
}

HOSPITAL_INTENT_KEYWORDS = [
    "hospital",
    "clinica",
    "recomend",
    "seguro",
    "oro",
    "plata",
    "bronce",
    "diabet",
    "copago",
    "cobertura",
    "beneficio",
    "plan",
    "cuanto pago",
    "cuanto cuesta",
    "precio",
    "costo",
]


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return stripped.lower()


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _matches_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def extract_insurance_tier(normalized_text: str) -> str | None:
    for tier_key, tier_label in TIER_MAP.items():
        if _has_word(normalized_text, tier_key):
            return tier_label
    return None


def has_insurance(normalized_text: str) -> bool:
    return not any(phrase in normalized_text for phrase in NO_INSURANCE_PHRASES)


def estimate_specialty(normalized_text: str) -> str:
    latest_match: tuple[int, str] | None = None
    for specialty, keywords in SPECIALTY_RULES:
        for keyword in keywords:
            position = normalized_text.rfind(keyword)
            if position == -1:
                continue

            if latest_match is None or position > latest_match[0]:
                latest_match = (position, specialty)

    if latest_match is not None:
        return latest_match[1]

    return GENERAL_SPECIALTY


def estimate_urgency(normalized_text: str) -> int:
    if _matches_any_pattern(normalized_text, EMERGENCY_PATTERNS):
        urgency = 5
    else:
        for level, keywords in URGENCY_RULES:
            if any(keyword in normalized_text for keyword in keywords):
                urgency = level
                break
        else:
            urgency = 1

    if _matches_any_pattern(normalized_text, HEART_PAIN_PATTERNS):
        urgency = max(urgency, 4)

    if _matches_any_pattern(normalized_text, HIGH_URGENCY_PATTERNS):
        urgency = max(urgency, 4)

    if urgency == 1 and (
        "dolor" in normalized_text
        or "duele" in normalized_text
        or _matches_any_pattern(normalized_text, AMBIGUOUS_SYMPTOM_PATTERNS)
    ):
        urgency = 2

    if urgency < 5 and any(word in normalized_text for word in INTENSITY_WORDS):
        urgency += 1

    return min(urgency, 5)


def analyze_message(message: str) -> TriageResult:
    normalized = normalize_text(message)
    insurance_tier = extract_insurance_tier(normalized)
    insurance_available = has_insurance(normalized)
    specialty = estimate_specialty(normalized)
    urgency_level = estimate_urgency(normalized)
    return TriageResult(
        urgency_level=urgency_level,
        specialty=specialty,
        insurance_tier=insurance_tier,
        has_insurance=insurance_available,
    )


def estimate_cost(specialty: str, urgency_level: int, insurance_tier: str | None, insurance_available: bool) -> dict:
    base = BASE_COSTS.get(specialty, BASE_COSTS["Medicina general"])
    multiplier = URGENCY_MULTIPLIER.get(urgency_level, 1.0)
    base = round(max(base * multiplier, 15.0), 2)

    if not insurance_available:
        coverage_rate = 0.0
    else:
        coverage_rate = COVERAGE_BY_TIER.get(insurance_tier, 0.25)

    coverage = round(base * coverage_rate, 2)
    copay = round(max(base - coverage, 0.0), 2)

    return {
        "base": base,
        "coverage": coverage,
        "copay": copay,
    }


def normalize_cost_factor(value: float | int | None) -> float:
    if value is None:
        return 1.0

    try:
        factor = float(value)
    except (TypeError, ValueError):
        return 1.0

    if factor <= 0:
        return 1.0

    return factor


def estimate_cost_with_factor(
    specialty: str,
    urgency_level: int,
    insurance_tier: str | None,
    insurance_available: bool,
    cost_factor: float | int | None,
) -> dict:
    base_cost = estimate_cost(specialty, urgency_level, insurance_tier, insurance_available)
    factor = normalize_cost_factor(cost_factor)

    if factor == 1.0:
        return base_cost

    base = round(base_cost["base"] * factor, 2)
    coverage = round(base_cost["coverage"] * factor, 2)
    copay = round(max(base - coverage, 0.0), 2)

    return {
        "base": base,
        "coverage": coverage,
        "copay": copay,
    }


def should_suggest_hospitals(message: str, urgency_level: int) -> bool:
    normalized = normalize_text(message)
    if urgency_level >= 4:
        return True
    return any(keyword in normalized for keyword in HOSPITAL_INTENT_KEYWORDS)
