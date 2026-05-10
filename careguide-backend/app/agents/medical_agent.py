import os
from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.groq import Groq

load_dotenv()


def _log(message: str) -> None:
    print(message.encode("ascii", errors="replace").decode("ascii"))


# --- NUEVAS HERRAMIENTAS PARA LA IA (TOOL CALLING) ---
def calcular_imc(peso_kg: float, altura_m: float) -> str:
    """Calcula el Índice de Masa Corporal (IMC) de un paciente.
    Args:
        peso_kg: El peso del paciente en kilogramos.
        altura_m: La altura del paciente en metros (ej. 1.75).
    """
    _log(f"[TOOL CALLING] Calculating BMI for peso={peso_kg}kg, altura={altura_m}m")
    try:
        imc = peso_kg / (altura_m ** 2)
        if imc < 18.5:
            estado = "Bajo peso"
        elif 18.5 <= imc < 25.0:
            estado = "Peso normal"
        elif 25.0 <= imc < 30.0:
            estado = "Sobrepeso"
        else:
            estado = "Obesidad"
        return f"El IMC exacto calculado es {imc:.2f} (Estado: {estado})."
    except Exception:
        return "Error al calcular el IMC, datos inválidos."

# Agente principal de CareGuide.
careguide_ai = Agent(
    model=Groq(id="llama-3.3-70b-versatile"),
    description="Asistente médico experto y asesor de triage en la red de salud de Manta, Ecuador.",
    tools=[calcular_imc],
    instructions=[
        "Eres CareGuide AI, un asistente de salud empático y directo.",
        "REGLA 1: Usa el contexto interno provisto (urgencia, especialidad) para guiar tu respuesta. Nunca menciones que estás leyendo un contexto interno.",
        "REGLA 2: Si el contexto indica EMERGENCIA (nivel 4 o 5), prioriza la vida. Indica que busquen ayuda médica de inmediato (911 o emergencias) y NO hables de precios ni de seguros.",
        "REGLA 3: Si es una consulta de RUTINA (niveles 1, 2, 3), sé empático, da consejos preventivos ligeros y usa el contexto para mencionar la especialidad correcta.",
        "REGLA 4: No inventes nombres de hospitales ni calcules precios por tu cuenta, el sistema ya se encarga de inyectar esa información si es pertinente.",
        "REGLA 5: Si el usuario menciona su peso y altura, llama a la herramienta 'calcular_imc' obligatoriamente y explícale el resultado de forma amable, mencionando siempre el número exacto de su IMC.",
        "REGLA 6: No repitas frases ni párrafos. Si algo ya fue dicho, resume en una sola vez.",
        "Responde siempre en espanol de forma breve y clara.",
        "Responde sin Markdown, sin numerales (#) ni asteriscos (*).",
    ],
    markdown=False,
)
# --- ESTO ES LO QUE FALTA PARA QUE SALGA ALGO EN LA TERMINAL ---
if __name__ == "__main__":
    _log("CareGuide AI starting...")
    
    _log("--- TOOL CALLING TEST (BMI calculation) ---")
    careguide_ai.print_response("Hola, peso 85 kilos y mido 1.75 metros. ¿Me puedes decir mi estado de salud?", stream=True)
