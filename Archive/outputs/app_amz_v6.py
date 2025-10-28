import streamlit as st
import pandas as pd, re, os
from io import BytesIO
from datetime import date, datetime
from pathlib import Path

st.set_page_config(page_title="S2C PPC Bulk Generator (AMZ v6)", layout="wide")

# minimal helpers (load excel/csv, fuzzy find)
def load_any(uploaded_file):
    uploaded_file.seek(0)
    name = uploaded_file.name.lower()
    if name.endswith(('.xlsx','.xls')):
        xls = pd.ExcelFile(uploaded_file)
        for s in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=s, dtype=str)
            if not df.empty:
                return df.fillna("")
        return pd.DataFrame()
    else:
        return pd.read_csv(uploaded_file, dtype=str, encoding_errors="ignore").fillna("")

def fuzzy_find_column(df, candidates):
    for c in df.columns:
        lc = c.lower()
        for cand in candidates:
            if cand in lc:
                return c
    return None

def to_yyyymmdd(val):
    if val is None: return ""
    s = str(val).strip()
    if s=="" or s.lower()=="nan": return ""
    # try common parses
    try:
        if re.match(r'^\d{8}$', s):
            return s
        if '-' in s:
            dt = datetime.fromisoformat(s)
            return dt.strftime("%Y%m%d")
        for fmt in ("%m/%d/%y","%m/%d/%Y","%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y%m%d")
            except: pass
    except:
        pass
    digits = re.findall(r'\d+', s)
    concat = ''.join(digits)
    if len(concat)>=8: return concat[:8]
    return s

AMZ_COLS = ['Product','Entity','Operation','Campaign ID','Ad Group ID','Portfolio ID','Ad ID','Keyword ID','Product Targeting ID','Campaign Name','Ad Group Name','Start Date','End Date','Targeting Type','State','Daily Budget','SKU','Ad Group Default Bid','Bid','Keyword Text','Native Language Keyword','Native Language Locale','Match Type','Bidding Strategy','Placement','Percentage','Product Targeting Expression','Audience ID','Shopper Cohort Percentage','Shopper Cohort Type']

st.title("S2C PPC Bulk Generator — Amazon v6 export")

left, right = st.columns([1,2])
with left:
    prod_file = st.file_uploader("Products master (CSV/XLSX)", type=['csv','xlsx','xls'], key='prod')
    cere_file = st.file_uploader("Keywords (Cerebro/listing export)", type=['csv','xlsx','xls'], key='cere')
    pricing_file = st.file_uploader("Competitor pricing (contains ASINs)", type=['csv','xlsx','xls'], key='price')
    paste_asins = st.text_area("Paste ASINs (optional)", height=80)
    top_k = st.number_input("Top K keywords per SKU", value=20, min_value=1)
    top_asins = st.number_input("Top N ASINs per SKU", value=10, min_value=1)
    dup_phrase_broad = st.checkbox("Duplicate phrase -> broad", value=False)
    broad_mult = st.number_input("Broad multiplier", value=0.75, min_value=0.1, max_value=1.0)
    generate = st.button("Generate AMZ v6 XLSX")

with right:
    status = st.empty()
    preview = st.empty()

def extract_asins_from_pricing(df):
    if df is None or df.empty: return []
    col = fuzzy_find_column(df, ['asin','product asin','seller asin','competitor asin'])
    if col:
        return [str(x).strip().upper() for x in df[col].dropna().astype(str).unique() if str(x).strip()!='']
    # fallback scan
    vals = [str(x).strip() for x in df.values.flatten() if isinstance(x,str)]
    cand = [v for v in vals if re.match(r'^[A-Za-z0-9]{6,}$', v)]
    return list(pd.unique([c.upper() for c in cand]))

def extract_kw_from_cere(df, kw_col):
    if df is None or df.empty or not kw_col: return []
    kws = df[kw_col].astype(str).str.strip().tolist()
    return [k for k in kws if k!='']

