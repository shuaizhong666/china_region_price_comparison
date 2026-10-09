import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
import threading
import time
from datetime import timedelta, datetime
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    .alert-banner.safe {
        background: linear-gradient(90deg, #14532d 0%, #16a34a 100%);
        box-shadow: 0 4px 16px rgba(22,163,74,0.25);
    }
    .alert-banner.warn {
        background: linear-gradient(90deg, #78350f 0%, #f59e0b 100%);
        box-shadow: 0 4px 16px rgba(245,158,11,0.25);
    }
    .alert-num { font-size: 52px; font-weight: 800; line-height: 1; min-width: 90px; text-align: center; }
    .alert-text { flex: 1; }
    .alert-title { font-size: 20px; font-weight: 700; margin-bottom: 6px; }
    .alert-desc { font-size: 14px; opacity: 0.92; line-height: 1.5; }
    .alert-action { background: rgba(255,255,255,0.2); padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; }

    .kpi-card {
        background: white; border-radius: 10px; padding: 18px 20px;
        border-left: 4px solid #3b82f6;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06); height: 100%;
    }
    .kpi-card.danger { border-left-color: #dc2626; }
    .kpi-card.warn { border-left-color: #f59e0b; }
    .kpi-card.info { border-left-color: #0ea5e9; }
    .kpi-card.success { border-left-color: #16a34a; }
    .kpi-label { font-size: 13px; color: #64748b; margin-bottom: 6px; }
    .kpi-value { font-size: 28px; font-weight: 700; color: #0f172a; line-height: 1.2; }
    .kpi-sub { font-size: 12px; color: #94a3b8; margin-top: 6px; }

    .sev-critical { display: inline-block; background: #dc2626; color: white; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .sev-medium { display: inline-block; background: #f59e0b; color: white; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .sev-light { display: inline-block; background: #facc15; color: #422006; padding: 2px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
    .plat-badge { display: inline-block; padding: 2px 8px; border-radius: 8px; color: white; font-size: 11px; font-weight: 600; margin-right: 4px; }

    .shop-group { background: white; border-radius: 10px; padding: 16px 20px; margin-bottom: 12px; border-left: 4px solid #dc2626; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }
    .shop-group.watch { border-left-color: #7c3aed; background: linear-gradient(90deg, #faf5ff 0%, #ffffff 100%); }
    .shop-name { font-size: 17px; font-weight: 700; color: #0f172a; display: flex; align-items: center; gap: 10px; }
    .shop-stats { color: #64748b; font-size: 13px; margin-top: 4px; }
    .shop-amount { font-size: 20px; font-weight: 800; color: #dc2626; }

    .stTabs [data-baseweb="tab-list"] { gap: 4px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px 8px 0 0; padding: 10px 18px; font-weight: 600; }
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 飞书应用凭证 & 常量
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
CACHE_TTL_SECONDS = 600  # 数据缓存有效期（秒）

# ============================================================
# 全局共享状态（跨会话）
# ============================================================
@st.cache_resource(show_spinner=False)
def _get_shared_state():
    """全局单例，所有 Streamlit 会话共享"""
    return {
        "df": None,               # 已处理的 DataFrame（共享对象，只读使用）
        "updated_at": 0.0,        # 缓存时间戳
        "errors": {},             # 拉取时产生的错误信息
        "load_lock": threading.Lock(),   # 防止多线程同时拉数据
        "token_value": None,
        "token_expire": 0.0,
        "token_lock": threading.Lock(),
    }


# ============================================================
# 飞书 API 请求（带重试 + 指数退避）
# ============================================================
def _feishu_request(method: str, url: str, **kwargs) -> dict:
    """
    统一的飞书 API 调用封装：
    - 429/5xx 自动重试
    - 飞书限流码自动退避
    - 指数退避 + 最大重试次数
    """
    retries = kwargs.pop("_retries", 4)
    timeout = kwargs.pop("_timeout", 45)
    last_err = "unknown"

    for attempt in range(retries):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)

            # HTTP 层面限流 / 服务端错误
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                if attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                raise RuntimeError(f"飞书 HTTP 错误: {resp.status_code}")

            resp.raise_for_status()
            data = resp.json()
            code = data.get("code")

            if code in (None, 0):
                return data

            # 飞书限流常见错误码
            if code in (99991400, 99991401, 1254291, 1000004):
                last_err = f"限流 {code}: {data.get('msg')}"
                if attempt < retries - 1:
                    time.sleep(min(2 ** attempt, 15))
                    continue
                raise RuntimeError(f"飞书限流: {data.get('msg')}")

            raise RuntimeError(f"飞书 API 错误: {data}")

        except requests.exceptions.RequestException as e:
            last_err = str(e)
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 15))
                continue
            break

    raise RuntimeError(f"飞书 API 请求失败（已重试 {retries} 次）: {last_err}")


def _get_tenant_access_token() -> str:
    """全局缓存的 token（带锁，防止并发重复获取）"""
    state = _get_shared_state()
    now = time.time()

    if state["token_value"] and now < state["token_expire"]:
        return state["token_value"]

    with state["token_lock"]:
        now = time.time()
        if state["token_value"] and now < state["token_expire"]:
            return state["token_value"]

        data = _feishu_request(
            "POST",
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": APP_ID, "app_secret": APP_SECRET},
        )
        state["token_value"] = data["tenant_access_token"]
        # 提前 5 分钟过期，留出安全余量
        expire_sec = int(data.get("expire", 7200))
        state["token_expire"] = now + max(expire_sec - 300, 60)
        return state["token_value"]


def _fetch_records(token: str, table_id: str) -> list:
    """拉取整张表全部记录（分页）"""
    headers = {"Authorization": f"Bearer {token}"}
    records = []
    page_token = None

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        data = _feishu_request(
            "GET",
            f"{FEISHU_BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records",
            headers=headers,
            params=params,
        )
        items = data.get("data", {}).get("items", [])
        records.extend(items)

        if not data.get("data", {}).get("has_more"):
            break
        page_token = data["data"].get("page_token")

    return records


def _fetch_all_tables(token: str) -> tuple:
    """并行拉取三张表（京东/天猫/拼多多），失败不阻塞其他表"""
    results, errors = {}, {}

    with ThreadPoolExecutor(max_workers=len(FEISHU_TABLES)) as ex:
        futures = {
            ex.submit(_fetch_records, token, cfg["table_id"]): name
            for name, cfg in FEISHU_TABLES.items()
        }
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                errors[name] = str(e)
                results[name] = []

    return results, errors


# ============================================================
# 时间戳转换（含时区修复）
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


# ============================================================
# 数据构建 & 处理
# ============================================================
def _build_dataframe(tables: dict) -> pd.DataFrame:
    frames = []
    for platform_name, records in tables.items():
        if not records:
            continue
        rows = [{"_record_id": r.get("record_id", ""), **r.get("fields", {})} for r in records]
        df_p = pd.DataFrame(rows)
        df_p["_platform_source"] = platform_name
        frames.append(df_p)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
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

    return df


def dedupe_latest(df: pd.DataFrame) -> pd.DataFrame:
    """区间去重：同一天同一商品多次采集，只保留记录时间最新的一条"""
    if df.empty:
        return df
    df = df.copy()
    key_cols = [c for c in ["平台", "店铺", "型号", "SKU ID", "日期"] if c in df.columns]
    if "日期" not in key_cols:
        key_cols = [c for c in ["平台", "店铺", "型号", "SKU ID"] if c in df.columns]
    sort_cols = []
    if "记录时间" in df.columns:
        sort_cols.append("记录时间")
    if "日期" in df.columns and "日期" not in sort_cols:
        sort_cols.append("日期")
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False, na_position="last")
    if key_cols:
        df = df.drop_duplicates(subset=key_cols, keep="first")
    return df.reset_index(drop=True)


def dedupe_by_latest(df: pd.DataFrame) -> pd.DataFrame:
    """时间点快照去重：每个商品只保留记录时间最新的一条"""
    if df.empty:
        return df
    df = df.copy()
    key_cols = [c for c in ["平台", "店铺", "型号", "SKU ID"] if c in df.columns]
    if not key_cols:
        return df
    sort_cols = []
    if "记录时间" in df.columns:
        sort_cols.append("记录时间")
    if "日期" in df.columns and "日期" not in sort_cols:
        sort_cols.append("日期")
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False, na_position="last")
    df = df.drop_duplicates(subset=key_cols, keep="first")
    return df.reset_index(drop=True)


# ============================================================
# 严重程度分级（向量化，替代 apply 加速）
# ============================================================
def classify_severity(diff: float) -> str:
    amt = abs(diff)
    if amt >= 100:
        return "🔴 严重"
    elif amt >= 30:
        return "🟠 中度"
    else:
        return "🟡 轻微"


def classify_severity_series(diff_series: pd.Series, compliant_label: str = None) -> pd.Series:
    """向量化分级：比 apply 快 10-100 倍"""
    amt = diff_series.abs().to_numpy()
    labels = np.select(
        [amt >= 100, amt >= 30],
        ["🔴 严重", "🟠 中度"],
        default="🟡 轻微",
    )
    result = pd.Series(labels, index=diff_series.index, dtype="object")
    if compliant_label is not None:
        result = result.mask(diff_series >= 0, compliant_label)
    return result


# ============================================================
# 共享数据加载（核心防崩逻辑）
# ============================================================
def _load_and_process_data() -> tuple:
    """真正执行拉取 + 处理，只在缓存失效时被调用一次"""
    token = _get_tenant_access_token()
    tables, errors = _fetch_all_tables(token)
    df = _build_dataframe(tables)

    if df.empty:
        return df, errors

    # 去重后作为全局共享数据
    df_all = dedupe_latest(df)
    return df_all, errors


def get_shared_data(force_refresh: bool = False) -> tuple:
    """
    获取全局共享的 DataFrame。
    - 使用双层检查锁：缓存有效时无锁直接返回
    - 缓存失效时只有一个线程去拉数据，其他用户等待复用结果
    """
    state = _get_shared_state()
    lock = state["load_lock"]
    now = time.time()

    # 快路径：命中缓存，无锁返回
    if not force_refresh and state["df"] is not None:
        if now - state["updated_at"] < CACHE_TTL_SECONDS:
            return state["df"], state["errors"]

    # 慢路径：加锁 + 双重检查
    with lock:
        now = time.time()
        if not force_refresh and state["df"] is not None:
            if now - state["updated_at"] < CACHE_TTL_SECONDS:
                return state["df"], state["errors"]

        with st.spinner("正在从飞书拉取数据（首次加载约需 10-30 秒）..."):
            df, errors = _load_and_process_data()

        state["df"] = df
        state["updated_at"] = time.time()
        state["errors"] = errors
        return df, errors


def invalidate_shared_data():
    """手动清空共享缓存"""
    state = _get_shared_state()
    with state["load_lock"]:
        state["df"] = None
        state["updated_at"] = 0.0
        state["errors"] = {}


# ============================================================
# UI 组件
# ============================================================
def kpi_card(label: str, value: str, sub: str = "", variant: str = ""):
    cls = f"kpi-card {variant}" if variant else "kpi-card"
    return f"""
    <div class='{cls}'>
        <div class='kpi-label'>{label}</div>
        <div class='kpi-value'>{value}</div>
        <div class='kpi-sub'>{sub}</div>
    </div>
    """


def render_alert_banner(broken_count: int, broken_shops: int, severe_count: int):
    if broken_count == 0:
        cls, num = "alert-banner safe", "0"
        title = "价格体系正常 · 无乱价"
        desc = "当前筛选范围内未检测到任何乱价行为，所有商品价格合规。"
        action = "✅ 继续保持"
    elif severe_count > 0:
        cls, num = "alert-banner", str(broken_count)
        title = f"检测到 {broken_count} 条乱价记录 · 需立即处理"
        desc = (
            f"涉及 {broken_shops} 家店铺，其中 <b style='background:rgba(255,255,255,0.25);"
            f"padding:1px 6px;border-radius:3px;'>{severe_count} 条严重乱价</b>（破价 ≥ 100 元），"
            f"建议优先处理严重级别，尽快联系店铺调价。"
        )
        action = "⚡ 立即介入"
    else:
        cls, num = "alert-banner warn", str(broken_count)
        title = f"检测到 {broken_count} 条乱价记录 · 建议跟进"
        desc = f"涉及 {broken_shops} 家店铺，暂无严重乱价，建议按流程通知店铺调价。"
        action = "📞 及时跟进"

    st.markdown(
        f"""
        <div class='{cls}'>
            <div class='alert-num'>{num}</div>
            <div class='alert-text'>
                <div class='alert-title'>{title}</div>
                <div class='alert-desc'>{desc}</div>
            </div>
            <div class='alert-action'>{action}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_platform_price_chart(model_df: pd.DataFrame, limit_price: float):
    platform_min = (
        model_df.groupby("平台")["店铺到手价"].min().reset_index()
        .rename(columns={"店铺到手价": "最低到手价"})
    )
    if platform_min.empty:
        return
    platform_min = platform_min.sort_values("最低到手价")
    colors = [PLATFORM_COLORS.get(p, "#607d8b") for p in platform_min["平台"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=platform_min["最低到手价"], y=platform_min["平台"],
        orientation="h", marker_color=colors,
        text=[f"¥{v:,.0f}" + (" 🚨" if v < limit_price else "") for v in platform_min["最低到手价"]],
        textposition="outside",
    ))
    fig.add_vline(x=limit_price, line_dash="dash", line_color="#d32f2f",
                  annotation_text=f"限价 ¥{limit_price:,.0f}", annotation_position="top")
    fig.update_layout(
        height=max(140, len(platform_min) * 50),
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_title="最低到手价 (¥)", yaxis_title="", showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")


def render_model_card(model_df: pd.DataFrame, limit_price: float):
    model_name = str(model_df["型号"].iloc[0])

    sku_id = ""
    if "SKU ID" in model_df.columns:
        sku_val = model_df["SKU ID"].iloc[0]
        if pd.notna(sku_val):
            sku_id = str(sku_val)

    product_name = ""
    if "页面产品名称" in model_df.columns:
        pn = model_df["页面产品名称"].iloc[0]
        if pd.notna(pn):
            product_name = str(pn)

    min_price = model_df["店铺到手价"].min()
    max_price = model_df["店铺到手价"].max()
    avg_platform = model_df["平台页面价"].mean() if "平台页面价" in model_df.columns else None

    diff = min_price - limit_price
    has_broken = diff < 0
    broken_count = int((model_df["店铺到手价"] < limit_price).sum())
    total_shops = len(model_df)

    latest_time_str = ""
    if "记录时间" in model_df.columns:
        latest_t = model_df["记录时间"].dropna().max()
        if pd.notna(latest_t):
            latest_time_str = latest_t.strftime("%Y-%m-%d %H:%M:%S")

    involved_platforms = (
        sorted(model_df["平台"].dropna().unique().tolist())
        if "平台" in model_df.columns else []
    )
    platform_tags_html = " ".join(
        PLATFORM_BADGE_HTML.get(p, f"<span class='plat-badge' style='background:#607d8b;'>{p}</span>")
        for p in involved_platforms
    )

    with st.container(border=True):
        head_left, head_right = st.columns([5, 1])
        with head_left:
            st.markdown(f"### 🏷️ {model_name}")
            if sku_id:
                st.markdown(
                    f"<div style='color:#555;font-size:13px;margin-top:-8px;'>"
                    f"🆔 SKU ID：<code>{sku_id}</code></div>",
                    unsafe_allow_html=True,
                )
            if product_name:
                st.caption(f"📦 {product_name}")
            if platform_tags_html:
                st.markdown(platform_tags_html, unsafe_allow_html=True)
            if latest_time_str:
                st.markdown(
                    f"<div style='color:#888;font-size:12px;'>🕒 最新采集：{latest_time_str}</div>",
                    unsafe_allow_html=True,
                )
        with head_right:
            if has_broken:
                sev = classify_severity(diff)
                st.markdown(
                    f"<div style='background:#ffebee;border:1px solid #ef9a9a;border-radius:8px;"
                    f"padding:10px;text-align:center;'>"
                    f"<div style='color:#c62828;font-weight:700;font-size:15px;'>{sev}</div>"
                    f"<div style='color:#c62828;font-size:22px;font-weight:700;line-height:1.2;'>"
                    f"¥{abs(diff):,.2f}</div>"
                    f"<div style='color:#c62828;font-size:12px;'>低于限价</div></div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='background:#e8f5e9;border:1px solid #a5d6a7;border-radius:8px;"
                    f"padding:10px;text-align:center;'>"
                    f"<div style='color:#2e7d32;font-weight:700;font-size:15px;'>✅ 合规</div>"
                    f"<div style='color:#2e7d32;font-size:22px;font-weight:700;line-height:1.2;'>"
                    f"¥{abs(diff):,.2f}</div>"
                    f"<div style='color:#2e7d32;font-size:12px;'>剩余余量</div></div>",
                    unsafe_allow_html=True,
                )

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🎯 公司限定价", f"¥{limit_price:,.2f}")
        c2.metric("🏪 最低店铺价", f"¥{min_price:,.2f}",
                  delta=f"{diff:+,.2f}" if has_broken else None)
        c3.metric("🏪 最高店铺价", f"¥{max_price:,.2f}")
        if avg_platform is not None and pd.notna(avg_platform):
            c4.metric("🛒 平台页面均价", f"¥{avg_platform:,.2f}")
        else:
            c4.metric("🏬 监控店铺数", f"{total_shops}")

        if len(involved_platforms) >= 2:
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
            shop_df["严重程度"] = classify_severity_series(shop_df["价差"], compliant_label="✅ 合规")
            shop_df = shop_df.sort_values("店铺到手价").reset_index(drop=True)

            st.dataframe(
                shop_df[detail_cols],
                hide_index=True,
                width="stretch",
                column_config={
                    "店铺到手价": st.column_config.NumberColumn(format="¥%.2f"),
                    "平台页面价": st.column_config.NumberColumn(format="¥%.2f"),
                    "价差": st.column_config.NumberColumn(format="¥%.2f"),
                    "商品链接": st.column_config.LinkColumn(display_text="🔗 打开"),
                },
            )


# ============================================================
# 分页表格组件
# ============================================================
def render_paginated_table(
    df: pd.DataFrame,
    key_prefix: str,
    column_config: dict = None,
    show_selection: bool = False,
    default_page_size=50,
):
    if df.empty:
        st.info("当前没有数据。")
        return None, None

    total = len(df)
    c1, c2, c3 = st.columns([2, 2, 5])
    size_options = [20, 50, 100, 200, 500, "全部"]
    if default_page_size not in size_options:
        default_page_size = 50
    with c1:
        page_size_opt = st.selectbox(
            "每页显示", size_options,
            index=size_options.index(default_page_size),
            key=f"{key_prefix}_size",
        )
    page_size = total if page_size_opt == "全部" else int(page_size_opt)
    total_pages = max(1, (total + page_size - 1) // page_size)

    with c2:
        page = st.number_input(
            f"页码（共 {total_pages} 页）",
            min_value=1, max_value=total_pages, value=1, step=1,
            key=f"{key_prefix}_page",
        )

    start = (page - 1) * page_size
    end = min(start + page_size, total)
    page_df = df.iloc[start:end]

    with c3:
        st.markdown(
            f"<div style='text-align:right;color:#64748b;font-size:13px;padding-top:28px;'>"
            f"显示第 <b>{start+1}</b> – <b>{end}</b> 条，共 <b>{total}</b> 条</div>",
            unsafe_allow_html=True,
        )

    if show_selection:
        event = st.dataframe(
            page_df, hide_index=True, width="stretch",
            on_select="rerun", selection_mode="single-row",
            key=f"{key_prefix}_tbl",
            column_config=column_config or {},
        )
        return page_df, event
    else:
        st.dataframe(
            page_df, hide_index=True, width="stretch",
            key=f"{key_prefix}_tbl",
            column_config=column_config or {},
        )
        return page_df, None


# ============================================================
# Excel 导出（带缓存，避免每次 rerun 都重新生成）
# ============================================================
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, max_entries=3)
def _build_excel_bytes(sheets_hashable: tuple) -> bytes:
    """
    传入 tuple 形式的 sheets 保证可哈希；结构：[("sheet_name", df), ...]
    """
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets_hashable:
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


def build_export_excel(sheets: dict) -> bytes:
    """构造 key 让缓存能命中；用 shape + 关键列做轻量指纹"""
    fingerprint = []
    ordered = []
    for name, df in sheets.items():
        if df is None or df.empty:
            ordered.append((name, df))
            fingerprint.append((name, 0, 0))
        else:
            ordered.append((name, df))
            fingerprint.append((name, df.shape[0], df.shape[1]))

    # 用 (frozenset 指纹, 排序后的 df 结构) 做缓存 key
    # 由于 df 无法直接哈希，这里把 fingerprint + 首末值 拼成元组
    key_parts = [tuple(fingerprint)]
    for name, df in ordered:
        if df is not None and not df.empty:
            try:
                head = df.head(1).to_json()
                tail = df.tail(1).to_json()
            except Exception:
                head, tail = "", ""
            key_parts.append((name, head, tail))
        else:
            key_parts.append((name, "", ""))

    # 直接调用内部函数（用 key_parts 做缓存key）
    return _build_excel_bytes_cached(tuple(key_parts), tuple((n, d) for n, d in ordered))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, max_entries=3, hash_funcs={pd.DataFrame: lambda d: None})
def _build_excel_bytes_cached(_key_parts, sheets_tuple):
    """真正的 Excel 构建，_key_parts 用于缓存命中，DataFrame 被忽略哈希"""
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in sheets_tuple:
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name, index=False)
    return buf.getvalue()


# ============================================================
# 加载 & 处理数据
# ============================================================
try:
    df_raw, load_errors = get_shared_data()
except Exception as e:
    st.error(f"❌ 数据加载失败：{e}")
    st.stop()

if load_errors:
    st.warning(
        "⚠️ 部分平台数据拉取失败：" +
        "、".join(f"{k}（{v[:60]}…）" if len(v) > 60 else f"{k}（{v}）" for k, v in load_errors.items())
    )

if df_raw is None or df_raw.empty:
    st.warning("⚠️ 飞书多维表格中暂无数据。")
    st.stop()

required = ["品类", "型号", "公司限定价", "店铺到手价"]
missing = [c for c in required if c not in df_raw.columns]
if missing:
    st.error(f"❌ 缺少必要字段：{missing}。")
    st.write("当前可用列：", list(df_raw.columns))
    st.stop()

# df_all 只读使用；任何筛选都必须 .copy()
df_all = df_raw

# 数据最新记录时间
data_updated_at = None
for c in ["记录时间", "日期"]:
    if c in df_all.columns:
        t = df_all[c].dropna().max()
        if pd.notna(t):
            data_updated_at = t
            break


# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.markdown("### 🎛️ 控制面板")

    view_mode = st.radio(
        "数据视图",
        ["📸 时间点快照", "📅 区间去重"],
        help="时间点快照：查看截至某个日期每个商品的最新价格\n区间去重：查看日期区间内每天一条记录",
    )
    snapshot_mode = view_mode.startswith("📸")

    st.markdown("---")

    start_date, end_date = None, None

    if "日期" in df_all.columns and df_all["日期"].notna().any():
        valid_dates = df_all["日期"].dropna()
        min_d = valid_dates.min().date()
        max_d = valid_dates.max().date()
        today = datetime.now().date()

        selectable_min = min_d - timedelta(days=30)
        selectable_max = max(max_d, today)

        st.caption(f"📊 数据范围：{min_d} ~ {max_d}")

        if snapshot_mode:
            as_of_date = st.date_input(
                "📅 查看截至日期",
                value=max_d,
                min_value=selectable_min,
                max_value=selectable_max,
                help="显示每个商品在该日期及之前的最新一次采集记录",
            )
            end_date = as_of_date
            start_date = None
        else:
            default_start = max(min_d, max_d - timedelta(days=30))
            date_pick = st.date_input(
                "📅 日期范围",
                value=(default_start, max_d),
                min_value=selectable_min,
                max_value=selectable_max,
            )
            if isinstance(date_pick, (tuple, list)) and len(date_pick) == 2:
                start_date, end_date = date_pick
            else:
                start_date = end_date = min_d
    else:
        st.caption("（无日期字段，跳过日期筛选）")

    st.markdown("---")

    search_query = st.text_input(
        "🔍 搜索型号 / SKU ID", "",
        placeholder="型号名或 SKU ID",
    )

    st.markdown("---")
    st.markdown("**🛒 电商平台**")
    all_platforms = sorted(df_all["平台"].dropna().unique().tolist())
    sel_platforms = st.multiselect("平台", all_platforms, default=all_platforms,
                                    label_visibility="collapsed")

    st.markdown("---")
    st.markdown("**🎯 监控品类**")
    categories = sorted(df_all["品类"].dropna().unique().tolist())
    selected_category = st.selectbox("品类", ["全部"] + categories,
                                      label_visibility="collapsed")

    st.markdown("---")
    with st.expander("🔧 高级筛选", expanded=False):
        shops = sorted(df_all["店铺"].dropna().unique().tolist()) if "店铺" in df_all.columns else []
        sel_shops = st.multiselect("店铺", shops, default=shops)

    st.markdown("---")
    if st.button("🔄 刷新数据", width="stretch", type="primary"):
        invalidate_shared_data()
        st.rerun()

    st.caption("🕒 缓存有效期 10 分钟（全局共享）")


# ============================================================
# 数据过滤
# ============================================================
df = df_all[df_all["平台"].isin(sel_platforms)].copy() if sel_platforms else df_all.copy()

if end_date and "日期" in df.columns:
    df = df[df["日期"].dt.date <= end_date]

if not snapshot_mode and start_date and "日期" in df.columns:
    df = df[df["日期"].dt.date >= start_date]

if "店铺" in df.columns and sel_shops:
    df = df[df["店铺"].isin(sel_shops) | df["店铺"].isna()]

df = df.dropna(subset=["公司限定价", "店铺到手价"])

if df.empty:
    st.warning("⚠️ 当前筛选条件下没有数据，请调整日期或筛选条件。")
    st.stop()

if snapshot_mode:
    df = dedupe_by_latest(df)
else:
    df = dedupe_latest(df)

if df.empty:
    st.warning("⚠️ 处理后没有数据。")
    st.stop()

df["is_broken"] = df["店铺到手价"] < df["公司限定价"]
df["破价金额"] = df["店铺到手价"] - df["公司限定价"]
df["严重程度"] = classify_severity_series(df["破价金额"], compliant_label="✅ 合规")

df_main = df[df["品类"] == selected_category].copy() if selected_category != "全部" else df.copy()

if df_main.empty:
    st.warning(f"⚠️ 品类「{selected_category}」在筛选条件下没有数据。")
    st.stop()

broken_records = df_main[df_main["is_broken"]].copy()


# ============================================================
# 顶部标题栏
# ============================================================
updated_str = ""
freshness = ""
if data_updated_at is not None:
    updated_str = data_updated_at.strftime("%Y-%m-%d %H:%M")
    delta_min = int((datetime.now() - data_updated_at.to_pydatetime()).total_seconds() / 60)
    if delta_min < 0:
        freshness = "（数据来自未来？请检查时区）"
    elif delta_min < 60:
        freshness = f"（{delta_min} 分钟前）"
    elif delta_min < 1440:
        freshness = f"（{delta_min // 60} 小时前）"
    else:
        freshness = f"（{delta_min // 1440} 天前）"

if snapshot_mode:
    date_desc = f"📸 截至 {end_date}" if end_date else "📸 时间点快照"
else:
    if start_date and end_date:
        date_desc = f"📅 {start_date} ~ {end_date}"
    else:
        date_desc = "📅 全期"

st.markdown(
    f"<h2 style='margin-bottom:6px;'>🚨 乱价监控看板</h2>"
    f"<p style='color:#64748b;font-size:13px;margin-bottom:18px;'>"
    f"数据最新更新至 {updated_str} {freshness} · 覆盖京东 / 天猫 / 拼多多 · "
    f"{date_desc}</p>",
    unsafe_allow_html=True,
)


# ============================================================
# 顶部告警横幅 + KPI
# ============================================================
broken_count = len(broken_records)
broken_shops = broken_records["店铺"].nunique() if "店铺" in broken_records.columns else 0
severe_count = int((broken_records["严重程度"] == "🔴 严重").sum()) if not broken_records.empty else 0
medium_count = int((broken_records["严重程度"] == "🟠 中度").sum()) if not broken_records.empty else 0
light_count = int((broken_records["严重程度"] == "🟡 轻微").sum()) if not broken_records.empty else 0

render_alert_banner(broken_count, broken_shops, severe_count)

total_models = df_main["型号"].nunique()
broken_models = broken_records["型号"].nunique() if not broken_records.empty else 0

if not broken_records.empty:
    worst_amt = broken_records["破价金额"].min()
else:
    worst_amt = 0.0

c1, c2, c3, c4 = st.columns(4)
with c1:
    variant = "danger" if broken_count > 0 else "success"
    st.markdown(kpi_card(
        "🚨 乱价记录",
        f"{broken_count}",
        f"涉及 {broken_models} 个型号 / {broken_shops} 家店铺",
        variant,
    ), unsafe_allow_html=True)
with c2:
    st.markdown(kpi_card(
        "🔴 严重乱价",
        f"{severe_count}",
        f"破价 ≥ ¥100 · 需立即处理" if severe_count > 0 else "暂无严重乱价",
        "danger" if severe_count > 0 else "success",
    ), unsafe_allow_html=True)
with c3:
    st.markdown(kpi_card(
        "🟠🟡 中轻度",
        f"{medium_count + light_count}",
        f"中度 {medium_count} 条 · 轻微 {light_count} 条",
        "warn" if medium_count + light_count > 0 else "success",
    ), unsafe_allow_html=True)
with c4:
    st.markdown(kpi_card(
        "💸 最大破价",
        f"¥{abs(worst_amt):,.0f}" if worst_amt < 0 else "无破价 🎉",
        f"全网最大破价金额" if worst_amt < 0 else "全部合规",
        "danger" if worst_amt < 0 else "success",
    ), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ============================================================
# 搜索模式
# ============================================================
if search_query and search_query.strip():
    sq = search_query.strip().lower()
    mask_search = pd.Series([False] * len(df_main), index=df_main.index)
    mask_search |= df_main["型号"].astype(str).str.lower().str.contains(sq, na=False, regex=False)
    if "页面产品名称" in df_main.columns:
        mask_search |= df_main["页面产品名称"].astype(str).str.lower().str.contains(sq, na=False, regex=False)
    if "SKU ID" in df_main.columns:
        mask_search |= df_main["SKU ID"].astype(str).str.lower().str.contains(sq, na=False, regex=False)

    df_search = df_main[mask_search]
    st.markdown(f"### 🔍 搜索「{search_query}」")
    if df_search.empty:
        st.warning("没有找到匹配的型号。")
    else:
        matched_models = df_search["型号"].unique().tolist()
        st.success(f"找到 **{len(matched_models)}** 个匹配型号")

        model_summary = (
            df_search.groupby("型号")
            .agg(
                公司限定价=("公司限定价", "first"),
                最低到手价=("店铺到手价", "min"),
            )
            .reset_index()
        )
        model_summary["最低价差"] = model_summary["最低到手价"] - model_summary["公司限定价"]
        model_summary = model_summary.sort_values("最低价差")

        for _, row in model_summary.iterrows():
            mdf = df_main[df_main["型号"] == row["型号"]]
            render_model_card(mdf, row["公司限定价"])
    st.stop()


# ============================================================
# 主区 Tab
# ============================================================
tab_workbench, tab_shop, tab_model, tab_trend, tab_overview, tab_alldata = st.tabs(
    ["🚨 乱价处理台", "🏪 店铺乱价榜", "📦 型号乱价榜",
     "📈 乱价趋势", "📊 品类概览", "📋 全部数据"]
)


# ============================================================
# Tab 1：乱价处理台
# ============================================================
with tab_workbench:
    st.markdown("### 🚨 乱价处理台")
    st.caption("💡 按破价金额从高到低排序，每条记录带商品链接，可直接点开处理。")

    if broken_records.empty:
        st.success("🎉 当前筛选范围内没有乱价记录，价格体系合规！")
    else:
        fc1, fc2, fc3, fc4 = st.columns([2, 2, 2, 2])
        with fc1:
            sev_filter = st.multiselect(
                "严重程度",
                ["🔴 严重", "🟠 中度", "🟡 轻微"],
                default=["🔴 严重", "🟠 中度", "🟡 轻微"],
                key="wb_sev",
            )
        with fc2:
            plat_options = sorted(broken_records["平台"].dropna().unique().tolist()) if "平台" in broken_records.columns else []
            plat_filter = st.multiselect(
                "平台", plat_options, default=plat_options, key="wb_plat",
            )
        with fc3:
            shop_options = sorted(broken_records["店铺"].dropna().unique().tolist()) if "店铺" in broken_records.columns else []
            shop_filter = st.multiselect(
                "店铺", shop_options, default=[], key="wb_shop",
                placeholder="不选=全部店铺",
            )
        with fc4:
            min_break = st.number_input(
                "最小破价金额（¥）",
                min_value=0, value=0, step=10, key="wb_min_amt",
                help="只看破价超过此金额的记录",
            )

        wb_df = broken_records[broken_records["严重程度"].isin(sev_filter)]
        if plat_filter and "平台" in wb_df.columns:
            wb_df = wb_df[wb_df["平台"].isin(plat_filter)]
        if shop_filter and "店铺" in wb_df.columns:
            wb_df = wb_df[wb_df["店铺"].isin(shop_filter)]
        if min_break > 0:
            wb_df = wb_df[wb_df["破价金额"].abs() >= min_break]

        wb_df = wb_df.sort_values("破价金额").reset_index(drop=True)

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("筛选后记录", f"{len(wb_df)}")
        r2.metric("涉及型号", f"{wb_df['型号'].nunique()}" if not wb_df.empty else "0")
        r3.metric("涉及店铺", f"{wb_df['店铺'].nunique()}" if not wb_df.empty and "店铺" in wb_df.columns else "0")
        if not wb_df.empty:
            r4.metric("最大破价", f"¥{wb_df['破价金额'].abs().max():,.0f}")
        else:
            r4.metric("最大破价", "-")

        st.markdown("---")

        view_type = st.radio(
            "展示方式",
            ["📋 表格视图", "🏪 按店铺分组"],
            horizontal=True,
            key="wb_view",
            label_visibility="collapsed",
        )

        if view_type == "📋 表格视图":
            show_cols = [c for c in [
                "严重程度", "平台", "店铺", "品类", "型号", "SKU ID",
                "公司限定价", "店铺到手价", "破价金额",
                "商品链接", "页面产品名称",
            ] if c in wb_df.columns]

            wb_display = wb_df[show_cols].copy()

            if wb_display.empty:
                st.info("没有符合筛选条件的乱价记录。")
            else:
                render_paginated_table(
                    wb_display,
                    key_prefix="wb",
                    default_page_size=50,
                    column_config={
                        "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                        "店铺到手价": st.column_config.NumberColumn(format="¥%.2f"),
                        "破价金额": st.column_config.NumberColumn(format="¥%.2f"),
                        "商品链接": st.column_config.LinkColumn(display_text="🔗 打开"),
                        "SKU ID": st.column_config.TextColumn("SKU ID"),
                    },
                )
        else:
            if wb_df.empty:
                st.info("没有符合筛选条件的乱价记录。")
            else:
                shop_groups = (
                    wb_df.groupby("店铺")
                    .agg(
                        平台=("平台", "first"),
                        乱价记录数=("is_broken", "count"),
                        型号数=("型号", "nunique"),
                        最大破价=("破价金额", "min"),
                        严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
                    )
                    .reset_index()
                    .sort_values("最大破价")
                )

                page_size = st.selectbox(
                    "每页显示店铺数",
                    [10, 20, 30, "全部"],
                    index=1,
                    key="wb_shop_pagesize",
                )
                page_size_int = len(shop_groups) if page_size == "全部" else int(page_size)
                total_pages = max(1, (len(shop_groups) + page_size_int - 1) // page_size_int)
                page = st.number_input(
                    f"页码（共 {total_pages} 页）",
                    min_value=1, max_value=total_pages, value=1,
                    key="wb_shop_page",
                )
                start = (page - 1) * page_size_int
                end = min(start + page_size_int, len(shop_groups))

                st.caption(f"显示第 {start+1} – {end} 家，共 {len(shop_groups)} 家店铺")

                for _, srow in shop_groups.iloc[start:end].iterrows():
                    shop_name = srow["店铺"]
                    plat = srow["平台"]
                    n_records = int(srow["乱价记录数"])
                    n_models = int(srow["型号数"])
                    max_break_amt = srow["最大破价"]
                    n_severe = int(srow["严重乱价数"])

                    plat_badge = PLATFORM_BADGE_HTML.get(
                        plat, f"<span class='plat-badge' style='background:#607d8b;'>{plat}</span>"
                    )

                    watch_tag = ""
                    if n_severe > 0:
                        watch_tag = (
                            "<span style='background:#dc2626;color:white;"
                            "padding:2px 8px;border-radius:10px;font-size:11px;"
                            "font-weight:700;margin-left:6px;'>⚠️ 重点关注</span>"
                        )

                    with st.container(border=True):
                        head_l, head_r = st.columns([4, 1])
                        with head_l:
                            st.markdown(
                                f"<div class='shop-name'>🏪 {shop_name} {plat_badge} {watch_tag}</div>"
                                f"<div class='shop-stats'>"
                                f"乱价记录 <b>{n_records}</b> 条 · "
                                f"涉及型号 <b>{n_models}</b> 个 · "
                                f"严重乱价 <b style='color:#dc2626;'>{n_severe}</b> 条"
                                f"</div>",
                                unsafe_allow_html=True,
                            )
                        with head_r:
                            st.markdown(
                                f"<div style='text-align:right;'>"
                                f"<div style='font-size:11px;color:#94a3b8;'>最大破价</div>"
                                f"<div class='shop-amount'>¥{abs(max_break_amt):,.0f}</div>"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

                        shop_detail = wb_df[wb_df["店铺"] == shop_name].sort_values("破价金额")
                        detail_cols = [c for c in [
                            "严重程度", "品类", "型号", "SKU ID",
                            "公司限定价", "店铺到手价", "破价金额", "商品链接",
                        ] if c in shop_detail.columns]

                        st.dataframe(
                            shop_detail[detail_cols],
                            hide_index=True,
                            width="stretch",
                            column_config={
                                "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                                "店铺到手价": st.column_config.NumberColumn(format="¥%.2f"),
                                "破价金额": st.column_config.NumberColumn(format="¥%.2f"),
                                "商品链接": st.column_config.LinkColumn(display_text="🔗 打开"),
                                "SKU ID": st.column_config.TextColumn("SKU ID"),
                            },
                        )


# ============================================================
# Tab 2：店铺乱价榜
# ============================================================
with tab_shop:
    st.markdown("### 🏪 店铺乱价榜")
    st.caption("💡 按店铺统计乱价情况，快速识别'惯犯'店铺。")

    if broken_records.empty:
        st.success("🎉 当前筛选范围内没有店铺乱价。")
    else:
        shop_rank = (
            broken_records.groupby("店铺")
            .agg(
                平台=("平台", "first"),
                乱价记录数=("is_broken", "sum"),
                涉及型号数=("型号", "nunique"),
                最大破价=("破价金额", "min"),
                平均破价=("破价金额", "mean"),
                严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
            )
            .reset_index()
        )
        shop_rank["乱价记录数"] = shop_rank["乱价记录数"].astype(int)
        shop_rank["严重乱价数"] = shop_rank["严重乱价数"].astype(int)
        shop_rank = shop_rank.sort_values("乱价记录数", ascending=False).reset_index(drop=True)

        l, r = st.columns([3, 2], gap="medium")

        with l:
            top_shops = shop_rank.head(20).sort_values("乱价记录数")
            fig = px.bar(
                top_shops,
                x="乱价记录数", y="店铺", orientation="h",
                text="乱价记录数",
                color="严重乱价数",
                color_continuous_scale="Reds",
                title="店铺乱价记录数 TOP 20（颜色深浅=严重乱价数量）",
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(
                height=max(400, len(top_shops) * 30),
                margin=dict(l=10, r=10, t=50, b=10),
                coloraxis_showscale=False,
                xaxis_title="乱价记录数", yaxis_title="",
                plot_bgcolor="white",
            )
            st.plotly_chart(fig, width="stretch")

        with r:
            st.markdown("##### 📋 店铺乱价明细表")
            shop_display = shop_rank[[
                "店铺", "平台", "乱价记录数", "严重乱价数",
                "涉及型号数", "最大破价", "平均破价"
            ]].copy()
            render_paginated_table(
                shop_display,
                key_prefix="shop_rank",
                default_page_size=50,
                column_config={
                    "最大破价": st.column_config.NumberColumn(format="¥%.2f"),
                    "平均破价": st.column_config.NumberColumn(format="¥%.2f"),
                },
            )


# ============================================================
# Tab 3：型号乱价榜
# ============================================================
with tab_model:
    st.markdown("### 📦 型号乱价榜")
    st.caption("💡 按型号统计乱价情况，找出'被乱价最严重'的型号。")

    if broken_records.empty:
        st.success("🎉 当前筛选范围内没有型号乱价。")
    else:
        model_rank = (
            broken_records.groupby("型号")
            .agg(
                品类=("品类", "first"),
                公司限定价=("公司限定价", "first"),
                最低到手价=("店铺到手价", "min"),
                乱价店铺数=("店铺", lambda x: x.nunique()),
                乱价记录数=("is_broken", "sum"),
                最大破价=("破价金额", "min"),
                严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
            )
            .reset_index()
        )
        model_rank["乱价记录数"] = model_rank["乱价记录数"].astype(int)
        model_rank["严重乱价数"] = model_rank["严重乱价数"].astype(int)
        model_rank = model_rank.sort_values("最大破价").reset_index(drop=True)

        tc1, tc2 = st.columns([2, 4])
        with tc1:
            top_n = st.selectbox(
                "展示范围",
                ["TOP 20", "TOP 50", "全部"],
                index=2,
                key="model_rank_topn",
            )

        model_display = model_rank.copy()
        if top_n == "TOP 20":
            model_display = model_display.head(20)
        elif top_n == "TOP 50":
            model_display = model_display.head(50)

        with tc2:
            st.caption(f"共 **{len(model_rank)}** 个型号存在乱价")

        model_display_out = model_display[[
            "型号", "品类", "公司限定价", "最低到手价",
            "乱价店铺数", "乱价记录数", "严重乱价数", "最大破价",
        ]].copy()

        render_paginated_table(
            model_display_out,
            key_prefix="model_rank",
            default_page_size="全部",
            column_config={
                "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                "最低到手价": st.column_config.NumberColumn(format="¥%.2f"),
                "最大破价": st.column_config.NumberColumn(format="¥%.2f"),
            },
        )

        st.divider()
        st.markdown("#### 📊 型号乱价严重度分布")

        fig = px.scatter(
            model_rank.head(50),
            x="乱价店铺数",
            y="最大破价",
            size="乱价记录数",
            color="严重乱价数",
            hover_data=["型号", "品类", "公司限定价"],
            color_continuous_scale="Reds",
            title="乱价型号分布（气泡越大=记录越多，颜色越深=严重乱价越多）",
        )
        fig.update_layout(
            height=420,
            margin=dict(l=10, r=10, t=50, b=10),
            xaxis_title="乱价店铺数", yaxis_title="最大破价金额 (¥)",
            plot_bgcolor="white",
        )
        st.plotly_chart(fig, width="stretch")


# ============================================================
# Tab 4：乱价趋势
# ============================================================
with tab_trend:
    st.markdown("### 📈 乱价趋势分析")
    st.caption("💡 观察乱价问题是在好转还是恶化（仅区间模式下有意义）。")

    if "日期" not in df.columns or df["日期"].isna().all():
        st.info("当前数据没有日期字段，无法绘制趋势图。")
    else:
        st.markdown("##### 每日乱价记录数")
        daily_break = (
            df.groupby(df["日期"].dt.date)
            .agg(
                总记录数=("is_broken", "count"),
                乱价数=("is_broken", "sum"),
                严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
            )
            .reset_index()
        )
        daily_break["乱价率"] = (daily_break["乱价数"] / daily_break["总记录数"] * 100).round(1)
        daily_break.columns = ["日期", "总记录数", "乱价数", "严重乱价数", "乱价率"]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=daily_break["日期"], y=daily_break["乱价数"],
            name="乱价数", marker_color="#f59e0b", yaxis="y",
        ))
        fig.add_trace(go.Scatter(
            x=daily_break["日期"], y=daily_break["严重乱价数"],
            name="严重乱价数", mode="lines+markers",
            line=dict(color="#dc2626", width=3), yaxis="y",
        ))
        fig.add_trace(go.Scatter(
            x=daily_break["日期"], y=daily_break["乱价率"],
            name="乱价率 (%)", mode="lines+markers",
            line=dict(color="#3b82f6", width=2, dash="dash"), yaxis="y2",
        ))
        fig.update_layout(
            height=400,
            margin=dict(l=10, r=10, t=30, b=10),
            yaxis=dict(title="记录数", side="left"),
            yaxis2=dict(title="乱价率 (%)", side="right", overlaying="y"),
            plot_bgcolor="white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, width="stretch")

        st.markdown("##### 每日乱价金额分布")
        if "破价金额" in df.columns:
            daily_amount = (
                df[df["is_broken"]]
                .groupby(df["日期"].dt.date)["破价金额"]
                .agg(["sum", "min", "mean"])
                .reset_index()
            )
            daily_amount.columns = ["日期", "总破价额", "最大单笔破价", "平均破价"]
            daily_amount["总破价额"] = daily_amount["总破价额"].abs()

            fig2 = px.area(
                daily_amount, x="日期", y="总破价额",
                color_discrete_sequence=["#ef4444"],
            )
            fig2.update_layout(
                height=300,
                margin=dict(l=10, r=10, t=10, b=10),
                yaxis_title="总破价金额 (¥)", xaxis_title="",
                plot_bgcolor="white",
            )
            st.plotly_chart(fig2, width="stretch")


# ============================================================
# Tab 5：品类概览
# ============================================================
with tab_overview:
    st.markdown("### 📊 各品类乱价情况")

    cat_agg = (
        df.groupby("品类")
        .agg(
            型号数=("型号", "nunique"),
            记录数=("店铺到手价", "count"),
            乱价数=("is_broken", "sum"),
            严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
        )
        .reset_index()
    )
    cat_agg["乱价率"] = (cat_agg["乱价数"] / cat_agg["记录数"] * 100).round(1)
    cat_agg = cat_agg.sort_values("乱价率", ascending=True)

    left, right = st.columns([3, 2], gap="medium")

    with left:
        fig = px.bar(
            cat_agg, x="乱价率", y="品类", orientation="h",
            text="乱价数", color="严重乱价数",
            color_continuous_scale="Reds",
            title="各品类乱价率（颜色深浅=严重乱价数）",
        )
        fig.update_traces(texttemplate="%{text} 条", textposition="outside")
        fig.update_layout(
            height=max(320, len(cat_agg) * 45),
            margin=dict(l=10, r=10, t=50, b=10),
            coloraxis_showscale=False,
            xaxis_title="乱价率 (%)", yaxis_title="",
            plot_bgcolor="white",
        )
        st.plotly_chart(fig, width="stretch")

    with right:
        display_cat = cat_agg.sort_values("乱价率", ascending=False).copy()
        display_cat["乱价率"] = display_cat["乱价率"].apply(lambda v: f"{v:.1f}%")
        st.markdown("##### 📋 品类乱价明细")
        st.dataframe(
            display_cat[["品类", "型号数", "记录数", "乱价数", "严重乱价数", "乱价率"]],
            hide_index=True, width="stretch",
        )

    st.divider()
    st.markdown("### 🏆 乱价最严重 TOP 10 型号")
    st.caption("💡 以下型号破价金额最大，建议优先处理。")

    if broken_records.empty:
        st.success("🎉 当前筛选条件下没有乱价型号！")
    else:
        top_severe = (
            broken_records.groupby("型号")
            .agg(
                品类=("品类", "first"),
                公司限定价=("公司限定价", "first"),
                最低到手价=("店铺到手价", "min"),
                破价金额=("破价金额", "min"),
                乱价店铺数=("店铺", lambda x: x.nunique()),
                涉及平台=("平台", lambda x: " / ".join(sorted(x.dropna().unique()))),
            )
            .reset_index()
            .sort_values("破价金额")
            .head(10)
        )
        top_severe["严重程度"] = top_severe["破价金额"].apply(classify_severity)

        st.dataframe(
            top_severe[[
                "严重程度", "型号", "品类", "公司限定价",
                "最低到手价", "破价金额", "乱价店铺数", "涉及平台"
            ]],
            hide_index=True, width="stretch",
            column_config={
                "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                "最低到手价": st.column_config.NumberColumn(format="¥%.2f"),
                "破价金额": st.column_config.NumberColumn(format="¥%.2f"),
            },
        )


# ============================================================
# Tab 6：全部数据
# ============================================================
with tab_alldata:
    st.markdown("### 📋 全部数据")
    st.caption(
        "💡 展示当前筛选范围内的所有原始采集数据（含合规记录），"
        "支持按状态/平台/店铺/品类筛选，列可自选，分页查看。"
    )

    flt1, flt2, flt3, flt4 = st.columns([2, 2, 2, 2])

    with flt1:
        status_filter = st.multiselect(
            "价格状态",
            ["🚨 乱价", "✅ 合规"],
            default=["🚨 乱价", "✅ 合规"],
            key="alldata_status",
        )
    with flt2:
        platform_options = sorted(df_main["平台"].dropna().unique().tolist()) if "平台" in df_main.columns else []
        platform_filter = st.multiselect(
            "平台", platform_options, default=[], key="alldata_platform",
            placeholder="不选=全部平台",
        )
    with flt3:
        category_options = sorted(df_main["品类"].dropna().unique().tolist()) if "品类" in df_main.columns else []
        category_filter = st.multiselect(
            "品类", category_options, default=[], key="alldata_category",
            placeholder="不选=全部品类",
        )
    with flt4:
        shop_options = sorted(df_main["店铺"].dropna().unique().tolist()) if "店铺" in df_main.columns else []
        shop_filter = st.multiselect(
            "店铺", shop_options, default=[], key="alldata_shop",
            placeholder="不选=全部店铺",
        )

    all_df = df_main.copy()
    status_map = all_df["is_broken"].map({True: "🚨 乱价", False: "✅ 合规"})
    all_df = all_df[status_map.isin(status_filter)]

    if platform_filter and "平台" in all_df.columns:
        all_df = all_df[all_df["平台"].isin(platform_filter)]
    if category_filter and "品类" in all_df.columns:
        all_df = all_df[all_df["品类"].isin(category_filter)]
    if shop_filter and "店铺" in all_df.columns:
        all_df = all_df[all_df["店铺"].isin(shop_filter)]

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("筛选后记录", f"{len(all_df):,}")
    s2.metric("涉及型号", f"{all_df['型号'].nunique()}" if not all_df.empty else "0")
    s3.metric("涉及店铺", f"{all_df['店铺'].nunique()}" if not all_df.empty and "店铺" in all_df.columns else "0")
    s4.metric("乱价记录", f"{int(all_df['is_broken'].sum())}" if not all_df.empty else "0")
    if not all_df.empty and all_df["is_broken"].any():
        s5.metric("最大破价", f"¥{all_df['破价金额'].min():,.0f}".replace("-", ""))
    else:
        s5.metric("最大破价", "-")

    st.markdown("---")

    all_columns = [c for c in all_df.columns if not c.startswith("_")]
    all_columns = [c for c in all_columns if c not in ["_record_id", "_platform_source"]]

    default_cols = [c for c in [
        "严重程度", "平台", "店铺", "品类", "型号", "SKU ID",
        "公司限定价", "店铺到手价", "平台页面价", "破价金额",
        "页面产品名称", "商品链接", "日期", "记录时间",
    ] if c in all_columns]

    other_cols = [c for c in all_columns if c not in default_cols]

    with st.expander("🔧 自定义显示列", expanded=False):
        selected_cols = st.multiselect(
            "选择要显示的列（拖动可调整顺序）",
            options=default_cols + other_cols,
            default=default_cols,
            key="alldata_cols",
        )

    if not selected_cols:
        selected_cols = default_cols

    all_display = all_df[selected_cols].copy()

    sort_c1, sort_c2 = st.columns([2, 5])
    with sort_c1:
        sort_by = st.selectbox(
            "排序方式",
            ["破价最严重优先", "价格从低到高", "价格从高到低", "最新采集优先", "型号名称"],
            key="alldata_sort",
        )

    if sort_by == "破价最严重优先":
        all_display = all_display.sort_values("破价金额") if "破价金额" in all_display.columns else all_display
    elif sort_by == "价格从低到高":
        all_display = all_display.sort_values("店铺到手价") if "店铺到手价" in all_display.columns else all_display
    elif sort_by == "价格从高到低":
        all_display = all_display.sort_values("店铺到手价", ascending=False) if "店铺到手价" in all_display.columns else all_display
    elif sort_by == "最新采集优先":
        if "记录时间" in all_display.columns:
            all_display = all_display.sort_values("记录时间", ascending=False)
        elif "日期" in all_display.columns:
            all_display = all_display.sort_values("日期", ascending=False)
    else:
        all_display = all_display.sort_values("型号") if "型号" in all_display.columns else all_display

    all_display = all_display.reset_index(drop=True)

    if all_display.empty:
        st.info("没有符合筛选条件的数据。")
    else:
        render_paginated_table(
            all_display,
            key_prefix="alldata",
            default_page_size=50,
            column_config={
                "公司限定价": st.column_config.NumberColumn(format="¥%.2f"),
                "店铺到手价": st.column_config.NumberColumn(format="¥%.2f"),
                "平台页面价": st.column_config.NumberColumn(format="¥%.2f"),
                "破价金额": st.column_config.NumberColumn(format="¥%.2f"),
                "商品链接": st.column_config.LinkColumn(display_text="🔗 打开"),
                "SKU ID": st.column_config.TextColumn("SKU ID"),
                "日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "记录时间": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            },
        )

        st.markdown("---")
        dl_c1, dl_c2 = st.columns([4, 1])
        with dl_c1:
            st.caption(f"可单独导出「全部数据」当前筛选结果：{len(all_display):,} 条")
        with dl_c2:
            csv_bytes = all_display.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇️ 导出 CSV",
                data=csv_bytes,
                file_name=f"全部数据_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                width="stretch",
            )


# ============================================================
# 底部导出区
# ============================================================
st.divider()
st.markdown("### 📥 导出处理清单")

exp_c1, exp_c2 = st.columns([3, 1])
with exp_c1:
    st.caption(
        f"导出当前筛选范围的综合数据，包含 5 个 Sheet："
        f"全部数据（{len(df_main)} 条）/ 乱价明细（{len(broken_records)} 条）/ 店铺乱价榜 / 型号乱价榜 / 品类统计"
    )
with exp_c2:
    try:
        drop_cols = [c for c in ["_record_id", "_platform_source"] if c in df_main.columns]
        all_export = df_main.drop(columns=drop_cols)

        broken_export = broken_records.drop(columns=[
            c for c in drop_cols if c in broken_records.columns
        ])

        if not broken_records.empty and "店铺" in broken_records.columns:
            shop_export = (
                broken_records.groupby("店铺")
                .agg(
                    平台=("平台", "first"),
                    乱价记录数=("is_broken", "sum"),
                    涉及型号数=("型号", "nunique"),
                    最大破价=("破价金额", "min"),
                    严重乱价数=("严重程度", lambda x: (x == "🔴 严重").sum()),
                )
                .reset_index()
                .sort_values("乱价记录数", ascending=False)
            )
        else:
            shop_export = pd.DataFrame()

        if not broken_records.empty:
            model_export = (
                broken_records.groupby("型号")
                .agg(
                    品类=("品类", "first"),
                    公司限定价=("公司限定价", "first"),
                    最低到手价=("店铺到手价", "min"),
                    破价金额=("破价金额", "min"),
                    乱价店铺数=("店铺", lambda x: x.nunique()),
                )
                .reset_index()
                .sort_values("破价金额")
            )
        else:
            model_export = pd.DataFrame()

        cat_export = cat_agg.copy() if not cat_agg.empty else pd.DataFrame()

        excel_bytes = build_export_excel({
            "全部数据": all_export,
            "乱价明细": broken_export,
            "店铺乱价榜": shop_export,
            "型号乱价榜": model_export,
            "品类统计": cat_export,
        })

        st.download_button(
            "📊 导出全部清单",
            data=excel_bytes,
            file_name=f"乱价监控清单_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            type="primary",
        )
    except ImportError:
        st.warning("需要安装 openpyxl：`pip install openpyxl`")