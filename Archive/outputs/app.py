# app.py
import streamlit as st
import pandas as pd
import re
from io import BytesIO
from datetime import date
import os

st.set_page_config(page_title="S2C PPC Bulk Generator (Multi-SKU)", layout="wide")

# ---------- Helpers ----------
def load_any(uploaded_file):
    """Read CSV or Excel from Streamlit uploader into DataFrame."""
    name = uploaded_file.name.lower()
    uploaded_file.seek(0)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        xls = pd.ExcelFile(uploaded_file)
        for s in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=s, dtype=str)
            if not df.empty:
                return df.fillna("")
        return pd.DataFrame()
    else:
        return pd.read_csv(uploaded_file, dtype=str, encoding_errors="ignore").fillna("")

def fuzzy_find_column(df, candidates):
    cols = list(df.columns)
    for c in cols:
        lc = c.lower()
        for cand in candidates:
            if cand in lc:
                return c
    return None

def short_adgroup(s):
    return re.sub(r"[^A-Za-z0-9_]", "_", (s or ""))[:30]

def make_unique_campaigns(df):
    if df.empty:
        return df
    df = df.copy()
    df["Ad Group Safe"] = df.get("Ad Group", "").astype(str).apply(short_adgroup)
    df["Campaign"] = df.apply(lambda r: f"{str(r.get('Campaign',''))}_{r['Ad Group Safe']}", axis=1)
    df = df.drop(columns=["Ad Group Safe"])
    return df

def df_to_bytes(df):
    b = BytesIO()
    df.to_csv(b, index=False, encoding="utf-8")
    b.seek(0)
    return b

def extract_asins_from_pricing(df_pricing):
    if df_pricing is None or df_pricing.empty:
        return []
    asin_cands = ["asin", "product asin", "seller asin", "competitor asin", "sku_asin", "product_asin", "item asin"]
    col = fuzzy_find_column(df_pricing, asin_cands)
    if col:
        vals = df_pricing[col].astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
        return vals
    all_vals = [str(x).strip() for x in df_pricing.values.flatten() if isinstance(x, str)]
    candidates = [v for v in all_vals if re.match(r"^[A-Z0-9]{6,}$", v)]
    return list(pd.unique(candidates))

def extract_asins_from_cerebro(df_cere, rank_limit=10):
    if df_cere is None or df_cere.empty:
        return []
    asin_col = fuzzy_find_column(df_cere, ["sourceasin", "asin", "competitor", "product asin"])
    rank_col = fuzzy_find_column(df_cere, ["rank", "position", "pos"])
    if asin_col:
        tmp = pd.DataFrame({"ASIN": df_cere[asin_col].astype(str)})
        if rank_col and rank_col in df_cere.columns:
            tmp[rank_col] = df_cere[rank_col]
            tmp = tmp[pd.to_numeric(tmp[rank_col], errors="coerce").notnull()]
            tmp = tmp.sort_values(rank_col)
        tmp = tmp[tmp["ASIN"].str.strip() != ""]
        return list(pd.unique(tmp["ASIN"]))[:rank_limit]
    all_vals = [str(x).strip() for x in df_cere.values.flatten() if isinstance(x, str)]
    candidates = [v for v in all_vals if re.match(r"^[A-Z0-9]{6,}$", v)]
    return list(pd.unique(candidates))[:rank_limit]

# ---------- UI ----------
st.title("S2C PPC Bulk Generator — Multi-SKU (Smart autodetect)")

left, right = st.columns([1, 2])

