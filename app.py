import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import gc
from datetime import timedelta, datetime, time
from io import BytesIO

# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="乱价监控看板",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 全局样式
# ============================================================
st.markdown(
    """
    <style>
    .stApp { background: #f5f7fa; }
    .alert-banner {
        background: linear-gradient(90deg, #7f1d1d 0%, #dc2626 100%);
        color: white; padding: 22px 30px; border-radius: 12px;
        margin-bottom: 18px; box-shadow: 0 4px 16px rgba(220,38,38,0.25);
        display: flex; align-items: center; gap: 30px;
    }
    .alert-banner.safe { background: linear-gradient(90deg, #14532d 0%, #16a34a 100%); box-shadow: 0 4px 16px rgba(22,163,74,0.25); }
    .alert-banner.warn { background: linear-gradient(90deg, #78350f 0%, #f59e0b 100%); box-shadow: 0 4px 16px rgba(245,158,11,0.25); }
    .alert-num { font-size: 52px; font-weight: 800; line-height: 1; min-width: 90px; text-align: center; }
    .alert-text { flex: 1; }
    .alert-title { font-size: 20px; font-weight: 700; margin-bottom: 6px; }
    .alert-desc { font-size: 14px; opacity: 0.92; line-height: 1.5; }
    .alert-action { background: rgba(255,255,255,0.2); padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; }
    .kpi-card { background: white; border-radius: 10px; padding: 18px 20px; border-left: 4px solid #3b82f6; box-shadow: 0 1px 4px rgba(0,0,0,0.06); height: 100%; }
    .kpi-card.danger { border-left-color: #dc2626; }
    .kpi-card.warn { border-left-color: #f59e0b; }
    .kpi-card.success { border-left-color: #16a34a; }
    .kpi-label { font-size: 13px; color: #64748b; margin-bottom: 6px; }
    .kpi-value { font-size: 28px; font-weight: 700; color: #0f172a; line-height: 1.2; }
    .kpi-sub { font-size: 12px; color: #94a3b8; margin-top: 6px; }
    .sev-critical { display: inline-block; background: #dc2626; color: white; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .sev-medium { display: inline-block; background: #f59e0b; color: white; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .sev-light { display: inline-block; background: #facc15; color: #422006; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .plat-badge { display: inline-block; padding: 2px 8px; border-radius: 8px; color: white; font-size: 11px; font-weight: 600; margin-right: 4px; }
    .shop-name { font-size: 17px; font-weight: 700; color: #0f172a; display: flex; align-items: center; gap: 10px; }
    .shop-stats { color: #64748b; font-size: 13px; margin-top: 4px; }
    .shop-amount { font-size: 20px; font-weight: 800; color: #dc2626; }
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 飞书配置
# ============================================================
APP_ID = st.secrets["feishu"]["app_id"]
APP_SECRET = st.secrets["feishu"]["app_secret"]
APP_TOKEN = st.secrets["feishu"]["app_token"]

FEISHU_TABLES = {
    "京东": {"table_id": "tblmispSYGtkWZbU"},
    "天猫": {"table_id": "tblB2s1GxLyltgOg"},
    "拼多多": {"table_id": "tbl31Jw9F8PFwzeH"},
}

FEISHU_BASE = "https://open.feishu.cn/open-apis"

FIELD_MAP = {
    "shop": "店铺", "platform": "平台", "product_category": "品类",
    "model": "型号", "product_link": "商品链接", "product_name": "页面产品名称",
    "company_limit_price": "公司限定价", "shop_final_price": "店铺到手价",
    "platform_display_price": "平台页面价", "record_date": "日期",
    "record_time": "记录时间",
}

SKU_KEY_CANDIDATES = [
    "SKU ID", "SKUID", "skuid", "sku_id", "skuId",
    "sku", "SKU", "SKU_ID", "skuID", "SkuId", "商品ID", "商品id", "产品ID",
]

PLATFORM_COLORS = {"京东": "#e53935", "天猫": "#fb8c00", "拼多多": "#8e24aa"}
PLATFORM_BADGE_HTML = {
    "京东": "<span class='plat-badge' style='background:#e53935;'>京东</span>",
    "天猫": "<span class='plat-badge' style='background:#fb8c00;'>天猫</span>",
    "拼多多": "<span class='plat-badge' style='background:#8e24aa;'>拼多多</span>",
}

BEIJING_TZ = "Asia/Shanghai"


# ============================================================
# 时间与 dtype 工具
# ============================================================
def convert_time_column(series: pd.Series) -> pd.Series:
    if series is None or len(series) == 0:
        return series
    if pd.api.types.is_numeric_dtype(series):
        try:
            result = pd.to_datetime(series, unit="ms", utc=True, errors="coerce")
            result = result.dt.tz_convert(BEIJING_TZ).dt.tz_localize(None)
            return result
        except Exception:
            return pd.to_datetime(series, errors="coerce")
    else:
        return pd.to_datetime(series, errors="coerce")


def optimize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """内存优化：数值列降级为 float32，重复度高的字符串列转为 category"""
    if df.empty:
        return df

    # 数值列降为 float32（原 float64 一半大小）
    for col in ["公司限定价", "店铺到手价", "平台页面价"]:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].astype("float32")

    # 高重复字符串列转为 category
    for col in ["平台", "品类", "店铺"]:
        if col in df.columns:
            # 先用 str 确保类型一致
            df[col] = df[col].astype(str).fillna("未知").astype("category")

    # 日期列确认是 datetime 类型
    for col in ["日期", "记录时间"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


# ============================================================
# 飞书 API
# ============================================================
@st.cache_resource(show_spinner=False)
def get_tenant_access_token() -> str:
    """token 用 cache_resource 缓存，避免重复申请"""
    url = f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": APP_ID, "app_secret": APP_SECRET}, timeout=15)
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {data}")
    return data["tenant_access_token"]


def _fetch_records_by_filter(token: str, table_id: str, start_date=None, end_date=None) -> list:
    """按日期范围拉取记录"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    records, page_token = [], None

    conditions = []
    if start_date:
        start_dt = datetime.combine(start_date, time.min)
        start_ms = str(int(start_dt.timestamp() * 1000))
        conditions.append({
            "field_name": "日期",
            "operator": "isGreater",
            "value": ["ExactDate", start_ms],
        })
    if end_date:
        end_dt = datetime.combine(end_date + timedelta(days=1), time.min)
        end_ms = str(int(end_dt.timestamp() * 1000))
        conditions.append({
            "field_name": "日期",
            "operator": "isLess",
            "value": ["ExactDate", end_ms],
        })

    url = f"{FEISHU_BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/search"

    while True:
        body = {"page_size": 500}
        if conditions:
            body["filter"] = {"conjunction": "and", "conditions": conditions}
        if page_token:
            body["page_token"] = page_token

        resp = requests.post(url, headers=headers, json=body, timeout=60)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"读取表 {table_id} 失败: {data.get('msg', data)}")
        records.extend(data.get("data", {}).get("items", []))
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data["data"].get("page_token")

    return records


