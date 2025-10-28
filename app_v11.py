# app_v12.py
"""
LaunchPad PPC - v1.2 (updated UX)
Changes implemented per request:
1) Logo removed from uploader; uses LOGO_PATH constant (local path). Displayed large next to title.
2) Only file upload allowed is Keyword file; all other inputs are comma-separated text inputs.
3) SKU column filled ONLY for rows where Entity == 'Product Ad'; all other rows have SKU blank.
4) Total Daily Budget is a single input and is distributed across chosen campaigns according to their order
   (earlier tactics get proportionally higher allocation).
Run:
    streamlit run app_v12.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import datetime
from io import BytesIO
import os
import plotly.graph_objects as go

st.set_page_config(page_title="LaunchPad PPC - v1.2", layout="wide")

# ---------------- CONFIG ----------------
LOGO_PATH = "s2c_logo.png"  # <-- put your local logo file path here (optional)
AUTO_PT_MULTIPLIERS = {
    "close-match": 1.5,
    "loose-match": 1.2,
    "substitutes": 0.8,
    "complements": 1.0
}
DEFAULT_EXACT_TOP = 5
DEFAULT_PHRASE_NEXT = 7

COLUMN_ORDER = [
    "Product","Entity","Operation","Campaign ID","Ad Group ID","Portfolio ID","Ad ID","Keyword ID",
    "Product Targeting ID","Campaign Name","Ad Group Name","Start Date","End Date","Targeting Type",
    "State","Daily Budget","SKU","Ad Group Default Bid","Bid","Keyword Text",
    "Native Language Keyword","Native Language Locale","Match Type","Bidding Strategy","Placement","Percentage",
    "Product Targeting Expression","Audience ID","Shopper Cohort Percentage","Shopper Cohort Type",
    "Creative ID","Tactic"
]

BRAND_PRIMARY = "#0ea5a4"
BRAND_ACCENT = "#f59e0b"

# ---------------- HEADER (Improved dark-teal layout + readable contrast) ----------------
LOGO_PATH = "logo.png"  # Adjust this to your actual logo path

BRAND_PRIMARY = "#0ea5a4"   # teal
BRAND_ACCENT = "#f59e0b"    # orange
BG_DARK = "#0b2c2d"         # deep teal background
BG_LIGHT = "#fdfcfb"        # for input boxes

# CSS Theme Injection
# --- Clean, consistent S2C dark theme with no white patches ---
st.markdown(
    f"""
    <style>
        html, body, [class*="stApp"] {{
            background: linear-gradient(180deg, #0b2c2d 0%, #071f1f 100%) !important;
            color: #ffffff !important;
        }}
        h1, h2, h3, label, span, div, p {{
            color: #ffffff !important;
        }}
        /* Buttons */
        .stButton>button {{
            background-color: {BRAND_PRIMARY} !important;
            color: white !important;
            border: none !important;
            border-radius: 8px !important;
            font-weight: 600 !important;
        }}
        .stButton>button:hover {{
            background-color: {BRAND_ACCENT} !important;
            color: black !important;
        }}

        /* Inputs, number boxes, file uploader, dropdowns */
        .stTextInput>div>div>input,
        .stNumberInput input,
        .stSelectbox div[data-baseweb="select"],
        .stTextArea textarea,
        .stFileUploader div[data-testid="stFileUploadDropzone"] {{
            background-color: #113738 !important;
            color: #fefefe !important;
            border: 1px solid #16827d !important;
            border-radius: 6px !important;
        }}

        /* File uploader button area */
        .stFileUploader div[data-testid="stFileUploadDropzone"] {{
            background-color: #113738 !important;
            border: 1.5px dashed #0ea5a4 !important;
            color: #d7fdfd !important;
        }}

        /* Sliders and select inputs */
        .stSlider>div>div>div>div {{
            background: {BRAND_ACCENT} !important;
        }}

        /* Dataframes and chart boxes */
        .stDataFrame, .stPlotlyChart, .stDownloadButton {{
            background: #113738 !important;
            border-radius: 10px !important;
            border: 1px solid #0ea5a4 !important;
            color: #ffffff !important;
        }}

        /* File uploader hover effect */
        .stFileUploader div[data-testid="stFileUploadDropzone"]:hover {{
            border-color: {BRAND_ACCENT} !important;
            background-color: #164a49 !important;
        }}
    </style>
    """,
    unsafe_allow_html=True
)

# Header layout with logo + title
col_logo, col_title = st.columns([1.2, 9])
with col_logo:
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=140)
    else:
        st.markdown(
            f"""
            <div style='width:140px;height:140px;border-radius:12px;
                        background:{BRAND_PRIMARY};
                        display:flex;align-items:center;justify-content:center;
                        color:white;font-size:42px;font-weight:700;'>S2C</div>
            """, unsafe_allow_html=True)
        st.caption("⚠️ Logo not found — check LOGO_PATH")

with col_title:
    st.markdown(
        f"<h1 style='margin:0;color:{BRAND_PRIMARY};font-weight:800;'>LaunchPad: Amazon PPC Campaign Creator — v1.2</h1>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"<div style='color:{BRAND_ACCENT};font-size:18px;margin-top:4px;'>Generate Bulk Campaigns • Export .XLSX • Smart Budget Split</div>",
        unsafe_allow_html=True
    )

st.markdown("---")


# ---------------- TOP HORIZONTAL INPUT PANEL (keywords only file upload allowed) ----------------
c1,c2,c3,c4,c5,c6,c7 = st.columns([3.0,2.8,1.8,1.0,1.0,0.9,1.0])
with c1:
    sku_input = st.text_input("Advertised SKU(s) — comma separated (these are your SKUs)", value="", key="sku_input")
with c2:
    asin_input = st.text_input("Competitor ASINs (comma-separated) — for product targeting", value="", key="asin_input")
with c3:
    uploaded_kw = st.file_uploader("Keyword list (optional) — CSV/XLSX, first column used", type=['csv','xls','xlsx'], key="kw_upload")
with c4:
    price = st.number_input("Product Price (AED)", min_value=0.1, value=99.0, step=0.5, format="%.2f")
with c5:
    acos = st.slider("Target ACoS %", min_value=5, max_value=40, value=20)
with c6:
    cvr = st.selectbox("Conversion Rate % (est)", [6,9,12,15,20], index=2)
with c7:
    total_daily_budget = st.number_input("Total Daily Budget (AED)", min_value=1.0, value=200.0, step=1.0, format="%.2f")

run_btn = st.button("Run Analysis", type="primary")

# ---------------- ADVANCED ----------------
adv = st.expander("Advanced options", expanded=False)
with adv:
    at1, at2 = st.columns([1.6,1])
    with at1:
        campaign_types = st.multiselect(
            "Campaign Tactics (order = priority when allocating budget)",
            ["Auto","Manual: Keywords","Manual: ASIN/Product","Category"],
            default=["Auto","Manual: Keywords","Manual: ASIN/Product"]
        )
        if not campaign_types:
            campaign_types = ["Auto","Manual: Keywords"]
        bid_mode = st.selectbox("Campaign-level Bidding Strategy", ["Dynamic bids - down only","Dynamic bids - up and down","Fixed bids"], index=0)
    with at2:
        use_auto_pt = st.checkbox("Enable Auto Product-Targeting types", value=True)
        auto_pt_choices = st.multiselect("Auto PT types", list(AUTO_PT_MULTIPLIERS.keys()), default=list(AUTO_PT_MULTIPLIERS.keys()))
        top_n_kw = st.number_input("Top N keywords to use (0 = use all uploaded)", min_value=0, max_value=500, value=0, step=1)
        exact_top = st.number_input("Exact keywords (top N)", min_value=0, max_value=100, value=DEFAULT_EXACT_TOP, step=1)
        phrase_next = st.number_input("Phrase keywords (next M)", min_value=0, max_value=100, value=DEFAULT_PHRASE_NEXT, step=1)

# ---------------- HELPERS ----------------
def read_sheet_generic(f):
    if f is None:
        return pd.DataFrame()
    try:
        nm = f.name.lower()
        if nm.endswith('.csv'):
            return pd.read_csv(f).fillna("")
        else:
            return pd.read_excel(f, sheet_name=0).fillna("")
    except Exception:
        return pd.DataFrame()

def parse_skus(manual_text):
    if not manual_text:
        return []
    return [s.strip() for s in manual_text.split(",") if s.strip()]

def parse_keywords(uploaded):
    if uploaded is None:
        return []
    df = read_sheet_generic(uploaded)
    if df.empty:
        return []
    col0 = df.columns[0]
    kws = [str(x).strip() for x in df[col0].astype(str).tolist() if str(x).strip()]
    return kws

def parse_asins(text):
    if not text:
        return []
    return [s.strip() for s in text.split(",") if s.strip()]

def calc_base_bid(price_val, acos_pct, cvr_pct):
    base = price_val * (cvr_pct/100.0) * (acos_pct/100.0)
    base = round(max(0.5, base), 2)
    return base

def append_row_dict(entities, row_dict):
    row = [row_dict.get(col, "") for col in COLUMN_ORDER]
    if len(row) < len(COLUMN_ORDER):
        row += [""] * (len(COLUMN_ORDER) - len(row))
    elif len(row) > len(COLUMN_ORDER):
        row = row[:len(COLUMN_ORDER)]
    entities.append(row)

def to_excel_with_metadata(df_main, metadata):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_main.to_excel(writer, index=False, sheet_name="bulk_rows")
        md = pd.DataFrame(list(metadata.items()), columns=["Key","Value"])
        md.to_excel(writer, index=False, sheet_name="metadata")
        writer.close()
    return output.getvalue()

# ---------------- BUDGET ALLOCATION (order-weighted) ----------------
def allocate_budget_by_priority(total_budget, tactics):
    """
    Simple priority-based allocation:
    weight_i = (n - i)  for i = 0..n-1  (earlier tactics get higher weight)
    normalized to total_budget.
    """
    n = len(tactics)
    raw = [n - idx for idx in range(n)]
    s = sum(raw)
    if s == 0:
        return {t: round(total_budget / n, 2) for t in tactics}
    alloc = {tactics[i]: round(total_budget * (raw[i] / s), 2) for i in range(n)}
    return alloc

# ---------------- RUN ----------------
if run_btn:
    skus = parse_skus(sku_input)
    if not skus:
        st.error("Provide at least one Advertised SKU (comma separated).")
        st.stop()

    keywords = parse_keywords(uploaded_kw)
    if top_n_kw and top_n_kw > 0:
        keywords = keywords[:top_n_kw] if keywords else keywords

    asins = parse_asins(asin_input)
    base_bid = calc_base_bid(price, acos, cvr)
    st.success(f"Calculated Strategic Base Bid: AED {base_bid:.2f}")

    # ensure campaign_types is defined
    if 'campaign_types' not in locals() or not campaign_types:
        campaign_types = ["Auto","Manual: Keywords"]

    # allocate budgets based on order
    allocation = allocate_budget_by_priority(total_daily_budget, campaign_types)
    st.info("Budget allocation per campaign (priority order): " + ", ".join([f"{k}: AED {v:.2f}" for k,v in allocation.items()]))

    entities = []
    ts = datetime.date.today().strftime("%Y%m%d")
    end_ts = ""

    for tactic in campaign_types:
        advertised_sku = skus[0]
        campaign_id = f"ZEN_{advertised_sku}_{tactic.replace(' ','')}"
        adgroup_id = f"{campaign_id}_AG"
        campaign_name = campaign_id
        adgroup_name = adgroup_id

        # Campaign row -> Daily Budget = allocated budget for this tactic
        campaign_row = {
            "Product":"Sponsored Products","Entity":"Campaign","Operation":"Create",
            "Campaign ID":campaign_id,"Ad Group ID":"",
            "Campaign Name":campaign_name,"Ad Group Name":"",
            "Start Date":ts,"End Date":end_ts,"Targeting Type":"",
            "State":"enabled","Daily Budget":f"{allocation.get(tactic, 0.0):.2f}",
            "SKU":"","Bidding Strategy": bid_mode if 'bid_mode' in locals() else "",
            "Tactic":tactic
        }
        append_row_dict(entities, campaign_row)

        # Ad Group row (SKU MUST BE BLANK here per change request)
        adgroup_row = {
            "Product":"Sponsored Products","Entity":"Ad Group","Operation":"Create",
            "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
            "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
            "Start Date":ts,"End Date":end_ts,
            "Targeting Type":"Auto" if tactic=="Auto" else "Manual",
            "State":"enabled","Daily Budget":"","SKU":"",
            "Ad Group Default Bid":f"{base_bid:.2f}","Bidding Strategy":"",
            "Tactic":tactic
        }
        append_row_dict(entities, adgroup_row)

        # Product Ad row -> SKU must be the advertised SKU (only place SKU is populated)
        product_ad_row = {
            "Product":"Sponsored Products","Entity":"Product Ad","Operation":"Create",
            "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
            "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
            "Start Date":ts,"End Date":end_ts,
            "Targeting Type":"Auto" if tactic=="Auto" else "Manual",
            "State":"enabled","Daily Budget":"","SKU":advertised_sku,
            "Ad Group Default Bid":f"{base_bid:.2f}","Bidding Strategy":"",
            "Tactic":tactic
        }
        append_row_dict(entities, product_ad_row)

        # Targeting rows (ensure SKU blank for targeting rows per request)
        if tactic == "Auto":
            chosen_pt = auto_pt_choices if (use_auto_pt and auto_pt_choices) else (list(AUTO_PT_MULTIPLIERS.keys()) if use_auto_pt else [])
            if chosen_pt:
                for pt in chosen_pt:
                    mult = AUTO_PT_MULTIPLIERS.get(pt, 1.0)
                    bid_val = round(base_bid * mult, 2)
                    row = {
                        "Product":"Sponsored Products","Entity":"Product Targeting","Operation":"Create",
                        "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                        "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                        "Start Date":ts,"End Date":end_ts,"Targeting Type":"Auto",
                        "State":"enabled","Daily Budget":"","SKU":"",
                        "Ad Group Default Bid":f"{base_bid:.2f}","Bid":f"{bid_val:.2f}",
                        "Product Targeting Expression": f'TYPE="{pt}"',"Bidding Strategy":"",
                        "Tactic":f"Auto-{pt}"
                    }
                    append_row_dict(entities, row)
            else:
                append_row_dict(entities, {
                    "Product":"Sponsored Products","Entity":"Auto","Operation":"Create",
                    "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                    "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                    "Start Date":ts,"End Date":end_ts,"Targeting Type":"Auto",
                    "State":"enabled","Daily Budget":"","SKU":"",
                    "Ad Group Default Bid":f"{base_bid:.2f}","Bidding Strategy":"",
                    "Tactic":"Auto"
                })

        elif tactic == "Manual: Keywords":
            kw_list = keywords if keywords else ["coffee mug","travel mug","tumbler","insulated bottle","leakproof bottle"]
            e_n = int(exact_top) if 'exact_top' in locals() else DEFAULT_EXACT_TOP
            p_n = int(phrase_next) if 'phrase_next' in locals() else DEFAULT_PHRASE_NEXT
            idx = 0
            # exacts
            for i in range(min(e_n, max(0, len(kw_list)-idx))):
                kw = kw_list[idx]; idx += 1
                bid = round(base_bid * 1.2, 2)
                append_row_dict(entities, {
                    "Product":"Sponsored Products","Entity":"Keyword","Operation":"Create",
                    "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                    "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                    "Start Date":ts,"End Date":end_ts,"Targeting Type":"Manual",
                    "State":"enabled","Daily Budget":"","SKU":"",
                    "Ad Group Default Bid":f"{base_bid:.2f}","Bid":f"{bid:.2f}",
                    "Keyword Text":kw,"Match Type":"exact","Bidding Strategy":"",
                    "Tactic":"Manual-Keywords"
                })
            # phrase
            for i in range(min(p_n, max(0, len(kw_list)-idx))):
                kw = kw_list[idx]; idx += 1
                bid = round(base_bid * 1.0, 2)
                append_row_dict(entities, {
                    "Product":"Sponsored Products","Entity":"Keyword","Operation":"Create",
                    "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                    "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                    "Start Date":ts,"End Date":end_ts,"Targeting Type":"Manual",
                    "State":"enabled","Daily Budget":"","SKU":"",
                    "Ad Group Default Bid":f"{base_bid:.2f}","Bid":f"{bid:.2f}",
                    "Keyword Text":kw,"Match Type":"phrase","Bidding Strategy":"",
                    "Tactic":"Manual-Keywords"
                })
            # broad
            while idx < len(kw_list):
                kw = kw_list[idx]; idx += 1
                bid = round(base_bid * 0.8, 2)
                append_row_dict(entities, {
                    "Product":"Sponsored Products","Entity":"Keyword","Operation":"Create",
                    "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                    "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                    "Start Date":ts,"End Date":end_ts,"Targeting Type":"Manual",
                    "State":"enabled","Daily Budget":"","SKU":"",
                    "Ad Group Default Bid":f"{base_bid:.2f}","Bid":f"{bid:.2f}",
                    "Keyword Text":kw,"Match Type":"broad","Bidding Strategy":"",
                    "Tactic":"Manual-Keywords"
                })

        elif tactic == "Manual: ASIN/Product":
            if not asins:
                append_row_dict(entities, {
                    "Product":"Sponsored Products","Entity":"Product Targeting","Operation":"Create",
                    "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                    "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                    "Start Date":ts,"End Date":end_ts,"Targeting Type":"Manual",
                    "State":"enabled","Daily Budget":"","SKU":"",
                    "Ad Group Default Bid":f"{base_bid:.2f}","Bid":f"{round(base_bid*1.1,2):.2f}",
                    "Product Targeting Expression":'ASIN="B0XXXXXX"',"Bidding Strategy":"",
                    "Tactic":"Manual-ASIN"
                })
            else:
                for a in asins:
                    append_row_dict(entities, {
                        "Product":"Sponsored Products","Entity":"Product Targeting","Operation":"Create",
                        "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                        "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                        "Start Date":ts,"End Date":end_ts,"Targeting Type":"Manual",
                        "State":"enabled","Daily Budget":"","SKU":"",
                        "Ad Group Default Bid":f"{base_bid:.2f}","Bid":f"{round(base_bid*1.1,2):.2f}",
                        "Product Targeting Expression":f'ASIN="{a}"',"Bidding Strategy":"",
                        "Tactic":"Manual-ASIN"
                    })

        elif tactic == "Category":
            append_row_dict(entities, {
                "Product":"Sponsored Products","Entity":"Product Targeting","Operation":"Create",
                "Campaign ID":campaign_id,"Ad Group ID":adgroup_id,
                "Campaign Name":campaign_name,"Ad Group Name":adgroup_name,
                "Start Date":ts,"End Date":end_ts,"Targeting Type":"Manual",
                "State":"enabled","Daily Budget":"","SKU":"",
                "Ad Group Default Bid":f"{base_bid:.2f}","Bid":f"{round(base_bid*1.0,2):.2f}",
                "Product Targeting Expression":'category="ENTER_CATEGORY_ID"',"Bidding Strategy":"",
                "Tactic":"Category"
            })

    # Build DataFrame and ensure SKU column rule
    df_bulk = pd.DataFrame(entities, columns=COLUMN_ORDER)
    # Sanity: set SKU empty everywhere except Product Ad rows
    df_bulk['SKU'] = df_bulk.apply(lambda r: r['SKU'] if str(r['Entity']).strip().lower() == 'product ad' else "", axis=1)

    st.markdown("### Preview (first 200 rows)")
    st.dataframe(df_bulk.head(200))

    # Export
    metadata = {
        "generated_at": datetime.datetime.now().isoformat(),
        "advertised_skus": ",".join(sk for sk in skus),
        "num_rows": len(df_bulk),
        "campaign_types": ",".join(campaign_types),
        "base_bid": f"{base_bid:.2f}",
        "total_daily_budget": f"{total_daily_budget:.2f}"
    }
    excel_bytes = to_excel_with_metadata(df_bulk, metadata)
    st.download_button("Export bulk sheet (.xlsx)", excel_bytes, file_name=f"ppc_bulk_{datetime.date.today().isoformat()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # Counts chart
    if 'Tactic' in df_bulk.columns:
        counts = df_bulk['Tactic'].value_counts().reset_index()
        counts.columns = ['Tactic','Rows']
        if not counts.empty:
            fig = go.Figure([go.Bar(x=counts['Tactic'], y=counts['Rows'], marker_color=BRAND_PRIMARY)])
            fig.update_layout(title="Rows per Tactic", template="plotly_dark", xaxis_title="Tactic", yaxis_title="Rows")
            st.plotly_chart(fig, use_container_width=True)

    st.success("Bulk sheet generated. QA before uploading to Amazon.")

st.markdown("---")
st.caption("Notes: Always review category and ASIN expressions before upload. SKU column is populated only for Product Ad rows as requested.")