if generate:
    if not prod_file:
        status.error("Upload products master first")
        st.stop()
    prod_df = load_any(prod_file)
    cere_df = load_any(cere_file) if cere_file else pd.DataFrame()
    pricing_df = load_any(pricing_file) if pricing_file else pd.DataFrame()

    # detect columns
    sku_col = fuzzy_find_column(prod_df, ['sku','sku id','product sku','seller sku']) or prod_df.columns[0]
    asin_col = fuzzy_find_column(prod_df, ['asin','product asin','seller asin'])
    title_col = fuzzy_find_column(prod_df, ['title','name','product title'])
    brand_col = fuzzy_find_column(prod_df, ['brand'])

    kw_col = fuzzy_find_column(cere_df, ['keyword','search term','phrase']) if not cere_df.empty else None
    match_col = fuzzy_find_column(cere_df, ['match','match type']) if not cere_df.empty else None
    bid_col = fuzzy_find_column(cere_df, ['suggested','suggested bid','bid']) if not cere_df.empty else None

    pasted_asins = [s.strip().upper() for s in re.split(r'[,\n\r\s]+', paste_asins) if s.strip()] if paste_asins else []
    pricing_asins = extract_asins_from_pricing(pricing_df)
    # build rows
    rows = []
    for _, p in prod_df.iterrows():
        sku = str(p.get(sku_col,"")).strip()
        prod_asin = str(p.get(asin_col,"")).strip() if asin_col else ""
        title = str(p.get(title_col,"")).strip() if title_col else sku
        brand = str(p.get(brand_col,"")).strip() if brand_col else "S2C"
        if not sku: continue
        campaign = f"{brand}_{sku}_Manual"
        # Campaign row
        camp_row = {c:"" for c in AMZ_COLS}
        camp_row['Product'] = 'Sponsored Products'
        camp_row['Entity'] = 'Campaign'
        camp_row['Operation'] = 'Create'
        camp_row['Campaign Name'] = campaign
        camp_row['Start Date'] = date.today().strftime("%Y%m%d")
        camp_row['Targeting Type'] = 'Manual'
        camp_row['State'] = 'enabled'
        camp_row['Daily Budget'] = 50
        rows.append(camp_row)
        # Ad Group row
        ag_name = f"KW_{sku}_phrase"
        ag_row = {c:"" for c in AMZ_COLS}
        ag_row['Product'] = 'Sponsored Products'
        ag_row['Entity'] = 'Ad Group'
        ag_row['Operation'] = 'Create'
        ag_row['Campaign Name'] = campaign
        ag_row['Ad Group Name'] = ag_name
        ag_row['State'] = 'enabled'
        ag_row['Ad Group Default Bid'] = 1.0
        rows.append(ag_row)
        # seed keyword exact row
        seed_kw = (title.split("–")[0] if "–" in title else title.split("-")[0]).strip()
        kwrow = {c:"" for c in AMZ_COLS}
        kwrow['Product']='Sponsored Products'; kwrow['Entity']='Keyword'; kwrow['Operation']='Create'
        kwrow['Campaign Name']=campaign; kwrow['Ad Group Name']=ag_name; kwrow['State']='enabled'
        kwrow['Keyword Text']=seed_kw; kwrow['Match Type']='exact'; kwrow['Bid']=1.5; kwrow['SKU']=sku
        rows.append(kwrow)
        # keywords from cerebro
        if not cere_df.empty and kw_col:
            kws = extract_kw_from_cere(cere_df, kw_col)[:int(top_k)]
            for k in kws:
                krow = {c:"" for c in AMZ_COLS}
                krow['Product']='Sponsored Products'; krow['Entity']='Keyword'; krow['Operation']='Create'
                krow['Campaign Name']=campaign; krow['Ad Group Name']=ag_name; krow['State']='enabled'
                krow['Keyword Text']=k; krow['Match Type']='phrase'; krow['Bid']=1.0; krow['SKU']=sku
                rows.append(krow)
                if dup_phrase_broad:
                    brow = krow.copy(); brow['Match Type']='broad'; brow['Bid']=round(float(krow['Bid'])*float(broad_mult),4)
                    rows.append(brow)
        # product targeting ad group
        pt_ag = f"PT_{sku}"
        pt_ag_row = {c:"" for c in AMZ_COLS}
        pt_ag_row['Product']='Sponsored Products'; pt_ag_row['Entity']='Ad Group'; pt_ag_row['Operation']='Create'
        pt_ag_row['Campaign Name']=campaign; pt_ag_row['Ad Group Name']=pt_ag; pt_ag_row['State']='enabled'; pt_ag_row['Ad Group Default Bid']=0.75
        rows.append(pt_ag_row)
        # product targeting rows
        comp_asins = pasted_asins or pricing_asins
        comp_asins = [a for a in comp_asins if a and a!=prod_asin][:int(top_asins)]
        for a in comp_asins:
            ptr = {c:"" for c in AMZ_COLS}
            ptr['Product']='Sponsored Products'; ptr['Entity']='Product Targeting'; ptr['Operation']='Create'
            ptr['Campaign Name']=campaign; ptr['Ad Group Name']=pt_ag; ptr['State']='enabled'; ptr['SKU']=sku
            ptr['Product Targeting Expression'] = f"asin:{a.upper()}"
            ptr['Bid'] = 0.8
            rows.append(ptr)

    df_out = pd.DataFrame(rows, columns=AMZ_COLS)
    preview.subheader("Preview (first 40 rows)")
    preview.dataframe(df_out.head(40))
    # save xlsx to outputs
    outdir = Path.cwd() / "outputs_amz_v6"
    outdir.mkdir(exist_ok=True)
    out_path = outdir / f"ppc_amz_v6_{date.today().isoformat()}.xlsx"
    df_out.to_excel(out_path, index=False)
    st.success(f"Saved: {out_path}")
    with open(out_path, "rb") as f:
        st.download_button("Download AMZ v6 XLSX", f.read(), file_name=out_path.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