@st.cache_data(ttl=1800, max_entries=2, show_spinner="正在加载数据...")
def load_data(start_date_str: str = None, end_date_str: str = None) -> pd.DataFrame:
    """
    按日期范围加载数据。
    缓存：30 分钟过期，最多缓存 2 份（防止内存堆积）
    """
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None

    token = get_tenant_access_token()
    frames = []
    for platform_name, cfg in FEISHU_TABLES.items():
        records = _fetch_records_by_filter(token, cfg["table_id"], start_date, end_date)
        if not records:
            continue
        rows = [{"_record_id": r.get("record_id", ""), **r.get("fields", {})} for r in records]
        df_p = pd.DataFrame(rows)
        df_p["_platform_source"] = platform_name
        frames.append(df_p)
        del records
        gc.collect()

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    del frames
    gc.collect()

    df = df.rename(columns={k: v for k, v in FIELD_MAP.items() if k in df.columns})

    if "SKU ID" not in df.columns:
        for sku_key in SKU_KEY_CANDIDATES:
            if sku_key in df.columns:
                df = df.rename(columns={sku_key: "SKU ID"})
                break

    if "平台" not in df.columns:
        df["平台"] = df["_platform_source"]
    else:
        df["平台"] = df["平台"].fillna(df["_platform_source"])

    for date_col in ["日期", "记录时间"]:
        if date_col in df.columns:
            df[date_col] = convert_time_column(df[date_col])

    for col in ["公司限定价", "店铺到手价", "平台页面价"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 立刻优化 dtype 减少内存
    df = optimize_dtypes(df)

    gc.collect()
    return df


# ============================================================
# 业务函数
# ============================================================
def dedupe_latest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    key_cols = [c for c in ["平台", "店铺", "型号", "SKU ID", "日期"] if c in df.columns]
    if "日期" not in key_cols:
        key_cols = [c for c in ["平台", "店铺", "型号", "SKU ID"] if c in df.columns]
    sort_cols = [c for c in ["记录时间", "日期"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False, na_position="last")
    if key_cols:
        df = df.drop_duplicates(subset=key_cols, keep="first")
    return df.reset_index(drop=True)


def dedupe_by_latest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    key_cols = [c for c in ["平台", "店铺", "型号", "SKU ID"] if c in df.columns]
    if not key_cols:
        return df
    sort_cols = [c for c in ["记录时间", "日期"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False, na_position="last")
    df = df.drop_duplicates(subset=key_cols, keep="first")
    return df.reset_index(drop=True)


def classify_severity(diff: float) -> str:
    amt = abs(diff)
    if amt >= 100:
        return "🔴 严重"
    elif amt >= 30:
        return "🟠 中度"
    else:
        return "🟡 轻微"


# ============================================================
# UI 组件
# ============================================================
def kpi_card(label: str, value: str, sub: str = "", variant: str = ""):
    cls = f"kpi-card {variant}" if variant else "kpi-card"
    return f"<div class='{cls}'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div><div class='kpi-sub'>{sub}</div></div>"


def render_alert_banner(broken_count: int, broken_shops: int, severe_count: int):
    if broken_count == 0:
        cls, num, title = "alert-banner safe", "0", "价格体系正常 · 无乱价"
        desc = "当前筛选范围内未检测到任何乱价行为，所有商品价格合规。"
        action = "✅ 继续保持"
    elif severe_count > 0:
        cls, num = "alert-banner", str(broken_count)
        title = f"检测到 {broken_count} 条乱价记录 · 需立即处理"
        desc = f"涉及 {broken_shops} 家店铺，其中 <b>{severe_count} 条严重乱价</b>（破价 ≥ 100 元），建议优先处理。"
        action = "⚡ 立即介入"
    else:
        cls, num = "alert-banner warn", str(broken_count)
        title = f"检测到 {broken_count} 条乱价记录 · 建议跟进"
        desc = f"涉及 {broken_shops} 家店铺，暂无严重乱价，建议按流程通知店铺调价。"
        action = "📞 及时跟进"
    st.markdown(
        f"<div class='{cls}'><div class='alert-num'>{num}</div>"
        f"<div class='alert-text'><div class='alert-title'>{title}</div>"
        f"<div class='alert-desc'>{desc}</div></div>"
        f"<div class='alert-action'>{action}</div></div>",
        unsafe_allow_html=True,
    )


def render_platform_price_chart(model_df: pd.DataFrame, limit_price: float):
    platform_min = model_df.groupby("平台", observed=True)["店铺到手价"].min().reset_index()
    platform_min = platform_min.rename(columns={"店铺到手价": "最低到手价"})
    if platform_min.empty:
        return
    platform_min = platform_min.sort_values("最低到手价")
    colors = [PLATFORM_COLORS.get(str(p), "#607d8b") for p in platform_min["平台"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=platform_min["最低到手价"], y=platform_min["平台"].astype(str), orientation="h",
        marker_color=colors,
        text=[f"¥{v:,.0f}" + (" 🚨" if v < limit_price else "") for v in platform_min["最低到手价"]],
        textposition="outside",
    ))
    fig.add_vline(x=limit_price, line_dash="dash", line_color="#d32f2f",
                  annotation_text=f"限价 ¥{limit_price:,.0f}", annotation_position="top")
    fig.update_layout(height=max(140, len(platform_min) * 50),
                      margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_title="最低到手价 (¥)", yaxis_title="", showlegend=False)
    st.plotly_chart(fig, width="stretch")
    del fig


def render_model_card(model_df: pd.DataFrame, limit_price: float):
    model_name = str(model_df["型号"].iloc[0])
    sku_id = ""
    if "SKU ID" in model_df.columns:
        v = model_df["SKU ID"].iloc[0]
        if pd.notna(v):
            sku_id = str(v)
    product_name = ""
    if "页面产品名称" in model_df.columns:
        v = model_df["页面产品名称"].iloc[0]
        if pd.notna(v):
            product_name = str(v)

    min_price = float(model_df["店铺到手价"].min())
    max_price = float(model_df["店铺到手价"].max())
    avg_platform = float(model_df["平台页面价"].mean()) if "平台页面价" in model_df.columns else None
    diff = min_price - limit_price
    has_broken = diff < 0
    broken_count = int((model_df["店铺到手价"] < limit_price).sum())
    total_shops = len(model_df)

    latest_time_str = ""
    if "记录时间" in model_df.columns:
        t = model_df["记录时间"].dropna().max()
        if pd.notna(t):
            latest_time_str = t.strftime("%Y-%m-%d %H:%M:%S")

    involved = sorted(model_df["平台"].dropna().astype(str).unique().tolist()) if "平台" in model_df.columns else []
    platform_tags = " ".join(
        PLATFORM_BADGE_HTML.get(p, f"<span class='plat-badge' style='background:#607d8b;'>{p}</span>")
        for p in involved
    )

    with st.container(border=True):
        head_left, head_right = st.columns([5, 1])
        with head_left:
            st.markdown(f"### 🏷️ {model_name}")
            if sku_id:
                st.markdown(f"<div style='color:#555;font-size:13px;margin-top:-8px;'>🆔 SKU ID：<code>{sku_id}</code></div>", unsafe_allow_html=True)
            if product_name:
                st.caption(f"📦 {product_name}")
            if platform_tags:
                st.markdown(platform_tags, unsafe_allow_html=True)
            if latest_time_str:
                st.markdown(f"<div style='color:#888;font-size:12px;'>🕒 最新采集：{latest_time_str}</div>", unsafe_allow_html=True)
        with head_right:
            if has_broken:
                sev = classify_severity(diff)
                st.markdown(
                    f"<div style='background:#ffebee;border:1px solid #ef9a9a;border-radius:8px;padding:10px;text-align:center;'>"
                    f"<div style='color:#c62828;font-weight:700;font-size:15px;'>{sev}</div>"
                    f"<div style='color:#c62828;font-size:22px;font-weight:700;line-height:1.2;'>¥{abs(diff):,.2f}</div>"
                    f"<div style='color:#c62828;font-size:12px;'>低于限价</div></div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='background:#e8f5e9;border:1px solid #a5d6a7;border-radius:8px;padding:10px;text-align:center;'>"
                    f"<div style='color:#2e7d32;font-weight:700;font-size:15px;'>✅ 合规</div>"
                    f"<div style='color:#2e7d32;font-size:22px;font-weight:700;line-height:1.2;'>¥{abs(diff):,.2f}</div>"
                    f"<div style='color:#2e7d32;font-size:12px;'>剩余余量</div></div>",
                    unsafe_allow_html=True,
                )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🎯 公司限定价", f"¥{limit_price:,.2f}")
        c2.metric("🏪 最低店铺价", f"¥{min_price:,.2f}", delta=f"{diff:+,.2f}" if has_broken else None)
        c3.metric("🏪 最高店铺价", f"¥{max_price:,.2f}")
        if avg_platform is not None and pd.notna(avg_platform):
            c4.metric("🛒 平台页面均价", f"¥{avg_platform:,.2f}")
        else:
            c4.metric("🏬 监控店铺数", f"{total_shops}")

        if len(involved) >= 2:
            st.markdown("###### 📊 各平台最低到手价对比")
            render_platform_price_chart(model_df, limit_price)

        expander_title = f"📋 各店铺明细（共 {total_shops} 家"
        if broken_count > 0:
            expander_title += f"，其中 {broken_count} 家乱价 🚨"
        expander_title += "）"

        with st.expander(expander_title, expanded=has_broken):
            detail_cols = ["平台", "店铺", "店铺到手价", "平台页面价", "价差", "严重程度", "商品链接"]
            shop_df = model_df.copy()
            for c in ["店铺", "平台"]:
                if c not in shop_df.columns:
                    shop_df[c] = "-"
            if "平台页面价" not in shop_df.columns:
                shop_df["平台页面价"] = None
            if "商品链接" not in shop_df.columns:
                shop_df["商品链接"] = None
            shop_df["价差"] = shop_df["店铺到手价"] - limit_price
            shop_df["严重程度"] = shop_df["价差"].apply(
                lambda x: classify_severity(x) if x < 0 else "✅ 合规"
            )
            shop_df = shop_df.sort_values("店铺到手价").reset_index(drop=True)

            st.dataframe(
                shop_df[detail_cols], hide_index=True, width="stretch",
                column_config={
                    "店铺到手价": st.column_config.NumberColumn(format="¥%.2f"),
                    "平台页面价": st.column_config.NumberColumn(format="¥%.2f"),
                    "价差": st.column_config.NumberColumn(format="¥%.2f"),
                    "商品链接": st.column_config.LinkColumn(display_text="🔗 打开"),
                },
            )
            del shop_df


def render_paginated_table(df, key_prefix, column_config=None, default_page_size=50):
    if df.empty:
        st.info("当前没有数据。")
        return

    total = len(df)
    c1, c2, c3 = st.columns([2, 2, 5])
    size_options = [20, 50, 100, 200, 500, "全部"]
    if default_page_size not in size_options:
        default_page_size = 50
    with c1:
        page_size_opt = st.selectbox("每页显示", size_options,
                                     index=size_options.index(default_page_size),
                                     key=f"{key_prefix}_size")
    page_size = total if page_size_opt == "全部" else int(page_size_opt)
    total_pages = max(1, (total + page_size - 1) // page_size)
    with c2:
        page = st.number_input(f"页码（共 {total_pages} 页）", min_value=1, max_value=total_pages,
                               value=1, step=1, key=f"{key_prefix}_page")
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    page_df = df.iloc[start:end].copy()
    with c3:
        st.markdown(
            f"<div style='text-align:right;color:#64748b;font-size:13px;padding-top:28px;'>"
            f"显示第 <b>{start+1}</b> – <b>{end}</b> 条，共 <b>{total}</b> 条</div>",
            unsafe_allow_html=True,
        )
    st.dataframe(page_df, hide_index=True, width="stretch",
                 key=f"{key_prefix}_tbl", column_config=column_config or {})
    del page_df


def to_excel(sheets: dict) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets.items():
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


# ============================================================
# session_state 初始化
# ============================================================
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "📸 时间点快照"
if "snapshot_date" not in st.session_state:
    st.session_state.snapshot_date = datetime.now().date() - timedelta(days=1)
if "range_start" not in st.session_state:
    st.session_state.range_start = datetime.now().date() - timedelta(days=7)
if "range_end" not in st.session_state:
    st.session_state.range_end = datetime.now().date() - timedelta(days=1)


# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.markdown("### 🎛️ 控制面板")

    view_mode = st.radio(
        "数据视图",
        ["📸 时间点快照", "📅 区间去重"],
        key="view_mode",
        help="时间点快照：查看某一天每个商品的最新价格\n区间去重：查看日期区间内每天一条记录",
    )
    snapshot_mode = view_mode.startswith("📸")

    st.markdown("---")

    start_date = end_date = None
    today = datetime.now().date()

    if snapshot_mode:
        picked = st.date_input(
            "📅 查看日期",
            key="snapshot_date",
            max_value=today,
        )
        start_date = end_date = picked
    else:
        c1, c2 = st.columns(2)
        with c1:
            s = st.date_input("起始", key="range_start", max_value=today)
        with c2:
            e = st.date_input("截止", key="range_end", max_value=today)
        if s > e:
            s, e = e, s
        start_date, end_date = s, e

    st.caption(f"🔎 将加载 {start_date} ~ {end_date} 的数据")

    st.markdown("---")
    search_query = st.text_input("🔍 搜索型号 / SKU ID", "", placeholder="型号名或 SKU ID")

    st.markdown("---")
    st.markdown("**🛒 电商平台**")
    all_platforms = ["京东", "天猫", "拼多多"]
    sel_platforms = st.multiselect("平台", all_platforms, default=all_platforms,
                                    label_visibility="collapsed")

    st.markdown("---")
    st.markdown("**🎯 监控品类**")
    category_placeholder = st.empty()

    st.markdown("---")
    shop_placeholder = st.empty()

    st.markdown("---")
    if st.button("🔄 刷新数据", width="stretch", type="primary"):
        st.cache_data.clear()
        st.cache_resource.clear()
        gc.collect()
        st.rerun()


# ============================================================
# 拉数据
# ============================================================
try:
    df_raw = load_data(
        start_date.isoformat() if start_date else None,
        end_date.isoformat() if end_date else None,
    )
except Exception as e:
    st.error(f"❌ 数据加载失败：{e}")
    st.stop()

if df_raw.empty:
    st.warning(f"⚠️ 所选日期（{start_date} ~ {end_date}）暂无采集数据，请选择其他日期。")
    st.stop()

required = ["品类", "型号", "公司限定价", "店铺到手价"]
missing = [c for c in required if c not in df_raw.columns]
if missing:
    st.error(f"❌ 缺少必要字段：{missing}。")
    st.write("当前可用列：", list(df_raw.columns))
    st.stop()

# 去重
df_all = dedupe_latest(df_raw)
del df_raw
gc.collect()

# 渲染品类 / 店铺筛选器
with category_placeholder.container():
    categories = sorted(df_all["品类"].dropna().astype(str).unique().tolist())
    selected_category = st.selectbox("品类", ["全部"] + categories, label_visibility="collapsed")

with shop_placeholder.container():
    with st.expander("🔧 高级筛选（店铺）", expanded=False):
        shops = sorted(df_all["店铺"].dropna().astype(str).unique().tolist()) if "店铺" in df_all.columns else []
        sel_shops = st.multiselect("店铺", shops, default=shops)


# ============================================================
# 数据过滤
# ============================================================
df = df_all[df_all["平台"].astype(str).isin(sel_platforms)].copy() if sel_platforms else df_all.copy()

if end_date and "日期" in df.columns:
    df = df[df["日期"].dt.date <= end_date]
if not snapshot_mode and start_date and "日期" in df.columns:
    df = df[df["日期"].dt.date >= start_date]

if "店铺" in df.columns and sel_shops:
    df = df[df["店铺"].astype(str).isin(sel_shops)]

df = df.dropna(subset=["公司限定价", "店铺到手价"])

if df.empty:
    st.warning("⚠️ 当前筛选条件下没有数据，请调整筛选条件。")
    st.stop()

if snapshot_mode:
    df = dedupe_by_latest(df)
else:
    df = dedupe_latest(df)

if df.empty:
    st.warning("⚠️ 处理后没有数据。")
    st.stop()

df["is_broken"] = df["店铺到手价"] < df["公司限定价"]
df["破价金额"] = (df["店铺到手价"] - df["公司限定价"]).astype("float32")
df["严重程度"] = df["破价金额"].apply(lambda x: classify_severity(x) if x < 0 else "✅ 合规")

df_main = df[df["品类"].astype(str) == selected_category].copy() if selected_category != "全部" else df.copy()

if df_main.empty:
    st.warning(f"⚠️ 品类「{selected_category}」在筛选条件下没有数据。")
    st.stop()

broken_records = df_main[df_main["is_broken"]].copy()

# 释放中间变量
del df
gc.collect()


# ============================================================
# 顶部标题
# ============================================================
if snapshot_mode:
    date_desc = f"📸 截至 {end_date}"
else:
    date_desc = f"📅 {start_date} ~ {end_date}"

latest_t = None
for c in ["记录时间", "日期"]:
    if c in df_main.columns:
        t = df_main[c].dropna().max()
        if pd.notna(t):
            latest_t = t
            break

updated_str = latest_t.strftime("%Y-%m-%d %H:%M") if latest_t is not None else "-"

st.markdown(
    f"<h2 style='margin-bottom:6px;'>🚨 乱价监控看板</h2>"
    f"<p style='color:#64748b;font-size:13px;margin-bottom:18px;'>"
    f"数据最新更新至 {updated_str} · 覆盖京东 / 天猫 / 拼多多 · {date_desc}</p>",
    unsafe_allow_html=True,
)


# ============================================================
# KPI 汇总
# ============================================================
broken_count = len(broken_records)
broken_shops = int(broken_records["店铺"].nunique()) if "店铺" in broken_records.columns and not broken_records.empty else 0
severe_count = int((broken_records["严重程度"] == "🔴 严重").sum()) if not broken_records.empty else 0
medium_count = int((broken_records["严重程度"] == "🟠 中度").sum()) if not broken_records.empty else 0
light_count = int((broken_records["严重程度"] == "🟡 轻微").sum()) if not broken_records.empty else 0

render_alert_banner(broken_count, broken_shops, severe_count)

total_models = int(df_main["型号"].nunique())
broken_models = int(broken_records["型号"].nunique()) if not broken_records.empty else 0
worst_amt = float(broken_records["破价金额"].min()) if not broken_records.empty else 0.0

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(kpi_card("🚨 乱价记录", f"{broken_count}",
                         f"涉及 {broken_models} 个型号 / {broken_shops} 家店铺",
                         "danger" if broken_count > 0 else "success"), unsafe_allow_html=True)
with c2:
    st.markdown(kpi_card("🔴 严重乱价", f"{severe_count}",
                         f"破价 ≥ ¥100 · 需立即处理" if severe_count > 0 else "暂无严重乱价",
                         "danger" if severe_count > 0 else "success"), unsafe_allow_html=True)
with c3:
    st.markdown(kpi_card("🟠🟡 中轻度", f"{medium_count + light_count}",
                         f"中度 {medium_count} 条 · 轻微 {light_count} 条",
                         "warn" if medium_count + light_count > 0 else "success"), unsafe_allow_html=True)
with c4:
    st.markdown(kpi_card("💸 最大破价",
                         f"¥{abs(worst_amt):,.0f}" if worst_amt < 0 else "无破价 🎉",
                         "全网最大破价金额" if worst_amt < 0 else "全部合规",
                         "danger" if worst_amt < 0 else "success"), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ============================================================
# 搜索模式
# ============================================================
if search_query and search_query.strip():
    sq = search_query.strip().lower()
    mask = pd.Series([False] * len(df_main), index=df_main.index)
    mask |= df_main["型号"].astype(str).str.lower().str.contains(sq, na=False, regex=False)
    if "页面产品名称" in df_main.columns:
        mask |= df_main["页面产品名称"].astype(str).str.lower().str.contains(sq, na=False, regex=False)
    if "SKU ID" in df_main.columns:
        mask |= df_main["SKU ID"].astype(str).str.lower().str.contains(sq, na=False, regex=False)

    df_search = df_main[mask]
    st.markdown(f"### 🔍 搜索「{search_query}」")
    if df_search.empty:
        st.warning("没有找到匹配的型号。")
    else:
        matched = df_search["型号"].unique().tolist()
        st.success(f"找到 **{len(matched)}** 个匹配型号")
        model_summary = df_search.groupby("型号", observed=True).agg(
            公司限定价=("公司限定价", "first"),
            最低到手价=("店铺到手价", "min"),
        ).reset_index()
        model_summary["最低价差"] = model_summary["最低到手价"] - model_summary["公司限定价"]
        model_summary = model_summary.sort_values("最低价差")
        for _, row in model_summary.iterrows():
            mdf = df_main[df_main["型号"] == row["型号"]]
            render_model_card(mdf, float(row["公司限定价"]))
    st.stop()


# ============================================================
# 导航（用 radio 替代 tabs，实现懒加载）
# ============================================================
st.markdown("<hr style='margin:12px 0;border:none;border-top:1px solid #e5e7eb;'>", unsafe_allow_html=True)
nav_options = ["🚨 乱价处理台", "🏪 店铺乱价榜", "📦 型号乱价榜",
               "📈 乱价趋势", "📊 品类概览", "📋 全部数据"]
selected_nav = st.radio(
    "导航",
    nav_options,
    horizontal=True,
    label_visibility="collapsed",
    key="main_nav",
)
st.markdown("<hr style='margin:8px 0 18px 0;border:none;border-top:1px solid #e5e7eb;'>", unsafe_allow_html=True)


# ============================================================
# 页面内容（只渲染当前选中页）
# ============================================================
# ---------- 1. 乱价处理台 ----------
if selected_nav == "🚨 乱价处理台":
    st.markdown("### 🚨 乱价处理台")
    st.caption("💡 按破价金额从高到低排序，每条记录带商品链接。")

    if broken_records.empty:
        st.success("🎉 当前筛选范围内没有乱价记录！")
    else:
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            sev_filter = st.multiselect("严重程度",
                ["🔴 严重", "🟠 中度", "🟡 轻微"],
                default=["🔴 严重", "🟠 中度", "🟡 轻微"], key="wb_sev")
        with fc2:
            plat_opts = sorted(broken_records["平台"].astype(str).unique().tolist())
            plat_filter = st.multiselect("平台", plat_opts, default=plat_opts, key="wb_plat")
        with fc3:
            shop_opts = sorted(broken_records["店铺"].astype(str).unique().tolist()) if "店铺" in broken_records.columns else []
            shop_filter = st.multiselect("店铺", shop_opts, default=[], key="wb_shop", placeholder="不选=全部")
        with fc4:
            min_break = st.number_input("最小破价金额（¥）", min_value=0, value=0, step=10, key="wb_min")

        wb_df = broken_records[broken_records["严重程度"].isin(sev_filter)]
        if plat_filter:
            wb_df = wb_df[wb_df["平台"].astype(str).isin(plat_filter)]
        if shop_filter and "店铺" in wb_df.columns:
            wb_df = wb_df[wb_df["店铺"].astype(str).isin(shop_filter)]
        if min_break > 0:
            wb_df = wb_df[wb_df["破价金额"].abs() >= min_break]
        wb_df = wb_df.sort_values("破价金额").reset_index(drop=True)

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("筛选后记录", f"{len(wb_df)}")
        r2.metric("涉及型号", f"{wb_df['型号'].nunique()}")
        r3.metric("涉及店铺", f"{wb_df['店铺'].nunique()}" if "店铺" in wb_df.columns else "0")
        r4.metric("最大破价", f"¥{wb_df['破价金额'].abs().max():,.0f}" if not wb_df.empty else "-")

        st.markdown("---")

        if wb_df.empty:
            st.info("没有符合筛选条件的乱价记录。")
        else:
            show_cols = [c for c in ["严重程度", "平台", "店铺", "品类", "型号", "SKU ID",
                                     "公司限定价", "店铺到手价", "破价金额", "商品链接"] if c in wb_df.columns]
            render_paginated_table(
                wb_df[show_cols], key_prefix="wb", default_page_size=50,
                column_config={
                    "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                    "店铺到手价": st.column_config.NumberColumn(format="¥%.2f"),
                    "破价金额": st.column_config.NumberColumn(format="¥%.2f"),
                    "商品链接": st.column_config.LinkColumn(display_text="🔗 打开"),
                },
            )


# ---------- 2. 店铺乱价榜 ----------
elif selected_nav == "🏪 店铺乱价榜":
    st.markdown("### 🏪 店铺乱价榜")
    if broken_records.empty:
        st.success("🎉 当前筛选范围内没有店铺乱价。")
    else:
        shop_rank = broken_records.groupby("店铺", observed=True).agg(
            平台=("平台", "first"),
            乱价记录数=("is_broken", "sum"),
            涉及型号数=("型号", "nunique"),
            最大破价=("破价金额", "min"),
            平均破价=("破价金额", "mean"),
            严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
        ).reset_index()
        shop_rank["乱价记录数"] = shop_rank["乱价记录数"].astype(int)
        shop_rank["严重乱价数"] = shop_rank["严重乱价数"].astype(int)
        shop_rank = shop_rank.sort_values("乱价记录数", ascending=False).reset_index(drop=True)

        l, r = st.columns([3, 2])
        with l:
            top = shop_rank.head(20).sort_values("乱价记录数").copy()
            top["店铺"] = top["店铺"].astype(str)
            fig = px.bar(top, x="乱价记录数", y="店铺", orientation="h",
                         text="乱价记录数", color="严重乱价数",
                         color_continuous_scale="Reds",
                         title="店铺乱价记录数 TOP 20")
            fig.update_traces(textposition="outside")
            fig.update_layout(height=max(400, len(top) * 30),
                              margin=dict(l=10, r=10, t=50, b=10),
                              coloraxis_showscale=False,
                              xaxis_title="乱价记录数", yaxis_title="", plot_bgcolor="white")
            st.plotly_chart(fig, width="stretch")
            del fig, top
        with r:
            render_paginated_table(
                shop_rank[["店铺", "平台", "乱价记录数", "严重乱价数", "涉及型号数", "最大破价", "平均破价"]],
                key_prefix="shop_rank", default_page_size=50,
                column_config={
                    "最大破价": st.column_config.NumberColumn(format="¥%.2f"),
                    "平均破价": st.column_config.NumberColumn(format="¥%.2f"),
                },
            )


# ---------- 3. 型号乱价榜 ----------
elif selected_nav == "📦 型号乱价榜":
    st.markdown("### 📦 型号乱价榜")
    if broken_records.empty:
        st.success("🎉 当前筛选范围内没有型号乱价。")
    else:
        model_rank = broken_records.groupby("型号", observed=True).agg(
            品类=("品类", "first"),
            公司限定价=("公司限定价", "first"),
            最低到手价=("店铺到手价", "min"),
            乱价店铺数=("店铺", lambda x: x.nunique()),
            乱价记录数=("is_broken", "sum"),
            最大破价=("破价金额", "min"),
            严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
        ).reset_index()
        model_rank["乱价记录数"] = model_rank["乱价记录数"].astype(int)
        model_rank["严重乱价数"] = model_rank["严重乱价数"].astype(int)
        model_rank = model_rank.sort_values("最大破价").reset_index(drop=True)

        top_n = st.selectbox("展示范围", ["TOP 20", "TOP 50", "全部"], index=2, key="model_topn")
        md = model_rank.copy()
        if top_n == "TOP 20":
            md = md.head(20)
        elif top_n == "TOP 50":
            md = md.head(50)
        st.caption(f"共 **{len(model_rank)}** 个型号存在乱价")

        render_paginated_table(
            md[["型号", "品类", "公司限定价", "最低到手价", "乱价店铺数", "乱价记录数", "严重乱价数", "最大破价"]],
            key_prefix="model_rank", default_page_size="全部",
            column_config={
                "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                "最低到手价": st.column_config.NumberColumn(format="¥%.2f"),
                "最大破价": st.column_config.NumberColumn(format="¥%.2f"),
            },
        )

        st.divider()
        # 只画前 30 个点，避免图表数据过大
        scatter_df = model_rank.head(30).copy()
        scatter_df["品类"] = scatter_df["品类"].astype(str)
        scatter_df["型号"] = scatter_df["型号"].astype(str)
        fig = px.scatter(scatter_df, x="乱价店铺数", y="最大破价",
                         size="乱价记录数", color="严重乱价数",
                         hover_data=["型号", "品类", "公司限定价"],
                         color_continuous_scale="Reds",
                         title="乱价型号分布 TOP 30（气泡越大=记录越多）")
        fig.update_layout(height=400, margin=dict(l=10, r=10, t=50, b=10),
                          xaxis_title="乱价店铺数", yaxis_title="最大破价金额 (¥)",
                          plot_bgcolor="white")
        st.plotly_chart(fig, width="stretch")
        del fig, scatter_df


# ---------- 4. 乱价趋势 ----------
elif selected_nav == "📈 乱价趋势":
    st.markdown("### 📈 乱价趋势分析")
    if "日期" not in df_main.columns or df_main["日期"].isna().all():
        st.info("当前数据没有日期字段，无法绘制趋势图。")
    else:
        daily = df_main.groupby(df_main["日期"].dt.date).agg(
            总记录数=("is_broken", "count"),
            乱价数=("is_broken", "sum"),
            严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
        ).reset_index()
        daily["乱价率"] = (daily["乱价数"] / daily["总记录数"] * 100).round(1)
        daily.columns = ["日期", "总记录数", "乱价数", "严重乱价数", "乱价率"]

        fig = go.Figure()
        fig.add_trace(go.Bar(x=daily["日期"], y=daily["乱价数"], name="乱价数",
                             marker_color="#f59e0b", yaxis="y"))
        fig.add_trace(go.Scatter(x=daily["日期"], y=daily["严重乱价数"], name="严重乱价数",
                                 mode="lines+markers", line=dict(color="#dc2626", width=3), yaxis="y"))
        fig.add_trace(go.Scatter(x=daily["日期"], y=daily["乱价率"], name="乱价率 (%)",
                                 mode="lines+markers", line=dict(color="#3b82f6", width=2, dash="dash"),
                                 yaxis="y2"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                          yaxis=dict(title="记录数"), yaxis2=dict(title="乱价率 (%)", overlaying="y", side="right"),
                          plot_bgcolor="white",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(fig, width="stretch")
        del fig, daily


# ---------- 5. 品类概览 ----------
elif selected_nav == "📊 品类概览":
    st.markdown("### 📊 各品类乱价情况")
    cat_agg = df_main.groupby("品类", observed=True).agg(
        型号数=("型号", "nunique"),
        记录数=("店铺到手价", "count"),
        乱价数=("is_broken", "sum"),
        严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
    ).reset_index()
    cat_agg["乱价率"] = (cat_agg["乱价数"] / cat_agg["记录数"] * 100).round(1)
    cat_agg = cat_agg.sort_values("乱价率", ascending=True)
    cat_agg["品类"] = cat_agg["品类"].astype(str)

    l, r = st.columns([3, 2])
    with l:
        fig = px.bar(cat_agg, x="乱价率", y="品类", orientation="h",
                     text="乱价数", color="严重乱价数",
                     color_continuous_scale="Reds",
                     title="各品类乱价率（颜色深浅=严重乱价数）")
        fig.update_traces(texttemplate="%{text} 条", textposition="outside")
        fig.update_layout(height=max(320, len(cat_agg) * 45),
                          margin=dict(l=10, r=10, t=50, b=10),
                          coloraxis_showscale=False,
                          xaxis_title="乱价率 (%)", yaxis_title="", plot_bgcolor="white")
        st.plotly_chart(fig, width="stretch")
        del fig
    with r:
        disp = cat_agg.sort_values("乱价率", ascending=False).copy()
        disp["乱价率"] = disp["乱价率"].apply(lambda v: f"{v:.1f}%")
        st.dataframe(disp[["品类", "型号数", "记录数", "乱价数", "严重乱价数", "乱价率"]],
                     hide_index=True, width="stretch")
        del disp


# ---------- 6. 全部数据 ----------
elif selected_nav == "📋 全部数据":
    st.markdown("### 📋 全部数据")
    st.caption("💡 展示当前筛选范围内的所有原始采集数据")

    flt1, flt2, flt3, flt4 = st.columns(4)
    with flt1:
        status_filter = st.multiselect("价格状态", ["🚨 乱价", "✅ 合规"],
                                        default=["🚨 乱价", "✅ 合规"], key="alldata_status")
    with flt2:
        pf = st.multiselect("平台", sorted(df_main["平台"].astype(str).unique().tolist()),
                             default=[], placeholder="不选=全部", key="alldata_platform")
    with flt3:
        cf = st.multiselect("品类", sorted(df_main["品类"].astype(str).unique().tolist()),
                             default=[], placeholder="不选=全部", key="alldata_category")
    with flt4:
        sf = st.multiselect("店铺", sorted(df_main["店铺"].astype(str).unique().tolist()),
                             default=[], placeholder="不选=全部", key="alldata_shop")

    all_df = df_main.copy()
    status_map = all_df["is_broken"].map({True: "🚨 乱价", False: "✅ 合规"})
    all_df = all_df[status_map.isin(status_filter)]
    if pf:
        all_df = all_df[all_df["平台"].astype(str).isin(pf)]
    if cf:
        all_df = all_df[all_df["品类"].astype(str).isin(cf)]
    if sf:
        all_df = all_df[all_df["店铺"].astype(str).isin(sf)]

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("筛选后记录", f"{len(all_df):,}")
    s2.metric("涉及型号", f"{all_df['型号'].nunique()}")
    s3.metric("涉及店铺", f"{all_df['店铺'].nunique()}" if "店铺" in all_df.columns else "0")
    s4.metric("乱价记录", f"{int(all_df['is_broken'].sum())}" if not all_df.empty else "0")
    if not all_df.empty and all_df["is_broken"].any():
        s5.metric("最大破价", f"¥{all_df['破价金额'].min():,.0f}".replace("-", ""))
    else:
        s5.metric("最大破价", "-")

    st.markdown("---")

    all_columns = [c for c in all_df.columns if not c.startswith("_")]
    default_cols = [c for c in ["严重程度", "平台", "店铺", "品类", "型号", "SKU ID",
                                 "公司限定价", "店铺到手价", "平台页面价", "破价金额",
                                 "页面产品名称", "商品链接", "日期", "记录时间"] if c in all_columns]
    other_cols = [c for c in all_columns if c not in default_cols]

    with st.expander("🔧 自定义显示列", expanded=False):
        selected_cols = st.multiselect("选择要显示的列", default_cols + other_cols,
                                        default=default_cols, key="alldata_cols")
    if not selected_cols:
        selected_cols = default_cols

    all_display = all_df[selected_cols].copy()

    sort_by = st.selectbox("排序方式",
                            ["破价最严重优先", "价格从低到高", "价格从高到低", "最新采集优先", "型号名称"],
                            key="alldata_sort")
    if sort_by == "破价最严重优先" and "破价金额" in all_display.columns:
        all_display = all_display.sort_values("破价金额")
    elif sort_by == "价格从低到高" and "店铺到手价" in all_display.columns:
        all_display = all_display.sort_values("店铺到手价")
    elif sort_by == "价格从高到低" and "店铺到手价" in all_display.columns:
        all_display = all_display.sort_values("店铺到手价", ascending=False)
    elif sort_by == "最新采集优先":
        if "记录时间" in all_display.columns:
            all_display = all_display.sort_values("记录时间", ascending=False)
        elif "日期" in all_display.columns:
            all_display = all_display.sort_values("日期", ascending=False)
    else:
        if "型号" in all_display.columns:
            all_display = all_display.sort_values("型号")
    all_display = all_display.reset_index(drop=True)

    if all_display.empty:
        st.info("没有符合筛选条件的数据。")
    else:
        render_paginated_table(
            all_display, key_prefix="alldata", default_page_size=50,
            column_config={
                "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                "店铺到手价": st.column_config.NumberColumn(format="¥%.2f"),
                "平台页面价": st.column_config.NumberColumn(format="¥%.2f"),
                "破价金额": st.column_config.NumberColumn(format="¥%.2f"),
                "商品链接": st.column_config.LinkColumn(display_text="🔗 打开"),
                "日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "记录时间": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

        st.markdown("---")
        csv_bytes = all_display.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ 导出 CSV", data=csv_bytes,
                            file_name=f"全部数据_{start_date}_{end_date}.csv",
                            mime="text/csv", width="stretch")
        del csv_bytes


# ============================================================
# 底部导出
# ============================================================
st.divider()
st.markdown("### 📥 导出处理清单")

try:
    drop_cols = [c for c in ["_record_id", "_platform_source"] if c in df_main.columns]
    all_export = df_main.drop(columns=drop_cols).copy()
    broken_export = broken_records.drop(columns=[c for c in drop_cols if c in broken_records.columns]).copy()

    if not broken_records.empty and "店铺" in broken_records.columns:
        shop_export = broken_records.groupby("店铺", observed=True).agg(
            平台=("平台", "first"),
            乱价记录数=("is_broken", "sum"),
            涉及型号数=("型号", "nunique"),
            最大破价=("破价金额", "min"),
            严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
        ).reset_index().sort_values("乱价记录数", ascending=False)
    else:
        shop_export = pd.DataFrame()

    if not broken_records.empty:
        model_export = broken_records.groupby("型号", observed=True).agg(
            品类=("品类", "first"),
            公司限定价=("公司限定价", "first"),
            最低到手价=("店铺到手价", "min"),
            破价金额=("破价金额", "min"),
            乱价店铺数=("店铺", lambda x: x.nunique()),
        ).reset_index().sort_values("破价金额")
    else:
        model_export = pd.DataFrame()

    excel_bytes = to_excel({
        "全部数据": all_export,
        "乱价明细": broken_export,
        "店铺乱价榜": shop_export,
        "型号乱价榜": model_export,
    })

    st.download_button(
        "📊 导出全部清单",
        data=excel_bytes,
        file_name=f"乱价监控清单_{start_date}_{end_date}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch", type="primary",
    )
    del excel_bytes, all_export, broken_export
    gc.collect()
except ImportError:
    st.warning("需要安装 openpyxl：`pip install openpyxl`")