import os
import json
import fitz
import pandas as pd
import streamlit as st
from openai import OpenAI

st.set_page_config(
    page_title="Leningsovereenkomsten PoC",
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
</style>
""", unsafe_allow_html=True)

# ── Constanten ────────────────────────────────────────────────────────────────

CHECKLIST_ITEMS = [
    {"field": "principal_amount",   "label": "Hoofdsom",               "required": True,  "rj": "RJ 292.408a"},
    {"field": "interest_rate",      "label": "Rentepercentage",        "required": True,  "rj": "RJ 292.408b"},
    {"field": "start_date",         "label": "Ingangsdatum",           "required": True,  "rj": "RJ 292.408c"},
    {"field": "end_date",           "label": "Einddatum",              "required": False, "rj": "RJ 292.408c"},
    {"field": "term_description",   "label": "Looptijdomschrijving",   "required": False, "rj": "RJ 292.408c"},
    {"field": "repayment_terms",    "label": "Aflossingsvoorwaarden",  "required": True,  "rj": "RJ 292.408d"},
    {"field": "security",           "label": "Zekerheden",             "required": False, "rj": "RJ 292.408e"},
    {"field": "subordination",      "label": "Achterstelling",         "required": False, "rj": "RJ 292.408f"},
    {"field": "special_conditions", "label": "Bijzondere voorwaarden", "required": False, "rj": "RJ 292.408g"},
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
        "source_quotes": {
            "type": "object",
            "properties": {
                "principal_amount": {"type": ["string", "null"]},
                "interest_rate":    {"type": ["string", "null"]},
                "repayment_terms":  {"type": ["string", "null"]},
            },
            "required": ["principal_amount", "interest_rate", "repayment_terms"],
            "additionalProperties": False,
        },
    },
    "required": [
        "document_type", "parties", "principal_amount", "interest_rate",
        "start_date", "end_date", "term_description", "repayment_terms",
        "security", "subordination", "special_conditions",
        "missing_items", "uncertain_items", "source_quotes",
    ],
    "additionalProperties": False,
}

# ── Sessiestatus initialiseren ─────────────────────────────────────────────────

if "contracts" not in st.session_state:
    st.session_state.contracts = []
if "active_idx" not in st.session_state:
    st.session_state.active_idx = None

# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def extract_text_from_pdf(uploaded_file) -> str:
    """Extraheert alle tekst uit een geüpload PDF-bestand."""
    with fitz.open(stream=uploaded_file.read(), filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def get_field_value(data: dict, field: str) -> str | None:
    """Haalt een veldwaarde op en formatteert deze voor weergave."""
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
    """Partiële match: controleert of een zoekterm voorkomt in een van de teksten."""
    return any(term in tekst for term in zoektermen for tekst in tekstlijst)


def build_checklist(data: dict) -> list[dict]:
    """Bouwt de checklistresultaten op basis van geëxtraheerde contractdata."""
    missing   = [m.lower() for m in data.get("missing_items",   [])]
    uncertain = [u.lower() for u in data.get("uncertain_items", [])]
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
        rows.append({
            **item,
            "value":   value,
            "present": present,
            "remark":  remark,
            "quote":   (data.get("source_quotes") or {}).get(field),
        })
    return rows


def determine_status(checklist: list[dict]) -> str:
    """Bepaalt de reviewstatus op basis van verplichte velden."""
    verplicht = [i for i in checklist if i["required"]]
    ontbreekt = [i for i in verplicht if not i["present"]]
    onzeker   = [i for i in verplicht if i["remark"] == "Onzeker volgens model"]
    return "Gereed voor review" if not ontbreekt and not onzeker else "Review vereist"


# ── OpenAI-aanroepen ──────────────────────────────────────────────────────────

def extract_data(client: OpenAI, document_text: str) -> dict:
    """Extraheert contractgegevens via gpt-4o-mini."""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "Je analyseert een Nederlandse leningsovereenkomst. "
                    "Extraheer alleen informatie die expliciet in de tekst staat. "
                    "Gebruik null voor ontbrekende velden. "
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


def generate_toelichting(client: OpenAI, data: dict) -> str:
    """Genereert een concept-toelichting voor de jaarrekening via gpt-4o."""
    relevante_velden = [
        "document_type", "parties", "principal_amount", "interest_rate",
        "start_date", "end_date", "repayment_terms", "security",
        "subordination", "special_conditions",
    ]
    relevante_data   = {k: data.get(k) for k in relevante_velden}
    onzekere_items   = data.get("uncertain_items", [])

    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Je schrijft een zakelijke Nederlandse jaarrekeningtoelichting "
                    "op basis van contractgegevens conform RJ 292. "
                    "Verzin niets. Laat null-velden weg. "
                    'Sluit af met: "De accountant voert nog een finale beoordeling uit."'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Onzekere items (weglaten): {onzekere_items}\n\n"
                    f"Gegevens:\n{json.dumps(relevante_data, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
    )
    return response.choices[0].message.content


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 📄 Leningsovereenkomsten")
    st.markdown("AI-gestuurde toelichting voor de jaarrekening — RJ 292")
    st.divider()

    api_key = st.text_input(
        "OpenAI API-sleutel",
        type="password",
        placeholder="sk-...",
        help="Je sleutel wordt alleen in geheugen bewaard en niet opgeslagen.",
    )

    st.divider()

    if st.button("➕ Nieuw contract", use_container_width=True, type="primary"):
        st.session_state.active_idx = None

    st.markdown("**Verwerkte contracten**")
    for i, c in enumerate(st.session_state.contracts):
        status_icon = "✅" if c["status"] == "Gereed voor review" else "⚠️"
        approved_icon = " 🔒" if c.get("approved") else ""
        label = f"{status_icon} {c['name'][:24]}{approved_icon}"
        if st.button(label, key=f"nav_{i}", use_container_width=True):
            st.session_state.active_idx = i

    if st.session_state.contracts:
        st.divider()
        gereed      = sum(1 for c in st.session_state.contracts if c["status"] == "Gereed voor review")
        goedgekeurd = sum(1 for c in st.session_state.contracts if c.get("approved"))
        st.caption(f"Totaal: {len(st.session_state.contracts)} | Gereed: {gereed} | Goedgekeurd: {goedgekeurd}")

# ── Hoofdpagina: nieuw contract ───────────────────────────────────────────────

if st.session_state.active_idx is None:

    st.title("Nieuw contract verwerken")
    st.caption("Upload een leningsovereenkomst als PDF. Het AI-model extraheert de gegevens en genereert een concept-toelichting conform RJ 292.")

    if not api_key:
        st.info("Voer eerst je OpenAI API-sleutel in de zijbalk in.")
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

                st.write("🤖 Gegevens extraheren via AI (gpt-4o-mini)...")
                try:
                    extracted = extract_data(client, document_text)
                except Exception as e:
                    st.error(f"Fout bij AI-extractie: {e}")
                    st.stop()

                st.write("✓ Gegevens geëxtraheerd")

                st.write("📋 Checklist valideren tegen RJ 292...")
                checklist   = build_checklist(extracted)
                status_val  = determine_status(checklist)
                st.write(f"✓ Validatie klaar — status: **{status_val}**")

                st.write("✍️ Concept-toelichting genereren (gpt-4o)...")
                try:
                    toelichting = generate_toelichting(client, extracted)
                except Exception as e:
                    st.error(f"Fout bij toelichtingsgeneratie: {e}")
                    st.stop()

                st.write("✓ Concept-toelichting gereed")
                status_widget.update(label="Verwerking voltooid", state="complete")

            contract = {
                "name":        uploaded.name.replace(".pdf", ""),
                "filename":    uploaded.name,
                "data":        extracted,
                "checklist":   checklist,
                "status":      status_val,
                "toelichting": toelichting,
                "approved":    False,
            }
            st.session_state.contracts.append(contract)
            st.session_state.active_idx = len(st.session_state.contracts) - 1
            st.rerun()

    st.divider()
    st.info(
        "**Human-in-the-loop:** de gegenereerde toelichting is een concept. "
        "De accountant beoordeelt en keurt de inhoud goed voordat deze in de jaarrekening wordt opgenomen."
    )

# ── Hoofdpagina: bestaand contract ───────────────────────────────────────────

else:
    idx = st.session_state.active_idx
    c   = st.session_state.contracts[idx]
    cl  = c["checklist"]
    data = c["data"]

    n_verplicht  = sum(1 for i in cl if i["required"])
    n_aanwezig   = sum(1 for i in cl if i["required"] and i["present"])
    n_onzeker    = sum(1 for i in cl if i["remark"] == "Onzeker volgens model")
    n_ontbreekt  = sum(1 for i in cl if i["remark"] == "Ontbreekt volgens model")
    n_quotes     = sum(1 for i in cl if i["quote"])

    # Header
    col_title, col_btn = st.columns([3, 1])
    with col_title:
        st.title(c["name"])
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
                st.rerun()

    if c.get("approved"):
        st.markdown('<div class="approved-banner">🔒 Deze toelichting is goedgekeurd door de accountant en kan worden opgenomen in de jaarrekening.</div>', unsafe_allow_html=True)

    # Metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Verplichte velden", f"{n_aanwezig}/{n_verplicht}")
    m2.metric("Onzekere velden",   n_onzeker,  delta=None)
    m3.metric("Ontbrekende velden", n_ontbreekt, delta=None)
    m4.metric("Bronquotes",        n_quotes)
    m5.metric("Contracten totaal", len(st.session_state.contracts))

    st.divider()

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📋 Checklistvalidatie", "✍️ Concept-toelichting", "🔍 Ruwe extractie"])

    # ── Tab 1: Checklist ──────────────────────────────────────────────────────
    with tab1:
        st.subheader("Checklistvalidatie RJ 292")
        st.caption("Toetsing van geëxtraheerde contractgegevens aan de vereisten voor middelgrote rechtspersonen.")

        # Filteropties
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
                "Opmerking":    item["remark"],
            })

        df = pd.DataFrame(rows)

        def kleur_opmerking(val):
            if val == "Aanwezig":          return "color: #15803d"
            if val == "Onzeker volgens model":  return "color: #b45309"
            if val == "Ontbreekt volgens model": return "color: #dc2626"
            return "color: #6b7280"

        st.dataframe(
            df.style.map(kleur_opmerking, subset=["Opmerking"]),
            use_container_width=True,
            hide_index=True,
            height=min(60 + len(rows) * 38, 480),
        )

        ontbrekende_verplicht = [i for i in cl if i["required"] and not i["present"]]
        if ontbrekende_verplicht:
            st.warning(
                f"**{len(ontbrekende_verplicht)} verplicht(e) veld(en) ontbreken:** "
                + ", ".join(i["label"] for i in ontbrekende_verplicht)
            )
        else:
            st.success("Alle verplichte RJ 292-velden zijn aangetroffen.")

        if n_onzeker:
            st.warning(
                f"**{n_onzeker} veld(en) onzeker:** "
                + ", ".join(i["label"] for i in cl if i["remark"] == "Onzeker volgens model")
            )

    # ── Tab 2: Toelichting ────────────────────────────────────────────────────
    with tab2:
        st.subheader("Concept-toelichting jaarrekening")
        st.caption(
            "Gegenereerd op basis van de geëxtraheerde contractgegevens. "
            "Controleer, bewerk indien nodig, en keur goed."
        )

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

        col_a, col_b, col_c = st.columns([1, 1, 3])
        with col_a:
            if not c.get("approved"):
                if st.button("✅ Goedkeuren", type="primary", use_container_width=True, key=f"approve_tab2_{idx}"):
                    st.session_state.contracts[idx]["approved"] = True
                    st.rerun()
        with col_b:
            st.download_button(
                label="⬇ Downloaden",
                data=toelichting_edit,
                file_name=f"toelichting_{c['name']}.txt",
                mime="text/plain",
                use_container_width=True,
            )

        if c.get("approved"):
            st.info("Deze toelichting is goedgekeurd. Verwijder de goedkeuring via de knop bovenaan om opnieuw te bewerken.")

    # ── Tab 3: Ruwe extractie ─────────────────────────────────────────────────
    with tab3:
        st.subheader("Ruwe extractie (JSON)")
        st.caption("Volledige output van het extractiemodel, inclusief bronquotes, missing_items en uncertain_items.")

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

            st.markdown("**Bronquotes**")
            sq = data.get("source_quotes") or {}
            for k, v in sq.items():
                if v:
                    st.markdown(f"- *{k}:* {v[:120]}")

        st.divider()
        with st.expander("Volledige JSON-output"):
            st.json(data)

# ── Overzichtspagina (via sidebar-knop) ──────────────────────────────────────

if st.session_state.active_idx is None and st.session_state.contracts:
    st.divider()
    st.subheader("Overzicht alle contracten")

    overzicht = []
    for c in st.session_state.contracts:
        hs = get_field_value(c["data"], "principal_amount") or "—"
        overzicht.append({
            "Contract":        c["name"],
            "Status":          c["status"],
            "Goedgekeurd":     "Ja" if c.get("approved") else "Nee",
            "Hoofdsom":        hs,
            "Rentepercentage": f"{c['data'].get('interest_rate', '—')}%"
                               if c["data"].get("interest_rate") is not None else "—",
            "Startdatum":      c["data"].get("start_date") or "—",
            "Einddatum":       c["data"].get("end_date")   or "—",
        })

    st.dataframe(pd.DataFrame(overzicht), use_container_width=True, hide_index=True)
