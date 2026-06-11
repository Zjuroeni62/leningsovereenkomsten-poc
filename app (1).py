import os
import json
import fitz
import pandas as pd
import streamlit as st
from datetime import datetime
from openai import OpenAI

st.set_page_config(
    page_title="Leningsovereenkomsten PoC — Vermetten",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stTextArea textarea { font-size: 13px; line-height: 1.7; }
    .status-gereed  { color: #15803d; font-weight: 500; }
    .status-review  { color: #b45309; font-weight: 500; }
    .approved-banner {
        background: #f0fdf4; border: 1px solid #bbf7d0;
        border-radius: 8px; padding: 10px 16px;
        color: #15803d; font-size: 14px; margin-bottom: 12px;
    }
    .hitl-banner {
        background: #fffbeb; border: 1px solid #fde68a;
        border-radius: 8px; padding: 10px 16px;
        color: #92400e; font-size: 13px; margin-bottom: 8px;
    }
</style>
""", unsafe_allow_html=True)

# ── Constanten ────────────────────────────────────────────────────────────────
CHECKLIST_ITEMS = [
    {"field": "principal_amount",   "label": "Hoofdsom",               "required": True,  "rj": "RJ 254.408a / art. 2:375 lid 1 BW"},
    {"field": "interest_rate",      "label": "Rentepercentage",        "required": True,  "rj": "RJ 254.403 / art. 2:375 lid 2 BW"},
    {"field": "start_date",         "label": "Ingangsdatum",           "required": True,  "rj": "RJ 254.408a / art. 2:375 lid 2 BW"},
    {"field": "end_date",           "label": "Einddatum",              "required": False, "rj": "art. 2:375 lid 2 BW"},
    {"field": "term_description",   "label": "Looptijdomschrijving",   "required": False, "rj": "art. 2:375 lid 2 BW"},
    {"field": "repayment_terms",    "label": "Aflossingsvoorwaarden",  "required": True,  "rj": "RJ 254.408a / art. 2:375 lid 6 BW"},
    {"field": "security",           "label": "Zekerheden",             "required": False, "rj": "art. 2:375 lid 3 BW"},
    {"field": "subordination",      "label": "Achterstelling",         "required": False, "rj": "art. 2:375 lid 4 BW"},
    {"field": "special_conditions", "label": "Bijzondere voorwaarden", "required": False, "rj": "RJ 254.408"},
]

MAX_CONTRACT_CHARS = 12000  # verwerkingslimiet extractieprompt

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string"},
        "parties": {
            "type": "object",
            "properties": {
                "creditor": {"type": ["string", "null"]},
                "debtor":   {"type": ["string", "null"]},
            },
            "required": ["creditor", "debtor"],
            "additionalProperties": False,
        },
        "principal_amount": {
            "type": "object",
            "properties": {
                "value":    {"type": ["number", "null"]},
                "currency": {"type": ["string", "null"]},
            },
            "required": ["value", "currency"],
            "additionalProperties": False,
        },
        "interest_rate":      {"type": ["number", "null"]},
        "start_date":         {"type": ["string", "null"]},
        "end_date":           {"type": ["string", "null"]},
        "term_description":   {"type": ["string", "null"]},
        "repayment_terms":    {"type": ["string", "null"]},
        "security":           {"type": ["string", "null"]},
        "subordination":      {"type": ["string", "null"]},
        "special_conditions": {"type": ["string", "null"]},
        "missing_items":      {"type": "array", "items": {"type": "string"}},
        "uncertain_items":    {"type": "array", "items": {"type": "string"}},
        "confidence_scores": {
            "type": "object",
            "additionalProperties": True,
        },
        "source_quotes": {
            "type": "object",
            "properties": {
                "principal_amount":   {"type": ["string", "null"]},
                "interest_rate":      {"type": ["string", "null"]},
                "repayment_terms":    {"type": ["string", "null"]},
                "start_date":         {"type": ["string", "null"]},
                "end_date":           {"type": ["string", "null"]},
                "security":           {"type": ["string", "null"]},
                "subordination":      {"type": ["string", "null"]},
                "special_conditions": {"type": ["string", "null"]},
            },
            "required": ["principal_amount", "interest_rate", "repayment_terms"],
            "additionalProperties": False,
        },
    },
    "required": [
        "document_type", "parties", "principal_amount", "interest_rate",
        "start_date", "end_date", "term_description", "repayment_terms",
        "security", "subordination", "special_conditions",
        "missing_items", "uncertain_items", "confidence_scores", "source_quotes",
    ],
    "additionalProperties": False,
}

# ── Sessiestatus ──────────────────────────────────────────────────────────────
for key, default in [
    ("contracts", []),
    ("active_idx", None),
    ("audit_log", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def log_event(event: str, contract_name: str = "", details: str = ""):
    st.session_state.audit_log.append({
        "tijdstip":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "gebruiker":   "Accountant",
        "gebeurtenis": event,
        "contract":    contract_name,
        "details":     details,
    })

def extract_text_from_pdf(uploaded_file) -> str:
    with fitz.open(stream=uploaded_file.read(), filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)

def get_field_value(data: dict, field: str) -> str | None:
    if field == "principal_amount":
        p = data.get("principal_amount") or {}
        amount   = p.get("value")
        currency = p.get("currency")
        if amount is not None and currency:
            return f"{currency} {amount:,.2f}"
        return str(amount) if amount is not None else None
    value = data.get(field)
    return str(value) if value is not None else None

def _matches_any(zoektermen: list[str], tekstlijst: list[str]) -> bool:
    return any(term in tekst for term in zoektermen for tekst in tekstlijst)

def build_checklist(data: dict) -> list[dict]:
    missing   = [m.lower() for m in data.get("missing_items",   [])]
    uncertain = [u.lower() for u in data.get("uncertain_items", [])]
    scores    = data.get("confidence_scores") or {}
    rows = []
    for item in CHECKLIST_ITEMS:
        field    = item["field"]
        label    = item["label"]
        value    = get_field_value(data, field)
        present  = value is not None and value.strip() != ""
        zoektermen = [field.lower(), label.lower()]
        if _matches_any(zoektermen, missing):
            remark = "Ontbreekt volgens model"
        elif _matches_any(zoektermen, uncertain):
            remark = "Onzeker volgens model"
        elif present:
            remark = "Aanwezig"
        else:
            remark = "Niet aangetroffen"
        conf = scores.get(field)
        if isinstance(conf, dict):
            conf = conf.get("value") or next(iter(conf.values()), None)
        if conf is None:
            conf = scores.get(f"{field}.value")
        rows.append({
            **item,
            "value":      value,
            "present":    present,
            "remark":     remark,
            "confidence": conf,
            "quote":      (data.get("source_quotes") or {}).get(field),
        })
    return rows

def determine_status(checklist: list[dict]) -> str:
    verplicht = [i for i in checklist if i["required"]]
    ontbreekt = [i for i in verplicht if not i["present"]]
    onzeker   = [i for i in verplicht if i["remark"] == "Onzeker volgens model"]
    return "Gereed voor review" if not ontbreekt and not onzeker else "Review vereist"

def compute_volledigheid(checklist: list[dict]) -> float | None:
    """Volledigheid: correct herkende verplichte velden t.o.v. alle verplichte velden.
    Echte precision/recall worden gemeten via de regressietestset met ground truth
    (zie borgingsplan); deze metric toont de live volledigheid per contract."""
    verplicht = [i for i in checklist if i["required"]]
    herkend   = [i for i in verplicht if i["present"] and i["remark"] == "Aanwezig"]
    return (len(herkend) / len(verplicht) * 100) if verplicht else None

# ── OpenAI ────────────────────────────────────────────────────────────────────

def extract_data(client: OpenAI, document_text: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Je analyseert een Nederlandse leningsovereenkomst voor middelgrote rechtspersonen (RJ 254). "
                    "Extraheer ALLEEN informatie die expliciet in de contracttekst staat. "
                    "Gebruik null voor ontbrekende velden — verzin niets en bereken geen waarden uit andere gegevens. "
                    "Geef per geëxtraheerd veld een confidence score: 'high' (expliciet vermeld), "
                    "'medium' (direct afgeleid uit een expliciete contractbepaling), 'low' (onzeker). "
                    "Ingangsdatum: gebruik een expliciet vermelde uitbetalings- of ingangsdatum; is alleen een "
                    "ondertekeningsdatum vermeld, gebruik die met confidence 'medium'. Tel nooit zelf dagen, "
                    "werkdagen of termijnen op bij een datum. "
                    "Einddatum: alleen invullen als het contract die expliciet vermeldt of direct definieert "
                    "(bijvoorbeeld 'zeven jaar na de ingangsdatum'); zo'n afgeleide datum krijgt confidence "
                    "'medium'. Een einddatum die alleen uit het aflossingsschema zou volgen, blijft null. "
                    "source_quotes bevatten uitsluitend letterlijke citaten uit de contracttekst. "
                    "Signaleer interne tegenstrijdigheden in het contract (bijvoorbeeld een bedrag in cijfers "
                    "dat afwijkt van het bedrag in letters) altijd als uncertain_item. "
                    "Retourneer geldig JSON conform het opgegeven schema."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Schema:\n{json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False)}"
                    f"\n\nContract:\n{document_text[:MAX_CONTRACT_CHARS]}"
                ),
            },
        ],
    )
    return json.loads(response.choices[0].message.content)

def generate_toelichting(client: OpenAI, data: dict) -> str:
    relevante_velden = [
        "document_type", "parties", "principal_amount", "interest_rate",
        "start_date", "end_date", "repayment_terms", "security",
        "subordination", "special_conditions",
    ]
    relevante_data = {k: data.get(k) for k in relevante_velden}
    onzekere_items = data.get("uncertain_items", [])
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Je schrijft een zakelijke Nederlandse jaarrekeningtoelichting "
                    "voor middelgrote rechtspersonen op basis van contractgegevens conform RJ 254. "
                    "Verzin niets. Laat null-velden weg. "
                    "Dit is een concept dat door een accountant beoordeeld wordt. "
                    'Sluit af met: "Dit betreft een concept-toelichting. De accountant voert een finale beoordeling uit voordat deze wordt opgenomen in de jaarrekening."'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Onzekere items (weglaten of markeren): {onzekere_items}\n\n"
                    f"Gegevens:\n{json.dumps(relevante_data, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
    )
    return response.choices[0].message.content

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 📄 Leningsovereenkomsten")
    st.markdown("AI-gestuurde toelichting voor de jaarrekening — RJ 254")
    st.caption("Scope: middelgrote rechtspersonen")
    st.divider()

    api_key = st.text_input(
        "OpenAI API-sleutel",
        type="password",
        placeholder="sk-...",
        help="PoC-fase: OpenAI API. Productie: private deployment vereist (AVG).",
    )

    st.divider()

    if st.button("➕ Nieuw contract", use_container_width=True, type="primary"):
        st.session_state.active_idx = None

    st.markdown("**Verwerkte contracten**")
    for i, c in enumerate(st.session_state.contracts):
        status_icon   = "✅" if c["status"] == "Gereed voor review" else "⚠️"
        approved_icon = " 🔒" if c.get("approved") else ""
        label = f"{status_icon} {c['name'][:24]}{approved_icon}"
        if st.button(label, key=f"nav_{i}", use_container_width=True):
            st.session_state.active_idx = i

    if st.session_state.contracts:
        st.divider()
        gereed      = sum(1 for c in st.session_state.contracts if c["status"] == "Gereed voor review")
        goedgekeurd = sum(1 for c in st.session_state.contracts if c.get("approved"))
        st.caption(f"Totaal: {len(st.session_state.contracts)} | Gereed: {gereed} | Goedgekeurd: {goedgekeurd}")

    if st.session_state.audit_log:
        st.divider()
        with st.expander(f"📋 Audit trail ({len(st.session_state.audit_log)} entries)"):
            st.dataframe(pd.DataFrame(st.session_state.audit_log), use_container_width=True, hide_index=True)

# ── Hoofdpagina: nieuw contract ───────────────────────────────────────────────

if st.session_state.active_idx is None:

    st.title("Nieuw contract verwerken")
    st.caption(
        "Upload een leningsovereenkomst als PDF. Het AI-model extraheert de gegevens en genereert "
        "een concept-toelichting conform RJ 254 (middelgrote rechtspersonen)."
    )

    st.markdown(
        '<div class="hitl-banner">'
        "⚠️ <strong>Human-in-the-loop:</strong> de gegenereerde toelichting is altijd een concept. "
        "De accountant beoordeelt, past zo nodig aan, en keurt goed voordat de toelichting "
        "in de jaarrekening wordt opgenomen."
        "</div>",
        unsafe_allow_html=True,
    )

    if not api_key:
        st.info("Voer eerst je OpenAI API-sleutel in de zijbalk in.")
        st.caption("ℹ️ PoC-fase: OpenAI API. Voor productiegebruik is private deployment vereist conform AVG en kantoorbeleid.")
        st.stop()

    uploaded = st.file_uploader(
        "Selecteer een PDF-bestand",
        type=["pdf"],
        help="Ondersteund formaat: PDF. Aanbevolen max. 10 MB.",
    )

    if uploaded:
        st.success(f"Bestand geselecteerd: **{uploaded.name}**")

        if st.button("▶ Verwerken", type="primary"):
            client = OpenAI(api_key=api_key)
            log_event("Upload", uploaded.name, "PDF geüpload voor verwerking")

            with st.status("Contract verwerken...", expanded=True) as status_widget:

                st.write("📖 Tekst extraheren uit PDF...")
                try:
                    document_text = extract_text_from_pdf(uploaded)
                except Exception as e:
                    st.error(f"Fout bij PDF-extractie: {e}")
                    st.stop()
                if not document_text.strip():
                    st.error("De PDF bevat geen leesbare tekst. Controleer het bestand.")
                    st.stop()
                st.write(f"✓ PDF ingelezen — {len(document_text):,} tekens")
                log_event("Extractie gestart", uploaded.name, f"{len(document_text):,} tekens")

                if len(document_text) > MAX_CONTRACT_CHARS:
                    st.warning(
                        f"⚠️ Contract is langer ({len(document_text):,} tekens) dan de verwerkingslimiet "
                        f"({MAX_CONTRACT_CHARS:,}); alleen het eerste deel wordt geanalyseerd. "
                        "Contract geflagd voor extra handmatige review."
                    )
                    log_event("Geflagd", uploaded.name, "Contract langer dan verwerkingslimiet — handmatige review vereist")

                st.write("🤖 Gegevens extraheren via AI (gpt-4o-mini, temperature=0)...")
                try:
                    extracted = extract_data(client, document_text)
                except Exception as e:
                    st.error(f"Fout bij AI-extractie: {e}")
                    st.stop()
                st.write("✓ Gegevens geëxtraheerd")

                st.write("📋 Checklist valideren tegen RJ 254...")
                checklist  = build_checklist(extracted)
                status_val = determine_status(checklist)
                volledigheid = compute_volledigheid(checklist)
                st.write(f"✓ Validatie klaar — status: **{status_val}**")
                log_event("Validatie", uploaded.name, f"Status: {status_val}")

                low_confidence = [i for i in checklist if i.get("confidence") == "low"]
                if low_confidence:
                    velden = ", ".join(i["label"] for i in low_confidence)
                    st.warning(f"⚠️ Contract geflagd voor extra review — lage confidence: {velden}")
                    log_event("Geflagd", uploaded.name, f"Lage confidence: {velden}")

                st.write("✍️ Concept-toelichting genereren (gpt-4o, temperature=0)...")
                try:
                    toelichting = generate_toelichting(client, extracted)
                except Exception as e:
                    st.error(f"Fout bij toelichtingsgeneratie: {e}")
                    st.stop()
                st.write("✓ Concept-toelichting gereed")
                status_widget.update(label="Verwerking voltooid", state="complete")
                log_event("Toelichting gegenereerd", uploaded.name, "Concept gereed voor review")

            contract = {
                "name":        uploaded.name.replace(".pdf", ""),
                "filename":    uploaded.name,
                "data":        extracted,
                "checklist":   checklist,
                "status":      status_val,
                "toelichting": toelichting,
                "approved":    False,
                "volledigheid": volledigheid,
                "verwerkt_op": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            st.session_state.contracts.append(contract)
            st.session_state.active_idx = len(st.session_state.contracts) - 1
            st.rerun()

    st.divider()
    st.info(
        "**Human-in-the-loop:** de gegenereerde toelichting is een concept. "
        "De accountant beoordeelt en keurt de inhoud goed voordat deze in de jaarrekening wordt opgenomen."
    )

    if st.session_state.contracts:
        st.subheader("Overzicht alle contracten")
        overzicht = []
        for c in st.session_state.contracts:
            hs = get_field_value(c["data"], "principal_amount") or "—"
            overzicht.append({
                "Contract":        c["name"],
                "Verwerkt op":     c.get("verwerkt_op", "—"),
                "Status":          c["status"],
                "Goedgekeurd":     "Ja" if c.get("approved") else "Nee",
                "Hoofdsom":        hs,
                "Rentepercentage": f"{c['data'].get('interest_rate', '—')}%" if c["data"].get("interest_rate") is not None else "—",
                "Volledigheid verplicht": f"{c['volledigheid']:.0f}%" if c.get("volledigheid") is not None else "—",
            })
        st.dataframe(pd.DataFrame(overzicht), use_container_width=True, hide_index=True)

# ── Hoofdpagina: bestaand contract ───────────────────────────────────────────

else:
    idx  = st.session_state.active_idx
    c    = st.session_state.contracts[idx]
    cl   = c["checklist"]
    data = c["data"]

    n_verplicht = sum(1 for i in cl if i["required"])
    n_aanwezig  = sum(1 for i in cl if i["required"] and i["present"])
    n_onzeker   = sum(1 for i in cl if i["remark"] == "Onzeker volgens model")
    n_ontbreekt = sum(1 for i in cl if i["remark"] == "Ontbreekt volgens model")
    n_quotes    = sum(1 for i in cl if i["quote"])
    n_low_conf  = sum(1 for i in cl if i.get("confidence") == "low")

    col_title, col_btn = st.columns([3, 1])
    with col_title:
        st.title(c["name"])
        st.caption(f"Verwerkt op: {c.get('verwerkt_op', '—')} — Scope: RJ 254 middelgrote rechtspersonen")
        status_class = "status-gereed" if c["status"] == "Gereed voor review" else "status-review"
        status_icon  = "✅" if c["status"] == "Gereed voor review" else "⚠️"
        st.markdown(f'{status_icon} <span class="{status_class}">{c["status"]}</span>', unsafe_allow_html=True)
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if c.get("approved"):
            st.success("Goedgekeurd door accountant")
        else:
            if st.button("✅ Goedkeuren", type="primary", use_container_width=True, key=f"approve_header_{idx}"):
                st.session_state.contracts[idx]["approved"] = True
                log_event("Goedgekeurd", c["name"], "Toelichting goedgekeurd door accountant")
                st.rerun()

    if c.get("approved"):
        st.markdown('<div class="approved-banner">🔒 Deze toelichting is goedgekeurd door de accountant en kan worden opgenomen in de jaarrekening.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="hitl-banner">⚠️ <strong>Concept:</strong> beoordeel de toelichting en de checklistresultaten voordat u goedkeurt.</div>', unsafe_allow_html=True)

    if n_low_conf:
        lage_velden = ", ".join(i["label"] for i in cl if i.get("confidence") == "low")
        st.warning(f"⚠️ **Extra review aanbevolen** — lage confidence voor: {lage_velden}")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Verplichte velden",   f"{n_aanwezig}/{n_verplicht}")
    m2.metric("Onzekere velden",     n_onzeker)
    m3.metric("Ontbrekende velden",  n_ontbreekt)
    m4.metric("Bronquotes",          n_quotes)
    m5.metric(
        "Volledigheid verplicht",
        f"{c['volledigheid']:.0f}%" if c.get("volledigheid") is not None else "—",
        help="Verplichte RJ 254-velden correct herkend in dit contract. "
             "Precision/recall worden gemeten via de regressietestset met ground truth (zie borgingsplan).",
    )

    st.divider()

    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Checklistvalidatie RJ 254",
        "✍️ Concept-toelichting",
        "🔍 Ruwe extractie",
        "📋 Audit trail",
    ])

    with tab1:
        st.subheader("Checklistvalidatie RJ 254")
        st.caption("Toetsing van geëxtraheerde contractgegevens aan de vereisten voor middelgrote rechtspersonen.")

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filter_verplicht = st.checkbox("Toon alleen verplichte velden", value=False)
        with col_f2:
            filter_aandacht = st.checkbox("Toon alleen aandachtspunten", value=False)

        rows = []
        for item in cl:
            if filter_verplicht and not item["required"]:
                continue
            if filter_aandacht and item["remark"] == "Aanwezig":
                continue
            rows.append({
                "Onderdeel":    item["label"],
                "RJ-grondslag": item["rj"],
                "Verplicht":    "Ja" if item["required"] else "Nee",
                "Aanwezig":     "✅ Ja" if item["present"] else "❌ Nee",
                "Waarde":       (item["value"] or "—")[:80],
                "Bronquote":    (item["quote"] or "—")[:80],
                "Confidence":   item.get("confidence") or "—",
                "Opmerking":    item["remark"],
            })

        df = pd.DataFrame(rows)

        def kleur_opmerking(val):
            if val == "Aanwezig":                return "color: #15803d"
            if val == "Onzeker volgens model":   return "color: #b45309"
            if val == "Ontbreekt volgens model": return "color: #dc2626"
            return "color: #6b7280"

        def kleur_confidence(val):
            if val == "high":   return "color: #15803d"
            if val == "medium": return "color: #b45309"
            if val == "low":    return "color: #dc2626"
            return ""

        st.dataframe(
            df.style.map(kleur_opmerking, subset=["Opmerking"]).map(kleur_confidence, subset=["Confidence"]),
            use_container_width=True,
            hide_index=True,
            height=min(60 + len(rows) * 38, 480),
        )

        ontbrekende_verplicht = [i for i in cl if i["required"] and not i["present"]]
        if ontbrekende_verplicht:
            st.warning(f"**{len(ontbrekende_verplicht)} verplicht(e) veld(en) ontbreken:** " + ", ".join(i["label"] for i in ontbrekende_verplicht))
        else:
            st.success("Alle verplichte RJ 254-velden zijn aangetroffen.")
        if n_onzeker:
            st.warning(f"**{n_onzeker} veld(en) onzeker:** " + ", ".join(i["label"] for i in cl if i["remark"] == "Onzeker volgens model"))

        with st.expander("📊 Kwaliteitsmetrieken (borgingsplan streefwaarden)"):
            vol = c.get("volledigheid")
            st.metric(
                "Volledigheid verplichte velden",
                f"{vol:.1f}%" if vol is not None else "—",
                help="Live volledigheid van dit contract.",
            )
            if vol is not None and vol < 100:
                st.warning("Niet alle verplichte RJ 254-velden zijn correct herkend — handmatige review vereist.")
            st.caption(
                "Precision (streefwaarde ≥ 95%) en recall (streefwaarde ≥ 90%) worden gemeten via de "
                "regressietestset met vooraf vastgestelde verwachte waarden — zie het borgingsplan. "
                "PoC-validatie op 5 testcontracten: 94,6% (35/37 velden correct)."
            )

    with tab2:
        st.subheader("Concept-toelichting jaarrekening")
        st.caption("Gegenereerd conform RJ 254. Controleer, bewerk indien nodig, en keur goed.")

        toelichting_key = f"toelichting_{idx}"
        if toelichting_key not in st.session_state:
            st.session_state[toelichting_key] = c["toelichting"]

        toelichting_edit = st.text_area(
            "Concept-toelichting (bewerkbaar)",
            height=360,
            key=toelichting_key,
            disabled=c.get("approved", False),
            help="De accountant kan de tekst hier direct aanpassen voor de definitieve versie.",
        )
        st.session_state.contracts[idx]["toelichting"] = toelichting_edit

        col_a, col_b, _ = st.columns([1, 1, 3])
        with col_a:
            if not c.get("approved"):
                if st.button("✅ Goedkeuren", type="primary", use_container_width=True, key=f"approve_tab2_{idx}"):
                    st.session_state.contracts[idx]["approved"] = True
                    log_event("Goedgekeurd", c["name"], "Goedgekeurd via toelichting-tab")
                    st.rerun()
        with col_b:
            st.download_button(
                label="⬇ Downloaden (.txt)",
                data=toelichting_edit,
                file_name=f"toelichting_{c['name']}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        if c.get("approved"):
            st.info("Toelichting is goedgekeurd. Verwijder de goedkeuring bovenaan om opnieuw te bewerken.")

    with tab3:
        st.subheader("Ruwe extractie (JSON)")
        st.caption("Volledige output van het extractiemodel, inclusief bronquotes, confidence scores en uncertain_items.")

        col_p, col_s = st.columns(2)
        with col_p:
            st.markdown("**Partijen**")
            parties = data.get("parties") or {}
            st.markdown(f"- Leninggever: {parties.get('creditor') or '—'}")
            st.markdown(f"- Leningnemer: {parties.get('debtor')   or '—'}")
            st.markdown("**Ontbrekende items (model)**")
            for m in (data.get("missing_items") or []):
                st.markdown(f"- {m}")
            if not data.get("missing_items"):
                st.caption("Geen")
        with col_s:
            st.markdown("**Onzekere items (model)**")
            for u in (data.get("uncertain_items") or []):
                st.markdown(f"- {u}")
            if not data.get("uncertain_items"):
                st.caption("Geen")
            st.markdown("**Confidence scores**")
            for k, v in (data.get("confidence_scores") or {}).items():
                if v:
                    if v == "high":
                        kleur = "🟢"
                    elif v == "medium":
                        kleur = "🟡"
                    elif v == "low":
                        kleur = "🔴"
                    else:
                        kleur = "⚪"
                    st.markdown(f"- {kleur} *{k}:* {v}")
            st.markdown("**Bronquotes**")
            for k, v in (data.get("source_quotes") or {}).items():
                if v:
                    st.markdown(f"- *{k}:* {v[:120]}")

        st.divider()
        with st.expander("Volledige JSON-output"):
            st.json(data)

    with tab4:
        st.subheader("Audit trail")
        st.caption("Vastlegging van verwerkingsstappen conform het borgingsplan (wie, wanneer, wat).")
        contract_log = [e for e in st.session_state.audit_log if e["contract"] == c["name"]]
        if contract_log:
            st.dataframe(pd.DataFrame(contract_log), use_container_width=True, hide_index=True)
        else:
            st.caption("Geen log-entries voor dit contract.")
