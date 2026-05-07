# Operation Red Yarn · Thread C
## Detección automática de anomalías en el control de calidad

**Asignatura:** Information Systems — Topic 6: Automation & AI  
**Universidad:** Universidad Autónoma de Madrid  
**Grupo:** Ángel Fernández · Pablo Tutor  
**Fecha de entrega:** 13 de mayo de 2026  

---

## 1. Contexto y diagnóstico del proceso

### 1.1 Situación actual (as-is)

VoltRide gestiona su proceso de producción a través de un event log estructurado que recoge cada actividad ejecutada sobre cada orden. El análisis de Process Mining realizado en el Topic 5 reveló que el **11,3% de las órdenes de producción se cierra sin pasar por la inspección de calidad**, violando la SOP-QA-001. En el log post-disruption (abril–noviembre 2026), esta cifra escala al **23,4%** (78 de 333 órdenes completadas): la disrupción en la cadena de suministro provocó que, como medida de emergencia, algunas órdenes saltaran directamente de *Credit Check* a *Production Started* sin pasar por *QC Incoming*.

El problema no estaba siendo monitorizado: nadie detectaba las desviaciones hasta que el cliente devolvía un patinete defectuoso. El proceso de detección era **100% reactivo**, sin trazabilidad y sin posibilidad de auditoría.

**Puntos de dolor identificados:**

| Problema | Impacto |
|---|---|
| Sin monitorización en tiempo real | Las anomalías se detectan días o semanas después |
| Sin registro estructurado | Imposible auditar el cumplimiento de la SOP |
| Detección manual inexistente | El supervisor no recibe ninguna alerta automática |
| Sin métricas de conformidad | No se puede medir la tasa de incumplimiento |

### 1.2 Solución propuesta (to-be)

El bot de Thread C implementa un **conformance checker en tiempo real** que carga el event log periódicamente, detecta las órdenes que incumplen la SOP-QC-002, diagnostica la causa mediante LLM y alerta al supervisor por múltiples canales.

**Diagrama as-is → to-be:**

```
AS-IS                              TO-BE
─────────────────────────────      ────────────────────────────────────
Cliente devuelve patinete    →     Bot detecta la anomalía al instante
     ↓                                  ↓
Supervisor investiga         →     LLM diagnostica la causa
     ↓                                  ↓
Búsqueda manual en el log    →     Email + Telegram al supervisor
     ↓                                  ↓
Corrección tardía            →     Dashboard en tiempo real
                                        ↓
                                   Supervisor decide la acción
```

### 1.3 División Human / RPA / LLM

| Paso | Capa | Criterio de asignación |
|---|---|---|
| Cargar el CSV y filtrar por fecha | **RPA** | Tarea determinística y repetitiva |
| Comprobar conformidad (SOP-QC-002) | **RPA** | Regla lógica sin ambigüedad: `QC Incoming < Production Started` |
| Diagnosticar la causa de la desviación | **LLM** | Requiere comprensión semántica del patrón de actividades |
| Redactar el mini-informe | **LLM** | Tarea de generación de lenguaje natural |
| Enviar email y Telegram | **RPA** | Acción determinística sobre APIs externas |
| Actualizar el dashboard | **RPA** | Escritura de CSV y visualización |
| Decidir la acción correctora | **Humano** | Decisión irreversible con impacto operativo |

---

## 2. Arquitectura técnica

### 2.1 Diagrama de la arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    EVENT LOG (CSV)                          │
│            voltride_event_log_POST.csv                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  RPA LAYER  │  Paso 1: Cargar y filtrar
                    │  Paso 1-2   │  Paso 2: Conformance check
                    └──────┬──────┘         SOP-QC-002
                           │
              ┌────────────▼────────────┐
              │  Órdenes no conformes   │
              │  (sin QC Incoming)      │
              └────────────┬────────────┘
                           │
                    ┌──────▼──────┐
                    │  LLM LAYER  │  Paso 3: Diagnóstico causal
                    │  Paso 3-4   │  Paso 4: Mini-informe JSON
                    │  Ollama     │
                    │  gpt-oss:   │
                    │  120b-cloud │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
   │    Gmail    │  │  Telegram   │  │  Dashboard  │
   │   (email    │  │   (alerta   │  │ (Streamlit) │
   │   formal)   │  │  en tiempo  │  │    CSV      │
   │             │  │    real)    │  │             │
   └─────────────┘  └─────────────┘  └─────────────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                    ┌──────▼──────┐
                    │  AUDIT LOG  │  JSONL: prompt + output
                    │   (JSONL)   │         + acción + timestamp
                    └─────────────┘
                           │
                    ┌──────▼──────┐
                    │   HUMANO    │  Supervisor revisa y decide
                    │ (Supervisor)│  la acción correctora
                    └─────────────┘