with left:
    st.subheader("Uploads (any CSV / Excel)")
    prod_file = st.file_uploader("Products master (CSV/XLSX) — SKU,ASIN,Title,Brand,DefaultBid (multi-row ok)", type=["csv","xlsx","xls"], key="prod")
    keyword_file = st.file_uploader("Keywords file (Cerebro / Listing export)", type=["csv","xlsx","xls"], key="cere")
    pricing_file = st.file_uploader("Competitor pricing / tracker (contains ASINs) — optional", type=["csv","xlsx","xls"], key="pricing")

    st.markdown("**Or** paste ASINs for product-targeting (comma / newline separated):")
    comp_paste = st.text_area("Paste ASINs", placeholder="B0ABC...,B0DEF..., ...", height=80)

    st.markdown("---")
    st.subheader("Campaign toggles & defaults")
    c1, c2 = st.columns(2)
    with c1:
        enable_auto = st.checkbox("Enable Auto", value=True)
        enable_manual = st.checkbox("Enable Manual", value=True)
        enable_pt = st.checkbox("Enable Product Targeting", value=True)
        enable_neg = st.checkbox("Enable Negatives", value=True)
    with c2:
        budget_auto = st.number_input("Budget Auto", value=20.0, step=1.0)
        budget_manual = st.number_input("Budget Manual", value=50.0, step=1.0)
        budget_pt = st.number_input("Budget PT", value=30.0, step=1.0)

    st.markdown("**Bids**")
    bid_auto = st.number_input("Bid Auto", value=0.6, step=0.1)
    bid_exact = st.number_input("Bid Exact", value=1.5, step=0.1)
    bid_phrase = st.number_input("Bid Phrase", value=1.0, step=0.1)
    bid_broad = st.number_input("Bid Broad", value=0.5, step=0.1)

    st.markdown("**Limits**")
    top_k = st.number_input("Top K keywords per SKU", value=20, min_value=1, step=1)
    top_asins = st.number_input("Top N competitor ASINs (product-target)", value=10, min_value=1, step=1)

    st.markdown("---")
    operator = st.text_input("Operator name (run_log)", value="Faisal")
    # NEW: duplicate phrase -> broad toggle and multiplier
    duplicate_phrase_as_broad = st.checkbox("Duplicate Phrase as Broad (discovery)", value=False)
    broad_multiplier = st.number_input("Broad bid multiplier (phrase→broad)", value=0.75, min_value=0.1, max_value=1.0, step=0.05)

    generate_btn = st.button("Generate PPC Files")

with right:
    status = st.empty()
    samples = st.empty()
    preview = st.empty()
    neg_preview = st.empty()
    downloads = st.empty()
    run_info = st.empty()

