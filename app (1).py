import os
import json
import fitz
import pandas as pd
import streamlit as st
from datetime import datetime
from openai import OpenAI

st.set_page_config(
    page_title="Leningsovereenkomsten PoC — Vermetten",
    page_icon="https://www.vermetten.nl/public/themes/www/_compiled/images/favicon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Vermetten huisstijl ───────────────────────────────────────────────────────
# Kleuren van vermetten.nl:
#   Donkerblauw:  #1C3F6E  (primair, navigatie, headers)
#   Middenblauw:  #2B5EA7  (accent, knoppen hover)
#   Lichtblauw:   #E8EEF7  (achtergronden, zebra)
#   Oranje/goud:  #E8A020  (call-to-action accentkleur)
#   Tekst grijs:  #4A4A4A
#   Lichtgrijs:   #F5F6F8  (achtergronden)

st.markdown("""
<style>
    /* ── Vermetten kleurpalet ── */
    :root {
        --v-blue:        #1C3F6E;
        --v-blue-mid:    #2B5EA7;
        --v-blue-light:  #E8EEF7;
        --v-gold:        #E8A020;
        --v-text:        #2C2C2C;
        --v-muted:       #6B7280;
        --v-bg:          #F5F6F8;
        --v-white:       #FFFFFF;
        --v-border:      #D1D9E6;
        --v-success:     #15803d;
        --v-warning:     #b45309;
        --v-danger:      #dc2626;
    }

    /* ── Globale achtergrond ── */
    .stApp { background-color: var(--v-bg); }
    .stApp > header { background-color: var(--v-blue) !important; }

    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background-color: var(--v-blue) !important;
        border-right: none;
    }
    [data-testid="stSidebar"] * {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] .stButton > button {
        background-color: rgba(255,255,255,0.12) !important;
        border: 1px solid rgba(255,255,255,0.25) !important;
        color: #FFFFFF !important;
        border-radius: 6px;
        font-size: 13px;
        text-align: left;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background-color: rgba(255,255,255,0.22) !important;
    }
    [data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background-color: var(--v-gold) !important;
        border: none !important;
        color: #FFFFFF !important;
        font-weight: 600;
    }
    [data-testid="stSidebar"] .stTextInput input {
        background-color: rgba(255,255,255,0.1) !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
        color: #FFFFFF !important;
        border-radius: 6px;
    }
    [data-testid="stSidebar"] .stTextInput input::placeholder { color: rgba(255,255,255,0.5) !important; }
    [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.2) !important; }

    /* ── Hoofdinhoud ── */
    .main .block-container { padding-top: 1.5rem; }

    /* ── Knoppen ── */
    .stButton > button[kind="primary"] {
        background-color: var(--v-blue) !important;
        border: none !important;
        color: #FFFFFF !important;
        border-radius: 6px;
        font-weight: 600;
        padding: 0.45rem 1.2rem;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: var(--v-blue-mid) !important;
    }
    .stButton > button:not([kind="primary"]) {
        border: 1px solid var(--v-border) !important;
        color: var(--v-text) !important;
        border-radius: 6px;
        background: var(--v-white) !important;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        border-bottom: 2px solid var(--v-border);
        gap: 0;
    }
    .stTabs [data-baseweb="tab"] {
        color: var(--v-muted) !important;
        font-weight: 500;
        padding: 0.6rem 1.2rem;
        border-radius: 0;
        border-bottom: 2px solid transparent;
        margin-bottom: -2px;
    }
    .stTabs [aria-selected="true"] {
        color: var(--v-blue) !important;
        border-bottom: 2px solid var(--v-blue) !important;
        background: transparent !important;
    }

    /* ── Metrics ── */
    [data-testid="metric-container"] {
        background: var(--v-white);
        border: 1px solid var(--v-border);
        border-radius: 8px;
        padding: 0.75rem 1rem;
        border-top: 3px solid var(--v-blue);
    }
    [data-testid="metric-container"] label { color: #4A4A4A !important; font-size: 12px !important; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] { color: var(--v-blue) !important; font-weight: 700; }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] { color: #4A4A4A !important; }

    /* Expander: zorg voor leesbare tekst op lichte achtergrond */
    .streamlit-expanderContent { background: var(--v-white) !important; }
    .streamlit-expanderContent [data-testid="metric-container"] {
        background: var(--v-bg) !important;
    }
    .streamlit-expanderContent [data-testid="metric-container"] label { color: #4A4A4A !important; }
    .streamlit-expanderContent [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: var(--v-blue) !important;
    }
    .streamlit-expanderContent .stAlert p { color: #4A4A4A !important; }
    .streamlit-expanderContent p,
    .streamlit-expanderContent span,
    .streamlit-expanderContent div { color: #2C2C2C; }

    /* ── Tekstvak ── */
    .stTextArea textarea {
        font-size: 13px;
        line-height: 1.7;
        border: 1px solid var(--v-border) !important;
        border-radius: 6px;
        background: var(--v-white) !important;
    }

    /* ── Dataframe ── */
    [data-testid="stDataFrame"] { border: 1px solid var(--v-border); border-radius: 8px; overflow: hidden; }

    /* ── Expander ── */
    .streamlit-expanderHeader { color: var(--v-blue) !important; font-weight: 500; }

    /* ── Custom banners ── */
    .v-approved {
        background: #f0fdf4; border: 1px solid #bbf7d0;
        border-left: 4px solid var(--v-success);
        border-radius: 6px; padding: 10px 16px;
        color: var(--v-success); font-size: 14px; margin-bottom: 12px;
    }
    .v-hitl {
        background: #fffbeb; border: 1px solid #fde68a;
        border-left: 4px solid var(--v-gold);
        border-radius: 6px; padding: 10px 16px;
        color: #92400e; font-size: 13px; margin-bottom: 8px;
    }
    .v-flag {
        background: #fef2f2; border: 1px solid #fecaca;
        border-left: 4px solid var(--v-danger);
        border-radius: 6px; padding: 10px 16px;
        color: var(--v-danger); font-size: 13px; margin-bottom: 8px;
    }
    .v-header-bar {
        background: var(--v-blue);
        color: white;
        padding: 0.8rem 1.2rem;
        border-radius: 8px;
        margin-bottom: 1.2rem;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .v-header-bar .v-title { font-size: 17px; font-weight: 700; }
    .v-header-bar .v-sub   { font-size: 12px; opacity: 0.75; }
    .v-tag {
        display: inline-block;
        background: var(--v-blue-light);
        color: var(--v-blue);
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 4px;
        margin-right: 4px;
    }
    .v-tag-gold {
        background: #fef3c7;
        color: #92400e;
    }
    .status-gereed  { color: var(--v-success); font-weight: 600; }
    .status-review  { color: var(--v-warning); font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── Constanten ────────────────────────────────────────────────────────────────
CHECKLIST_ITEMS = [
    {"field": "principal_amount",   "label": "Hoofdsom",               "required": True,  "rj": "RJ 272.408a"},
    {"field": "interest_rate",      "label": "Rentepercentage",        "required": True,  "rj": "RJ 272.408b"},
    {"field": "start_date",         "label": "Ingangsdatum",           "required": True,  "rj": "RJ 272.408c"},
    {"field": "end_date",           "label": "Einddatum",              "required": False, "rj": "RJ 272.408c"},
    {"field": "term_description",   "label": "Looptijdomschrijving",   "required": False, "rj": "RJ 272.408c"},
    {"field": "repayment_terms",    "label": "Aflossingsvoorwaarden",  "required": True,  "rj": "RJ 272.408d"},
    {"field": "security",           "label": "Zekerheden",             "required": False, "rj": "RJ 272.408e"},
    {"field": "subordination",      "label": "Achterstelling",         "required": False, "rj": "RJ 272.408f"},
    {"field": "special_conditions", "label": "Bijzondere voorwaarden", "required": False, "rj": "RJ 272.408g"},
]

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
                "principal_amount":    {"type": ["string", "null"]},
                "interest_rate":       {"type": ["string", "null"]},
                "repayment_terms":     {"type": ["string", "null"]},
                "start_date":          {"type": ["string", "null"]},
                "end_date":            {"type": ["string", "null"]},
                "security":            {"type": ["string", "null"]},
                "subordination":       {"type": ["string", "null"]},
                "special_conditions":  {"type": ["string", "null"]},
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

def _matches_any(zoektermen, tekstlijst):
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
            remark = "Ontbreekt"
        elif _matches_any(zoektermen, uncertain):
            remark = "Onzeker"
        elif present:
            remark = "Aanwezig"
        else:
            remark = "Niet aangetroffen"
        rows.append({
            **item,
            "value":      value,
            "present":    present,
            "remark":     remark,
            "confidence": scores.get(field),
            "quote":      (data.get("source_quotes") or {}).get(field),
        })
    return rows

def determine_status(checklist: list[dict]) -> str:
    verplicht = [i for i in checklist if i["required"]]
    ontbreekt = [i for i in verplicht if not i["present"]]
    onzeker   = [i for i in verplicht if i["remark"] == "Onzeker"]
    return "Gereed voor review" if not ontbreekt and not onzeker else "Review vereist"

def compute_precision_recall(checklist):
    totaal_schema = len(CHECKLIST_ITEMS)
    herkend       = [i for i in checklist if i["present"] and i["remark"] == "Aanwezig"]
    n_totaal_pres = sum(1 for i in checklist if i["present"])
    precision = (len(herkend) / n_totaal_pres * 100) if n_totaal_pres else None
    recall    = (len(herkend) / totaal_schema  * 100) if totaal_schema else None
    return precision, recall

# ── OpenAI ────────────────────────────────────────────────────────────────────

def extract_data(client, document_text):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Je analyseert een Nederlandse leningsovereenkomst voor middelgrote rechtspersonen (RJ 272). "
                    "Extraheer ALLEEN informatie die expliciet in de contracttekst staat. "
                    "Gebruik null voor ontbrekende velden — verzin niets. "
                    "Geef per geëxtraheerd veld een confidence score: 'high' (expliciet vermeld), "
                    "'medium' (afgeleid), 'low' (onzeker). "
                    "Retourneer geldig JSON conform het opgegeven schema."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Schema:\n{json.dumps(EXTRACTION_SCHEMA, ensure_ascii=False)}"
                    f"\n\nContract:\n{document_text[:12000]}"
                ),
            },
        ],
    )
    return json.loads(response.choices[0].message.content)

def generate_toelichting(client, data):
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
                    "voor middelgrote rechtspersonen op basis van contractgegevens conform RJ 272. "
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
    # Logo / branding
    st.markdown("""
    <div style="padding: 0.5rem 0 1rem 0; border-bottom: 1px solid rgba(255,255,255,0.2); margin-bottom: 1rem;">
        <div style="font-size: 20px; font-weight: 800; letter-spacing: -0.5px; color: white;">
            Vermetten
        </div>
        <div style="font-size: 11px; color: rgba(255,255,255,0.65); margin-top: 2px;">
            accountants en adviseurs
        </div>
        <div style="margin-top: 8px;">
            <span style="background: rgba(232,160,32,0.3); color: #fbbf24; font-size: 10px;
                         font-weight: 600; padding: 2px 8px; border-radius: 4px;">
                PoC · Leningsovereenkomsten
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    api_key = st.text_input(
        "OpenAI API-sleutel",
        type="password",
        placeholder="sk-...",
        help="PoC-fase: OpenAI API. Productie: private deployment vereist (AVG).",
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if st.button("➕ Nieuw contract verwerken", use_container_width=True, type="primary"):
        st.session_state.active_idx = None

    if st.session_state.contracts:
        st.markdown(
            "<div style='font-size:11px; font-weight:600; text-transform:uppercase; "
            "letter-spacing:0.8px; color:rgba(255,255,255,0.5); margin: 1rem 0 0.5rem;'>"
            "Contracten</div>",
            unsafe_allow_html=True,
        )
        for i, c in enumerate(st.session_state.contracts):
            status_icon   = "✅" if c["status"] == "Gereed voor review" else "⚠️"
            approved_icon = " 🔒" if c.get("approved") else ""
            label = f"{status_icon} {c['name'][:26]}{approved_icon}"
            if st.button(label, key=f"nav_{i}", use_container_width=True):
                st.session_state.active_idx = i

        st.divider()
        gereed      = sum(1 for c in st.session_state.contracts if c["status"] == "Gereed voor review")
        goedgekeurd = sum(1 for c in st.session_state.contracts if c.get("approved"))
        st.caption(f"Totaal: {len(st.session_state.contracts)} · Gereed: {gereed} · Goedgekeurd: {goedgekeurd}")

    if st.session_state.audit_log:
        st.divider()
        with st.expander(f"📋 Audit trail ({len(st.session_state.audit_log)})"):
            df_audit = pd.DataFrame(st.session_state.audit_log)
            st.dataframe(df_audit, use_container_width=True, hide_index=True)

    st.markdown("<div style='height: 2rem'></div>", unsafe_allow_html=True)
    st.caption("Zonder gedoe.")

# ── Hoofdpagina: nieuw contract ───────────────────────────────────────────────

if st.session_state.active_idx is None:

    # Paginakop in Vermetten stijl
    st.markdown("""
    <div class="v-header-bar">
        <div>
            <div class="v-title">📄 Nieuw contract verwerken</div>
            <div class="v-sub">AI-gestuurde toelichting · RJ 272 · Middelgrote rechtspersonen</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        '<div class="v-hitl">'
        "⚠️ <strong>Human-in-the-loop:</strong> de gegenereerde toelichting is altijd een concept. "
        "De accountant beoordeelt, past zo nodig aan, en keurt goed voordat de toelichting "
        "in de jaarrekening wordt opgenomen. Zonder gedoe."
        "</div>",
        unsafe_allow_html=True,
    )

    if not api_key:
        st.info("Voer eerst je OpenAI API-sleutel in de zijbalk in.")
        st.caption("ℹ️ PoC-fase: OpenAI API. Voor productiegebruik is private deployment vereist conform AVG en kantoorbeleid van Vermetten.")
        st.stop()

    uploaded = st.file_uploader(
        "Selecteer een PDF-bestand",
        type=["pdf"],
        help="Ondersteund: PDF. Max. aanbevolen 10 MB.",
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

                st.write("🤖 Gegevens extraheren via AI (gpt-4o-mini, temperature=0)...")
                try:
                    extracted = extract_data(client, document_text)
                except Exception as e:
                    st.error(f"Fout bij AI-extractie: {e}")
                    st.stop()
                st.write("✓ Gegevens geëxtraheerd")

                st.write("📋 Checklist valideren tegen RJ 272...")
                checklist  = build_checklist(extracted)
                status_val = determine_status(checklist)
                precision, recall = compute_precision_recall(checklist)
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
                "precision":   precision,
                "recall":      recall,
                "verwerkt_op": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            st.session_state.contracts.append(contract)
            st.session_state.active_idx = len(st.session_state.contracts) - 1
            st.rerun()

    st.divider()

    if st.session_state.contracts:
        st.markdown("#### Overzicht contracten")
        overzicht = []
        for c in st.session_state.contracts:
            hs = get_field_value(c["data"], "principal_amount") or "—"
            overzicht.append({
                "Contract":        c["name"],
                "Verwerkt op":     c.get("verwerkt_op", "—"),
                "Status":          c["status"],
                "Goedgekeurd":     "✅ Ja" if c.get("approved") else "❌ Nee",
                "Hoofdsom":        hs,
                "Rente":           f"{c['data'].get('interest_rate', '—')}%" if c["data"].get("interest_rate") is not None else "—",
                "Precision":       f"{c['precision']:.0f}%" if c.get("precision") is not None else "—",
                "Recall":          f"{c['recall']:.0f}%"    if c.get("recall")    is not None else "—",
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
    n_onzeker   = sum(1 for i in cl if i["remark"] == "Onzeker")
    n_ontbreekt = sum(1 for i in cl if i["remark"] == "Ontbreekt")
    n_quotes    = sum(1 for i in cl if i["quote"])
    n_low_conf  = sum(1 for i in cl if i.get("confidence") == "low")

    # Header
    col_title, col_btn = st.columns([3, 1])
    with col_title:
        st.markdown(f"""
        <div class="v-header-bar">
            <div>
                <div class="v-title">📄 {c['name']}</div>
                <div class="v-sub">Verwerkt op {c.get('verwerkt_op', '—')} · RJ 272 · Middelgrote rechtspersonen</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        status_class = "status-gereed" if c["status"] == "Gereed voor review" else "status-review"
        st.markdown(
            f'{"✅" if c["status"] == "Gereed voor review" else "⚠️"} '
            f'<span class="{status_class}">{c["status"]}</span>',
            unsafe_allow_html=True,
        )
    with col_btn:
        st.markdown("<br><br>", unsafe_allow_html=True)
        if c.get("approved"):
            st.success("🔒 Goedgekeurd")
        else:
            if st.button("✅ Goedkeuren", type="primary", use_container_width=True, key=f"approve_header_{idx}"):
                st.session_state.contracts[idx]["approved"] = True
                log_event("Goedgekeurd", c["name"], "Goedgekeurd door accountant")
                st.rerun()

    if c.get("approved"):
        st.markdown('<div class="v-approved">🔒 Deze toelichting is goedgekeurd door de accountant en kan worden opgenomen in de jaarrekening.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="v-hitl">⚠️ <strong>Concept:</strong> beoordeel de toelichting en checklistresultaten voordat u goedkeurt.</div>', unsafe_allow_html=True)

    if n_low_conf:
        lage = ", ".join(i["label"] for i in cl if i.get("confidence") == "low")
        st.markdown(f'<div class="v-flag">🔴 <strong>Extra review aanbevolen</strong> — lage confidence voor: {lage}</div>', unsafe_allow_html=True)

    # Metrics
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Verplichte velden",   f"{n_aanwezig}/{n_verplicht}")
    m2.metric("Onzekere velden",     n_onzeker)
    m3.metric("Ontbrekende velden",  n_ontbreekt)
    m4.metric("Bronquotes",          n_quotes)
    m5.metric("Precision",  f"{c['precision']:.0f}%" if c.get("precision") is not None else "—", help="Streefwaarde ≥ 95%")
    m6.metric("Recall",     f"{c['recall']:.0f}%"    if c.get("recall")    is not None else "—", help="Streefwaarde ≥ 90%")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Checklistvalidatie RJ 272",
        "✍️ Concept-toelichting",
        "🔍 Ruwe extractie",
        "📋 Audit trail",
    ])

    # ── Tab 1 ─────────────────────────────────────────────────────────────────
    with tab1:
        st.subheader("Checklistvalidatie RJ 272")
        st.caption("Toetsing aan de vereisten voor middelgrote rechtspersonen.")

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filter_verplicht = st.checkbox("Toon alleen verplichte velden", value=False)
        with col_f2:
            filter_aandacht = st.checkbox("Toon alleen aandachtspunten", value=False)

        rows = []
        for item in cl:
            if filter_verplicht and not item["required"]:
                continue
            if filter_aandacht and item["remark"] in ("Aanwezig", "Niet aangetroffen") and item["present"]:
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
            if val == "Aanwezig":  return "color: #15803d"
            if val == "Onzeker":   return "color: #b45309"
            if val == "Ontbreekt": return "color: #dc2626"
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
            st.success("Alle verplichte RJ 272-velden zijn aangetroffen.")
        if n_onzeker:
            st.warning(f"**{n_onzeker} veld(en) onzeker:** " + ", ".join(i["label"] for i in cl if i["remark"] == "Onzeker"))

        with st.expander("📊 Kwaliteitsmetrieken (borgingsplan streefwaarden)"):
            prec, rec = c.get("precision"), c.get("recall")
            c1, c2 = st.columns(2)
            c1.metric("Precision", f"{prec:.1f}%" if prec is not None else "—", help="Streefwaarde ≥ 95%")
            c2.metric("Recall",    f"{rec:.1f}%"  if rec  is not None else "—", help="Streefwaarde ≥ 90%")
            if prec is not None and prec < 95: st.warning("Precision onder streefwaarde (≥ 95%)")
            if rec  is not None and rec  < 90: st.warning("Recall onder streefwaarde (≥ 90%)")

    # ── Tab 2 ─────────────────────────────────────────────────────────────────
    with tab2:
        st.subheader("Concept-toelichting jaarrekening")
        st.caption("Gegenereerd conform RJ 272. Controleer, bewerk indien nodig, en keur goed.")

        toelichting_key = f"toelichting_{idx}"
        if toelichting_key not in st.session_state:
            st.session_state[toelichting_key] = c["toelichting"]

        toelichting_edit = st.text_area(
            "Concept-toelichting (bewerkbaar)",
            value=st.session_state[toelichting_key],
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
                    log_event("Goedgekeurd", c["name"], "Via toelichting-tab")
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

    # ── Tab 3 ─────────────────────────────────────────────────────────────────
    with tab3:
        st.subheader("Ruwe extractie")
        st.caption("Volledige modeloutput inclusief bronquotes, confidence scores en uncertain_items.")

        col_p, col_s = st.columns(2)
        with col_p:
            st.markdown("**Partijen**")
            parties = data.get("parties") or {}
            st.markdown(f"- Leninggever: {parties.get('creditor') or '—'}")
            st.markdown(f"- Leningnemer: {parties.get('debtor')   or '—'}")
            st.markdown("**Ontbrekende items**")
            for m in (data.get("missing_items") or []):
                st.markdown(f"- {m}")
            if not data.get("missing_items"):
                st.caption("Geen")
        with col_s:
            st.markdown("**Onzekere items**")
            for u in (data.get("uncertain_items") or []):
                st.markdown(f"- {u}")
            if not data.get("uncertain_items"):
                st.caption("Geen")
            st.markdown("**Confidence scores**")
            for k, v in (data.get("confidence_scores") or {}).items():
                if v:
                    kleur = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(v, "⚪")
                    st.markdown(f"- {kleur} *{k}:* {v}")
            st.markdown("**Bronquotes**")
            for k, v in (data.get("source_quotes") or {}).items():
                if v:
                    st.markdown(f"- *{k}:* {v[:120]}")

        st.divider()
        with st.expander("Volledige JSON-output"):
            st.json(data)

    # ── Tab 4 ─────────────────────────────────────────────────────────────────
    with tab4:
        st.subheader("Audit trail")
        st.caption("Vastlegging van verwerkingsstappen conform het borgingsplan (wie, wanneer, wat).")
        contract_log = [e for e in st.session_state.audit_log if e["contract"] == c["name"]]
        if contract_log:
            st.dataframe(pd.DataFrame(contract_log), use_container_width=True, hide_index=True)
        else:
            st.caption("Geen log-entries voor dit contract.")