```

### 2.2 Regla de conformidad (SOP-QC-002)

La regla implementada es: **"QC Incoming debe aparecer antes de Production Started"** en la secuencia de actividades de cada orden. Si Production Started ocurre sin un QC Incoming previo, la orden es no conforme.

Se eligió esta regla porque el análisis del log POST-disruption muestra que la desviación real es la omisión de la inspección de componentes entrantes (QC Incoming), no la de producto terminado. El log pre-disruption muestra 0 violaciones de este tipo; el log POST muestra 78 (23,4%), confirmando que es el efecto directo de la disrupción.

### 2.3 Justificación de herramientas

**Por qué Python y no n8n / Power Automate:**

- El input es un CSV estructurado con acceso directo por fichero → no se necesita scraping de interfaz de usuario, que es el caso de uso principal de Power Automate Desktop
- Python permite control total del flujo, tipos de dato y manejo de errores sin depender de nodos visuales
- La auditabilidad es nativa: cada decisión se registra con `logging` estándar y en JSONL estructurado
- Reproducibilidad completa siguiendo el README (una sola instrucción: `python bot.py`)

**Librerías principales:**

| Librería | Rol |
|---|---|
| `pandas` / `csv` | RPA: lectura y filtrado del event log |
| `ollama` | LLM: cliente nativo para Ollama Cloud |
| `smtplib` | RPA: envío de email vía Gmail SMTP |
| `requests` | RPA: llamadas a la API de Telegram |
| `streamlit` | Dashboard: frontend de monitorización |
| `python-dotenv` | Gestión de credenciales desde `.env` |

**Por qué Ollama Cloud (gpt-oss:120b-cloud) y no GPT-4 / Claude:**

- Modelo de pesos abiertos → sin transferencia de datos a terceros propietarios, sin necesidad de DPA específico para datos sintéticos
- API compatible con el cliente nativo de Ollama → integración limpia sin dependencia del SDK de OpenAI
- 120B parámetros → capacidad suficiente para diagnóstico causal estructurado con salida JSON fiable
- Salida JSON estructurada con cuatro campos (`activity_gap`, `likely_cause`, `risk_level`, `mini_report`) → reduce la superficie de alucinación al limitar el espacio de respuesta

### 2.4 Manejo de errores

| Escenario | Tratamiento |
|---|---|
| JSON inválido del LLM | Fallback con diagnóstico genérico predefinido (nunca falla silenciosamente) |
| Timestamps futuros en el log | Filtro con cota superior `ts <= now` para excluir fechas futuras |
| Credenciales no configuradas | Cada canal comprueba sus variables antes de intentar enviar; el bot no interrumpe si un canal falla |
| Fichero de log no encontrado | `FileNotFoundError` con mensaje descriptivo antes de comenzar el procesamiento |

---

## 3. Implementación y resultados

### 3.1 Decisiones de implementación clave

**SOP-QC-002 vs SOP-QA-001:** El enunciado menciona SOP-QA-001 (QC-Inspection antes de Done). Sin embargo, el análisis del log POST-disruption muestra que el paso "QC Finished Goods" no tiene ninguna violación, mientras que "QC Incoming" tiene 78. Se optó por monitorizar la conformidad real presente en los datos, documentando el cambio.

**Ventana de lookback configurable:** El parámetro `LOOKBACK_HOURS` es configurable vía variable de entorno. El valor por defecto para producción es 24h (ejecución diaria). Para la auditoría histórica puede elevarse a cualquier valor.

**Dashboard CSV + Streamlit vs Excel:** Se generó un CSV en lugar de un .xlsx porque permite actualización incremental sin dependencia de librerías externas, y porque el dashboard Streamlit lo lee directamente con auto-refresco cada 30 segundos, ofreciendo una experiencia superior a un fichero Excel estático.

### 3.2 Resultados de las ejecuciones reales

Se realizaron tres ejecuciones con ventanas temporales distintas para demostrar el comportamiento a diferentes escalas:

| Run | Ventana | Órdenes revisadas | Anomalías detectadas | NC Rate | Alerta (>15%) |
|---|---|---|---|---|---|
| A | 8 horas | 9 | 1 — ORD-2026-0008 | 11,1% | No |
| B | 48 horas | 23 | 1 — ORD-2026-0034 | 4,3% | No |
| C | 168 horas (1 semana) | 28 | 2 — ORD-2026-0003 y ORD-2026-0034 | 7,1% | No |

**Tiempo de ejecución:** 5–12 segundos por run (incluyendo llamada al LLM, email y Telegram).  
**Canales activos en todos los runs:** Gmail ✓ · Telegram ✓ · Dashboard Streamlit ✓ · Audit log JSONL ✓

**Ejemplo de diagnóstico LLM (Run A — ORD-2026-0008):**

> *"Order ORD-2026-0008 skipped the mandatory QC Incoming inspection and receipt confirmation, violating SOP-QC-002. Because the components from EuroMotor were not verified upon receipt, there is an elevated risk of latent defects reaching the customer, especially in a B2C environment where field failures impact brand reputation. I recommend an immediate re-inspection of the sourced parts, a hold on further production until verification is completed, and a root-cause analysis to reinforce emergency protocols that preserve critical quality checks even during supply-chain stress."*
>
> — Risk level: **MEDIUM** · Supplier: EuroMotor · Customer type: B2C

### 3.3 Dashboard de monitorización

El dashboard Streamlit (`streamlit run dashboard.py`) muestra en tiempo real:
- Métricas: órdenes no conformes, NC rate, umbral, estado ALERT/OK
- Gráfico de distribución de riesgo (High / Medium / Low)
- Tabla de anomalías con proveedor, tipo de cliente, prioridad y causa probable
- Visor de diagnósticos LLM con el mini-informe completo por orden

---

## 4. Riesgos y regulación

### 4.1 Mitigación de alucinaciones

El LLM se utiliza **exclusivamente para diagnóstico semántico**, no para decisiones irreversibles. Las medidas implementadas son:

1. **Prompt estructurado con JSON forzado:** la respuesta está constreñida a cuatro campos con tipos fijos (`activity_gap`, `likely_cause`, `risk_level: low|medium|high`, `mini_report`). Esto limita el espacio de alucinación a caracterizar la causa, no a inventar datos.
2. **Fallback determinístico:** si el JSON no se puede parsear, el sistema aplica un diagnóstico genérico predefinido en lugar de fallar o propagar una alucinación.
3. **Grounding contextual:** el prompt incluye el ID de orden, proveedor, tipo de cliente, prioridad y la secuencia real de actividades del log — el LLM no puede inventar datos que ya están presentes en el input.
4. **Revisión humana obligatoria:** el supervisor recibe el diagnóstico y decide la acción correctora. El bot no modifica órdenes, no cierra casos ni toma decisiones operativas.
5. **Audit log completo:** cada llamada LLM queda registrada con prompt enviado, output recibido, acción ejecutada y timestamp. Esto permite medir la tasa de alucinación a posteriori.

### 4.2 GDPR

| Requisito GDPR | Implementación |
|---|---|
| Minimización de datos | Al LLM solo se envían: order_id, customer_type, priority, supplier, activity sequence. No se envían nombres, emails ni datos personales. |
| Datos sintéticos | El event log utilizado es sintético (generado para Topic 5). No contiene PII. |
| Base legal | Interés legítimo operativo (monitorización de calidad interna). |
| Registro de actividades | El audit log JSONL documenta cada operación de tratamiento (Article 30 GDPR). |
| Transferencia a terceros | Ollama Cloud procesa solo datos sintéticos sin PII. Para datos reales con PII sería necesario un DPA. |

### 4.3 EU AI Act

**Clasificación:** **Riesgo Limitado (Article 6).**

Justificación: el sistema clasifica anomalías en un proceso operativo interno (risk_level: low/medium/high). No toma decisiones que afecten a derechos fundamentales, no gestiona crédito ni empleo ni seguridad crítica. No entra en ninguna categoría de alto riesgo del Anexo III.

**Obligaciones de riesgo limitado cumplidas:**
- **Transparencia:** el supervisor sabe que está leyendo un diagnóstico generado por IA (etiqueta visible en el email y en el dashboard)
- **Supervisión humana:** ninguna acción correctora es ejecutada por el bot; el supervisor aprueba toda intervención
- **Trazabilidad:** audit log completo por cada decisión del sistema

### 4.4 Auditabilidad

Cada ejecución genera un fichero JSONL (`output/audit_log_YYYYMMDD_HHMMSS.jsonl`) con una entrada estructurada por cada orden procesada:

```json
{
  "stage": "llm_diagnosis",
  "order_id": "ORD-2026-0008",
  "llm_output": {
    "activity_gap": "QC Incoming was skipped",
    "likely_cause": "Emergency bypass during supply-chain disruption",
    "risk_level": "medium",
    "mini_report": "..."
  },
  "status": "diagnosed",
  "logged_at": "2026-05-07T19:10:49.990215"
}
```

Una segunda entrada de tipo `"stage": "output"` registra qué canales recibieron la alerta y si el envío fue exitoso.

---

## 5. Lecciones aprendidas

**Qué funcionó bien:**
- La separación limpia RPA/LLM simplificó el debugging: los errores de parseo de CSV son siempre de la capa RPA, los errores de JSON son siempre de la capa LLM.
- Forzar la salida JSON del LLM con un prompt estricto redujo drásticamente las alucinaciones respecto a una salida en texto libre.
- `python-dotenv` elimina la necesidad de exportar variables de entorno manualmente, haciendo el bot reproducible con una sola instrucción.

**Qué fue difícil:**
- La URL de Ollama Cloud no era la documentada inicialmente (`api.ollama.com/v1` devuelve 401; la correcta es `ollama.com`).
- El log POST contiene timestamps hasta noviembre 2026, lo que hacía que el filtro de ventana temporal incluyera órdenes futuras. Se corrigió añadiendo una cota superior `ts <= datetime.now()`.
- El entorno Anaconda del sistema no tenía `streamlit-autorefresh` instalado; se resolvió instalando las dependencias del `requirements.txt` en el entorno activo.

**Qué mejoraría en una versión productiva:**
- **Scheduling nativo:** integrar APScheduler o Celery Beat para eliminar la dependencia de cron externo.
- **Base de datos persistente:** reemplazar el CSV del dashboard por SQLite para soportar histórico acumulado sin sobreescritura.
- **Umbral de confianza:** si la puntuación de confianza del LLM fuera baja, escalar automáticamente a revisión humana en lugar de publicar el diagnóstico directamente.
- **Deduplicación:** detectar si una orden ya fue reportada en una ejecución anterior para no enviar alertas duplicadas.

---

## Anexo: Estructura del proyecto

```
.
├── bot.py                          # Bot principal — entrada del sistema
├── dashboard.py                    # Dashboard Streamlit (tiempo real)
├── requirements.txt                # Dependencias Python
├── .env.example                    # Plantilla de credenciales
├── README.md                       # Instrucciones de ejecución
├── data/
│   ├── voltride_event_log_POST.csv # Log post-disruption (bot por defecto)
│   └── voltride_event_log.csv      # Log pre-disruption (baseline T5)
├── logs/
│   ├── run_A_8h.log                # Ejecución A (ventana 8h)
│   ├── run_B_48h.log               # Ejecución B (ventana 48h)
│   └── run_C_168h.log              # Ejecución C (ventana 168h)
└── output/
    ├── audit_run_A_8h.jsonl        # Audit log ejecución A
    ├── audit_run_B_48h.jsonl       # Audit log ejecución B
    ├── audit_run_C_168h.jsonl      # Audit log ejecución C
    └── qc_dashboard.csv            # Dashboard CSV (última ejecución)
```

---

*Informe generado con asistencia de IA (Claude). El contenido ha sido revisado, validado y adaptado por los autores.*