# ---------- Action ----------
if generate_btn:
    if prod_file is None:
        status.error("Upload products master file (required).")
        st.stop()

    try:
        prod_df = load_any(prod_file)
    except Exception as e:
        status.error(f"Failed reading products file: {e}")
        st.stop()

    cere_df = pd.DataFrame()
    pricing_df = pd.DataFrame()
    try:
        if keyword_file:
            cere_df = load_any(keyword_file)
        if pricing_file:
            pricing_df = load_any(pricing_file)
    except Exception as e:
        status.error(f"Failed reading uploaded file(s): {e}")
        st.stop()

    prod_cols = list(prod_df.columns)
    sku_col = fuzzy_find_column(prod_df, ["sku", "sku id", "product sku", "item"])
    asin_col_prod = fuzzy_find_column(prod_df, ["asin", "product asin", "seller asin"])
    title_col = fuzzy_find_column(prod_df, ["title", "name", "product title"])
    brand_col = fuzzy_find_column(prod_df, ["brand"])
    defaultbid_col = fuzzy_find_column(prod_df, ["defaultbid", "default bid", "bid"])

    if sku_col is None or asin_col_prod is None:
        status.error(f"products_master missing required columns (detected columns: {prod_cols}). Ensure it contains SKU and ASIN columns.")
        st.stop()

    status.info(f"Products master columns detected: SKU='{sku_col}', ASIN='{asin_col_prod}', Title='{title_col}', Brand='{brand_col}', DefaultBid='{defaultbid_col}'")

    keyword_col = None
    match_col = None
    suggested_bid_col = None
    if not cere_df.empty:
        keyword_col = fuzzy_find_column(cere_df, ["keyword", "keyword phrase", "search term", "searchphrase", "phrase"])
        match_col = fuzzy_find_column(cere_df, ["match", "match type"])
        suggested_bid_col = fuzzy_find_column(cere_df, ["suggested", "suggested bid", "bid"])
        status.info(f"Keywords file detected columns: keyword='{keyword_col}', match='{match_col}', suggested_bid='{suggested_bid_col}'")
    else:
        status.info("No keywords file uploaded — manual keywords only (seed from product title).")

    pasted_asins = []
    if comp_paste and str(comp_paste).strip():
        pasted_asins = [s.strip() for s in re.split(r"[,\n\r\s]+", comp_paste) if s.strip()]

    pricing_asins = extract_asins_from_pricing(pricing_df) if not pricing_df.empty else []
    cerebro_asins = extract_asins_from_cerebro(cere_df, rank_limit=int(top_asins)) if not cere_df.empty else []

    status.info(f"ASIN sources: pasted={len(pasted_asins)}, pricing_file={len(pricing_asins)}, cerebro_auto={len(cerebro_asins)}")
    sample_text = {
        "pasted_head": pasted_asins[:10],
        "pricing_head": pricing_asins[:10],
        "cerebro_head": cerebro_asins[:10]
    }
    samples.json(sample_text)

    rows = []
    negs = []
    today = date.today().isoformat()

    for _, p in prod_df.iterrows():
        sku = str(p.get(sku_col, "")).strip()
        prod_asin = str(p.get(asin_col_prod, "")).strip()
        title = str(p.get(title_col, "")).strip() if title_col else sku
        brand = str(p.get(brand_col, "")).strip() if brand_col else "S2C"
        try:
            default_bid = float(str(p.get(defaultbid_col, "")).strip()) if defaultbid_col and str(p.get(defaultbid_col, "")).strip()!="" else float(bid_exact)
        except:
            default_bid = float(bid_exact)

        if not sku or not prod_asin:
            status.warning(f"Skipping row with missing SKU/ASIN: sku='{sku}', asin='{prod_asin}'")
            continue

        # Auto
        if enable_auto:
            rows.append({
                "Campaign Type":"Auto",
                "Campaign":f"{brand}_{sku}_Auto",
                "Campaign Daily Budget": budget_auto,
                "Campaign Start Date": today,
                "Campaign End Date": "",
                "Campaign Targeting Type":"Auto",
                "Campaign Strategy":"Legacy",
                "Ad Group":f"Auto_{sku}",
                "Max Bid": bid_auto,
                "Keyword/ASIN": "",
                "Match Type": "",
                "SKU": sku,
                "State":"enabled",
                "Placement": "",
                "Custom Label 1":"",
                "Source":"user",
                "Notes":"auto harvest"
            })

        # Manual
        if enable_manual:
            seed_kw = (title.split("–")[0] if "–" in title else title.split("-")[0]).strip() or sku
            rows.append({
                "Campaign Type":"Manual",
                "Campaign":f"{brand}_{sku}_Manual",
                "Campaign Daily Budget": budget_manual,
                "Campaign Start Date": today,
                "Campaign End Date":"",
                "Campaign Targeting Type":"Manual",
                "Campaign Strategy":"Legacy",
                "Ad Group":f"KW_{sku}_Exact",
                "Max Bid": default_bid,
                "Keyword/ASIN": seed_kw,
                "Match Type":"exact",
                "SKU":sku,
                "State":"enabled",
                "Placement":"",
                "Custom Label 1":"seed",
                "Source":"user",
                "Notes":"seed from title"
            })

            if not cere_df.empty and keyword_col:
                kw_df = cere_df.copy()
                kw_df = kw_df[kw_df[keyword_col].astype(str).str.strip() != ""]
                kw_selected = kw_df.head(int(top_k))
                for _, kr in kw_selected.iterrows():
                    kw = str(kr.get(keyword_col, "")).strip()
                    mtype = str(kr.get(match_col, "")).strip().lower() if match_col else "phrase"
                    if mtype not in ("exact","phrase","broad"):
                        mtype = "phrase"
                    sb = kr.get(suggested_bid_col, "")
                    try:
                        bid = float(str(sb)) if sb not in ("", None) else (float(bid_phrase) if mtype=="phrase" else float(bid_broad))
                    except:
                        bid = float(bid_phrase) if mtype=="phrase" else float(bid_broad)

                    # Primary row
                    rows.append({
                        "Campaign Type":"Manual",
                        "Campaign":f"{brand}_{sku}_Manual",
                        "Campaign Daily Budget": budget_manual,
                        "Campaign Start Date": today,
                        "Campaign End Date":"",
                        "Campaign Targeting Type":"Manual",
                        "Campaign Strategy":"Legacy",
                        "Ad Group":f"KW_{sku}_{mtype}",
                        "Max Bid": bid,
                        "Keyword/ASIN": kw,
                        "Match Type": mtype,
                        "SKU":sku,
                        "State":"enabled",
                        "Placement":"",
                        "Custom Label 1":"cerebro",
                        "Source":"cerebro",
                        "Notes":"seeded from Cerebro"
                    })

                    # Duplicate phrase -> broad
                    if duplicate_phrase_as_broad and mtype == "phrase":
                        broad_bid = round(bid * float(broad_multiplier), 4)
                        rows.append({
                            "Campaign Type":"Manual",
                            "Campaign":f"{brand}_{sku}_Manual",
                            "Campaign Daily Budget": budget_manual,
                            "Campaign Start Date": today,
                            "Campaign End Date":"",
                            "Campaign Targeting Type":"Manual",
                            "Campaign Strategy":"Legacy",
                            "Ad Group":f"KW_{sku}_broad",
                            "Max Bid": broad_bid,
                            "Keyword/ASIN": kw,
                            "Match Type": "broad",
                            "SKU":sku,
                            "State":"enabled",
                            "Placement":"",
                            "Custom Label 1":"cerebro",
                            "Source":"cerebro_broad",
                            "Notes":"auto-generated broad from phrase"
                        })

        # Product Targeting
        if enable_pt:
            comp_asins = []
            if pasted_asins:
                comp_asins = pasted_asins
            elif pricing_asins:
                comp_asins = pricing_asins
            elif cerebro_asins:
                comp_asins = cerebro_asins

            comp_asins = [str(x).strip() for x in comp_asins if str(x).strip() and str(x).strip()!=prod_asin]
            comp_asins = list(pd.unique(comp_asins))[:int(top_asins)]

            if comp_asins:
                status.info(f"SKU {sku}: using {len(comp_asins)} competitor ASINs (sample: {comp_asins[:6]})")

            for ca in comp_asins:
                rows.append({
                    "Campaign Type":"ProductTargeting",
                    "Campaign":f"{brand}_{sku}_PT",
                    "Campaign Daily Budget": budget_pt,
                    "Campaign Start Date": today,
                    "Campaign End Date":"",
                    "Campaign Targeting Type":"Product",
                    "Campaign Strategy":"Legacy",
                    "Ad Group":f"PT_{sku}",
                    "Max Bid": bid_broad,
                    "Keyword/ASIN": ca,
                    "Match Type": "",
                    "SKU": sku,
                    "State":"enabled",
                    "Placement":"",
                    "Custom Label 1":"pt_comp",
                    "Source":"comp_list" if (pasted_asins or pricing_asins) else "cerebro_auto",
                    "Notes":"target competitor ASIN"
                })

        # Negatives
        if enable_neg:
            neg_list = ["cheap lunch box","free lunch box","replacement lid"]
            for n in neg_list:
                negs.append({
                    "Campaign Type":"Negative",
                    "Campaign":f"{brand}_{sku}_Negs",
                    "Campaign Daily Budget": budget_manual,
                    "Campaign Start Date": today,
                    "Campaign End Date":"",
                    "Campaign Targeting Type":"Manual",
                    "Campaign Strategy":"Legacy",
                    "Ad Group":f"Neg_{sku}",
                    "Max Bid": 0,
                    "Keyword/ASIN": n,
                    "Match Type":"broad",
                    "SKU":sku,
                    "State":"enabled",
                    "Placement":"",
                    "Custom Label 1":"auto_neg",
                    "Source":"user",
                    "Notes":"auto-neg list"
                })

    # finalize
    if rows:
        df_bulk = pd.DataFrame(rows)
        df_bulk = make_unique_campaigns(df_bulk)
    else:
        df_bulk = pd.DataFrame(columns=['Campaign Type','Campaign','Campaign Daily Budget','Campaign Start Date','Campaign End Date','Campaign Targeting Type','Campaign Strategy','Ad Group','Max Bid','Keyword/ASIN','Match Type','SKU','State','Placement','Custom Label 1','Source','Notes'])

    if negs:
        df_neg = pd.DataFrame(negs)
        df_neg = make_unique_campaigns(df_neg)
    else:
        df_neg = pd.DataFrame(columns=df_bulk.columns)

    preview.subheader("Bulk CSV preview (first 15 rows)")
    preview.dataframe(df_bulk.head(15), use_container_width=True)
    neg_preview.subheader("Negatives preview (first 12 rows)")
    neg_preview.dataframe(df_neg.head(12), use_container_width=True)

    bulk_bytes = df_to_bytes(df_bulk)
    neg_bytes = df_to_bytes(df_neg)

    downloads.write("### Download generated files")
    downloads.download_button("Download Bulk CSV", data=bulk_bytes, file_name=f"ppc_bulk_{date.today().isoformat()}.csv", mime="text/csv")
    downloads.download_button("Download Negatives CSV", data=neg_bytes, file_name=f"ppc_negative_{date.today().isoformat()}.csv", mime="text/csv")

    run_info.write(f"Operator: {operator}  •  SKUs processed: {len(pd.unique(prod_df[sku_col].astype(str)))}  •  Bulk rows: {len(df_bulk)}  •  Neg rows: {len(df_neg)}")
    outdir = os.path.join(os.getcwd(), "outputs")
    os.makedirs(outdir, exist_ok=True)
    df_bulk.to_csv(os.path.join(outdir, f"ppc_bulk_{date.today().isoformat()}.csv"), index=False)
    df_neg.to_csv(os.path.join(outdir, f"ppc_negative_{date.today().isoformat()}.csv"), index=False)
    status.success(f"Files saved to ./outputs and ready to download. Reviewed SKU samples shown above.")