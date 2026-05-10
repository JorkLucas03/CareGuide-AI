# CareGuide AI - Estimador Agéntico de Copago y Cobertura

## Introducción
Antes de completar el registro al HackIAthon, se propusieron 5 retos reales para medir análisis, criterio técnico y ejecución con herramientas de IA. Elegimos el **Reto 3** y construimos una solución funcional enfocada en pacientes reales de Manta, Ecuador.

**Entregables solicitados:**
- Enlace público del agente funcional.
- Enlace del repositorio en GitHub/GitLab.

## Reto 3: Estimador Agéntico de Copago y Cobertura para el Paciente
Un agente conversacional que ayuda al paciente a entender su beneficio antes de atenderse. El usuario ingresa sus síntomas, el agente sugiere la especialidad y, cruzando datos con su plan, indica el copago estimado y el hospital más conveniente en su red.

---

## Lo que hace este proyecto
- Triage médico por síntomas (urgencia + especialidad).
- Estimación de copago con base en cobertura del plan.
- Recomendación de hospitales filtrados por red (Oro/Plata/Bronce/Sin seguro).
- Respuesta conversacional clara y empática.

---

## Stack
- **Backend:** FastAPI (Python 3.12)
- **Frontend:** Next.js (React)
- **IA:** Groq (Llama 3.3 70B) + Agno
- **BD:** Supabase (PostgreSQL)

---

## Estructura del repo
```
careguide-backend/   # FastAPI + Agente + lógica de copagos
frontend/            # Next.js UI
README.md
```

---

## Variables de entorno
### Backend (.env en careguide-backend/)
```
SUPABASE_URL=...
SUPABASE_KEY=...
GROQ_API_KEY=...
SAVE_RECOMMENDATIONS=true
DEBUG_TRIAGE=false
DEBUG_SUPABASE=false
```

### Frontend (opcional .env.local en frontend/)
```
BACKEND_URL=http://localhost:8000
```

Tambien se incluyen archivos `.env.example` en `careguide-backend/` y `frontend/`.
No subas claves reales al repositorio.

> `GROQ_API_KEY` es obligatoria para que el agente responda con IA. Sin esa clave el backend sigue levantando y calcula triage/copago/hospitales, pero la respuesta conversacional queda en modo fallback.

---

## Ejecutar local
### Backend
```
cd careguide-backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```
cd frontend
npm install
npm run dev
```

---

## Endpoints principales
- `GET /` -> estado del backend
- `GET /api/hospitales` -> lista de hospitales
- `POST /chat` -> responde al usuario con triage + copago + hospitales

---

## Base de datos (Supabase)
Tablas clave utilizadas:
- `hospitals` (hospitales y tiers aceptados)
- `insurance_policies` (planes y proveedores)
- `specialties` (especialidades y costos base)
- `coverages` (cobertura por plan y especialidad)
- `hospital_insurance_contracts` (descuentos por red)

---

## Despliegue (recomendado)
**Backend en Render + Frontend en Vercel**

### Backend (Render)
- Root: `careguide-backend`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Variables de entorno: `SUPABASE_URL`, `SUPABASE_KEY`, `GROQ_API_KEY`

### Frontend (Vercel)
- Root: `frontend`
- Variable: `BACKEND_URL=https://<tu-backend>.onrender.com`

---

## Enlaces (completar al publicar)
- Agente funcional: [link público]
- Repositorio: [link del repo]

---

## Equipo
- Club de Inteligencia Artificial - ULEAM
- HackIAthon Manta
