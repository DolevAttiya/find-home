import streamlit as st
import pandas as pd
import yaml
import json
import os
import folium
from datetime import datetime, date
from pathlib import Path
from streamlit_folium import st_folium

APP_DIR = Path(__file__).parent
from core.database import (
    init_db, get_apartments, get_groups, get_stats,
    mark_seen, update_note, mark_inactive,
)

st.set_page_config(page_title="חיפוש דירות", page_icon="🏠", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
body, .stApp { direction: rtl; }
h1, h2, h3, p, label, .stMarkdown, .stMarkdown p,
div[data-testid="stMetricLabel"], div[data-testid="stMetricValue"],
.stTextArea textarea, .stDataFrame, .stSelectbox, .stCheckbox,
div[data-testid="stText"], div[data-testid="column"] {
    direction: rtl; text-align: right;
}
.stSlider, .stNumberInput { direction: ltr; }
th { text-align: right !important; }
[data-testid="stDataFrame"] tr { cursor: pointer; }
[data-testid="stDataFrame"] tr:hover td { background: rgba(229,62,62,0.08) !important; }
[data-testid="column"]:first-child { position: sticky; top: 0; }
.badge-new   { background:#d4edda; color:#155724; padding:2px 7px; border-radius:4px; font-size:.8em; }
.badge-drop  { background:#fff3cd; color:#856404; padding:2px 7px; border-radius:4px; font-size:.8em; }
.badge-seen  { background:#e2e3e5; color:#383d41; padding:2px 7px; border-radius:4px; font-size:.8em; }
.badge-off   { background:#f8d7da; color:#721c24; padding:2px 7px; border-radius:4px; font-size:.8em; }
.days-low    { color:#2d7d46; font-weight:600; }
.days-mid    { color:#e07b00; font-weight:600; }
.days-high   { color:#c0392b; font-weight:700; }
</style>
""", unsafe_allow_html=True)

init_db()

TODAY = date.today()


# ── helpers ──────────────────────────────────────────────────────────────────

def _days_on_market(apt: dict) -> int | None:
    for field in ("posted_at", "scraped_at"):
        val = apt.get(field)
        if not val:
            continue
        try:
            dt = pd.to_datetime(val)
            if dt.tzinfo is not None:
                dt = dt.tz_convert("UTC").tz_localize(None)
            return max(0, (pd.Timestamp.now() - dt).days)
        except Exception:
            continue
    return None


def _days_label(days: int | None) -> str:
    if days is None:
        return "-"
    if days == 0:
        return "היום"
    return f"{days}י׳"


def _orig_price(apt: dict) -> int | None:
    return apt.get("original_price") or apt.get("first_hist_price")


def _status_badges(apt: dict) -> str:
    parts = []
    scraped = apt.get("scraped_at")
    if scraped:
        try:
            if pd.to_datetime(scraped).date() == TODAY:
                parts.append("🆕")
        except Exception:
            pass
    orig = _orig_price(apt)
    if orig and apt.get("price") and orig > apt["price"]:
        parts.append("📉")
    if apt.get("seen"):
        parts.append("👁")
    if not apt.get("is_active", 1):
        parts.append("🚫")
    return " ".join(parts)


def _render_gallery(images: list):
    import base64
    imgs_b64 = []
    for path in images[:10]:
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = path.rsplit(".", 1)[-1].lower()
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(ext, "jpeg")
            imgs_b64.append(f"data:image/{mime};base64,{b64}")
        except Exception:
            pass
    if not imgs_b64:
        return

    imgs_json = json.dumps(imgs_b64)
    html = f"""<style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{margin:0;overflow:hidden;background:transparent}}
    .gallery{{display:flex;flex-wrap:wrap;gap:5px;padding:2px 0}}
    .thumb{{height:90px;width:auto;max-width:150px;object-fit:cover;border-radius:5px;
            cursor:pointer;border:2px solid transparent;transition:all .15s;flex-shrink:0}}
    .thumb:hover{{border-color:#e53e3e;transform:scale(1.03)}}
    .thumb.active{{border-color:#e53e3e}}
    #preview{{opacity:0;pointer-events:none;position:relative;margin-top:8px;background:#111;
              border-radius:8px;height:370px;display:flex;align-items:center;
              justify-content:center;transition:opacity .15s}}
    #preview.open{{opacity:1;pointer-events:auto}}
    #main-img{{max-width:100%;max-height:358px;object-fit:contain;border-radius:5px}}
    .nav{{position:absolute;top:50%;transform:translateY(-50%);background:rgba(255,255,255,.15);
          border:none;color:#fff;font-size:1.4em;padding:7px 13px;cursor:pointer;border-radius:5px}}
    .nav:hover{{background:rgba(255,255,255,.32)}}
    #btn-prev{{left:8px}} #btn-next{{right:8px}}
    #btn-close{{position:absolute;top:8px;right:10px;background:rgba(0,0,0,.45);
               border:none;color:#fff;font-size:1.1em;padding:3px 9px;cursor:pointer;border-radius:4px}}
    #counter{{position:absolute;bottom:8px;left:50%;transform:translateX(-50%);
             color:rgba(255,255,255,.55);font-size:.8em;font-family:Arial}}
    </style>
    <div class="gallery">
      {"".join(f'<img class="thumb" src="{src}" onclick="openImg({i})">' for i, src in enumerate(imgs_b64))}
    </div>
    <div id="preview">
      <button class="nav" id="btn-prev" onclick="nav(-1)">&#9664;</button>
      <img id="main-img" src="">
      <button class="nav" id="btn-next" onclick="nav(1)">&#9654;</button>
      <button id="btn-close" onclick="closePreview()">&#x2715;</button>
      <div id="counter"></div>
    </div>
    <script>
    const imgs={imgs_json};let cur=0;
    function openImg(i){{cur=i;document.querySelectorAll('.thumb').forEach((t,j)=>t.classList.toggle('active',j===i));
      document.getElementById('main-img').src=imgs[i];
      document.getElementById('counter').textContent=(i+1)+' / '+imgs.length;
      document.getElementById('preview').classList.add('open');}}
    function closePreview(){{document.getElementById('preview').classList.remove('open');
      document.querySelectorAll('.thumb').forEach(t=>t.classList.remove('active'));}}
    function nav(dir){{cur=(cur+dir+imgs.length)%imgs.length;
      document.getElementById('main-img').src=imgs[cur];
      document.getElementById('counter').textContent=(cur+1)+' / '+imgs.length;
      document.querySelectorAll('.thumb').forEach((t,j)=>t.classList.toggle('active',j===cur));}}
    document.addEventListener('keydown',e=>{{
      if(!document.getElementById('preview').classList.contains('open'))return;
      if(e.key==='Escape')closePreview();
      if(e.key==='ArrowLeft')nav(1);if(e.key==='ArrowRight')nav(-1);
    }});
    </script>"""
    st.html(html)


def _render_apt_detail(apt: dict):
    post_id = apt.get("post_id") or str(apt.get("id") or id(apt))

    # ── header badges ──
    src_label = {"facebook": "פייסבוק", "madlan": "מדלן", "yad2": "יד2"}.get(apt.get("source", ""), apt.get("source", ""))
    days = _days_on_market(apt)

    badge_parts = []
    if src_label:
        badge_parts.append(f'<span class="badge-seen">{src_label}</span>')
    if apt.get("seen"):
        badge_parts.append('<span class="badge-seen">👁 ראיתי</span>')
    if not apt.get("is_active", 1):
        badge_parts.append('<span class="badge-off">🚫 הוסרה</span>')
    scraped = apt.get("scraped_at")
    if scraped:
        try:
            if pd.to_datetime(scraped).date() == TODAY:
                badge_parts.append('<span class="badge-new">🆕 חדשה היום</span>')
        except Exception:
            pass
    if badge_parts:
        st.markdown(" ".join(badge_parts), unsafe_allow_html=True)

    # ── price + drop ──
    price = apt.get("price")
    orig = _orig_price(apt)
    if price:
        if orig and orig > price:
            drop = orig - price
            pct = drop / orig * 100
            st.markdown(
                f"<div style='font-size:1.5em;font-weight:700;color:#2d7d46'>"
                f"{int(price):,} ₪ "
                f"<span style='font-size:.65em;color:#c0392b'>📉 ירד מ-{int(orig):,} ₪ (-{int(drop):,} ₪ / -{pct:.1f}%)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='font-size:1.5em;font-weight:700'>{int(price):,} ₪</div>",
                unsafe_allow_html=True,
            )

    # ── days on market ──
    if days is not None:
        if days <= 7:
            cls, note = "days-low", "דירה חדשה"
        elif days <= 30:
            cls, note = "days-mid", "מחכה כבר — יש מה לדבר"
        else:
            cls, note = "days-high", "מחכה הרבה זמן — כוח מיקוח גבוה!"
        st.markdown(
            f'<span class="{cls}">⏱ {days} ימים בשוק</span> '
            f'<span style="color:#888;font-size:.85em">({note})</span>',
            unsafe_allow_html=True,
        )

    # ── specs ──
    c1, c2, c3 = st.columns(3)
    c1.metric("חדרים", apt.get("rooms") or "-")
    c2.metric("מ״ר", int(apt["size_sqm"]) if apt.get("size_sqm") else "-")
    c3.metric("קומה", apt.get("floor") or "-")

    # ── amenities ──
    amenities = []
    if apt.get("has_mamad") == 1:    amenities.append('✓ ממ"ד')
    if apt.get("has_parking") == 1:  amenities.append("✓ חניה")
    if apt.get("has_balcony") == 1:  amenities.append("✓ מרפסת")
    if apt.get("has_elevator") == 1: amenities.append("✓ מעלית")
    if amenities:
        st.markdown("&nbsp;&nbsp;|&nbsp;&nbsp;".join(amenities))

    # ── contact ──
    row = []
    if apt.get("phone"):
        row.append(f"📞 **{apt['phone']}**")
    if apt.get("post_url"):
        row.append(f"[🔗 מודעה מקורית]({apt['post_url']})")
    if row:
        st.markdown("  &nbsp;·&nbsp;  ".join(row))

    # ── action buttons ──
    act1, act2 = st.columns(2)
    with act1:
        seen = apt.get("seen", 0)
        if seen:
            if st.button("↩ בטל ראיתי", key=f"seen_{post_id}", use_container_width=True):
                mark_seen(post_id, False)
                st.rerun()
        else:
            if st.button("✓ ראיתי", key=f"seen_{post_id}", type="primary", use_container_width=True):
                mark_seen(post_id, True)
                st.rerun()
    with act2:
        active = apt.get("is_active", 1)
        if active:
            if st.button("🗑 סמן כהוסרה", key=f"inactive_{post_id}", use_container_width=True):
                mark_inactive(post_id, active=False)
                st.rerun()
        else:
            if st.button("↩ שחזר מודעה", key=f"inactive_{post_id}", use_container_width=True):
                mark_inactive(post_id, active=True)
                st.rerun()

    # ── notes ──
    st.markdown("**הערות שלי:**")
    note_val = st.text_area(
        "הערות",
        value=apt.get("notes") or "",
        height=100,
        label_visibility="collapsed",
        key=f"note_area_{post_id}",
        placeholder="כתוב כאן הערות על הדירה הזו...",
    )
    if st.button("💾 שמור הערה", key=f"save_note_{post_id}"):
        update_note(post_id, note_val)
        st.toast("הערה נשמרה!")

    # ── description ──
    if apt.get("text"):
        safe_text = apt["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        st.markdown(
            f"""<div dir="rtl" style="
                font-size: 0.78em;
                line-height: 1.55;
                color: #333;
                background: #f9f9f9;
                border-right: 3px solid #e53e3e;
                padding: 10px 12px;
                border-radius: 4px;
                max-height: 220px;
                overflow-y: auto;
                white-space: pre-wrap;
                word-break: break-word;
            ">{safe_text}</div>""",
            unsafe_allow_html=True,
        )

    # ── images ──
    images = []
    if apt.get("images_json"):
        try:
            images = [p for p in json.loads(apt["images_json"]) if os.path.exists(p)]
        except Exception:
            pass
    if images:
        _render_gallery(images)


def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(config):
    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


# ── Sidebar ───────────────────────────────────────────────────────────────────

st.sidebar.title("🏠 חיפוש דירות")
page = st.sidebar.radio("ניווט", ["תוצאות", "הגדרות", "קבוצות"], key="nav")

# ── Results page ─────────────────────────────────────────────────────────────

if page == "תוצאות":
    st.title("דירות שנמצאו")

    config = load_config()

    stats = get_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("סה״כ דירות", stats["total"])
    c2.metric("חדשות היום", stats["new_today"])
    c3.metric("ירידות מחיר", stats["price_drops"])
    c4.metric("קבוצות פעילות", stats["groups"])

    st.divider()

    with st.expander("סינון תוצאות", expanded=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            only_price = st.checkbox("רק פוסטים עם מחיר", value=config["מחיר"].get("רק_פוסטים_עם_מחיר", True))
            price_range = st.slider(
                "טווח מחיר (₪)", 3_000_000, 6_000_000,
                (config["מחיר"].get("מינימום", 3_000_000), config["מחיר"].get("מקסימום", 6_000_000)),
                step=50_000, disabled=not only_price,
            )
            rooms_range = st.slider(
                "מספר חדרים", 1.0, 10.0,
                (float(config["חדרים"].get("מינימום", 3)), float(config["חדרים"].get("מקסימום", 5))),
                step=0.5,
            )
            size_range = st.slider(
                "גודל (מ״ר)", 20, 300,
                (config["גודל_במטר"].get("מינימום", 60), config["גודל_במטר"].get("מקסימום", 150)),
                step=5,
            )
        with fc2:
            has_mamad   = st.checkbox('✓ ממ"ד / מרחב מוגן')
            has_parking = st.checkbox("✓ חניה")
            has_balcony = st.checkbox("✓ מרפסת")
            source_filter = st.selectbox("מקור", ["הכל", "פייסבוק", "מדלן", "יד2"])
            st.markdown("---")
            hide_seen    = st.checkbox("הסתר דירות שראיתי 👁", value=False)
            show_inactive = st.checkbox("הצג מודעות שהוסרו 🚫", value=False)

    filters = {
        "only_with_price": only_price,
        "min_price":  price_range[0] if only_price else None,
        "max_price":  price_range[1] if only_price else None,
        "min_rooms":  rooms_range[0],
        "max_rooms":  rooms_range[1],
        "min_size":   size_range[0],
        "max_size":   size_range[1],
        "has_mamad":  has_mamad,
        "has_parking": has_parking,
        "has_balcony": has_balcony,
        "source": {"הכל": None, "פייסבוק": "facebook", "מדלן": "madlan", "יד2": "yad2"}.get(source_filter),
    }

    apartments_all = get_apartments(filters)

    # Python-level filters
    apartments = [
        a for a in apartments_all
        if (show_inactive or a.get("is_active", 1))
        and (not hide_seen or not a.get("seen"))
    ]

    st.subheader(f"נמצאו {len(apartments)} דירות")

    if apartments:
        df = pd.DataFrame(apartments)

        tab_table, tab_map = st.tabs(["טבלה", "מפה"])

        with tab_table:
            # ── build display columns ──
            df_display = pd.DataFrame(apartments)

            df_display["סטטוס"] = [_status_badges(a) for a in apartments]
            df_display["מקור"]  = df_display["source"].map(
                {"facebook": "פייסבוק", "madlan": "מדלן", "yad2": "יד2"}
            ).fillna(df_display["source"])
            df_display["ימים"]  = [_days_label(_days_on_market(a)) for a in apartments]

            def _price_col(apt):
                p = apt.get("price")
                if p is None:
                    return "-"
                orig = _orig_price(apt)
                s = f"{int(p):,}"
                if orig and orig > p:
                    s += f" ↓{int(orig - p):,}"
                return s

            df_display["מחיר ₪"] = [_price_col(a) for a in apartments]

            def fmt_bool3(series):
                return series.map(lambda v: "✓" if v == 1 else ("✗" if v == 0 else "?"))

            df_display['ממ"ד']  = fmt_bool3(df_display["has_mamad"])
            df_display["חניה"]  = fmt_bool3(df_display["has_parking"])
            df_display["מרפסת"] = fmt_bool3(df_display["has_balcony"])

            visible_cols = ["סטטוס", "address", "מחיר ₪", "rooms", "size_sqm", "floor", "ימים", 'ממ"ד', "חניה", "מרפסת", "מקור"]
            visible_cols = [c for c in visible_cols if c in df_display.columns]

            col_rename = {
                "address":  "כתובת",
                "rooms":    "חד׳",
                "size_sqm": "מ״ר",
                "floor":    "קומה",
            }

            # Row styling: new=green, price-drop=orange, inactive=red, seen=gray
            def _row_style(row):
                apt = apartments[row.name]
                scraped = apt.get("scraped_at")
                is_new = False
                if scraped:
                    try:
                        is_new = pd.to_datetime(scraped).date() == TODAY
                    except Exception:
                        pass
                orig = _orig_price(apt)
                price_dropped = bool(orig and apt.get("price") and orig > apt["price"])

                if not apt.get("is_active", 1):
                    bg = "rgba(220,53,69,0.07)"
                elif is_new and not apt.get("seen"):
                    bg = "rgba(40,167,69,0.09)"
                elif price_dropped:
                    bg = "rgba(255,165,0,0.12)"
                elif apt.get("seen"):
                    bg = "rgba(0,0,0,0.04)"
                else:
                    bg = ""
                return [f"background-color: {bg}"] * len(row)

            styled = (
                df_display[visible_cols]
                .rename(columns=col_rename)
                .style.apply(_row_style, axis=1)
            )

            col_detail, col_list = st.columns([3, 2])

            with col_list:
                st.caption(f"{len(apartments)} דירות — לחץ שורה לפרטים")
                evt = st.dataframe(
                    styled,
                    on_select="rerun",
                    selection_mode="single-row",
                    hide_index=True,
                    use_container_width=True,
                    height=680,
                )

            with col_detail:
                sel_rows = evt.selection.rows if (evt and hasattr(evt, "selection")) else []
                idx = sel_rows[0] if sel_rows else 0
                apt = apartments[idx]
                st.subheader(apt.get("address") or "פרטי דירה")
                _render_apt_detail(apt)

        with tab_map:
            map_df = df[df["lat"].notna() & df["lon"].notna()].copy()
            if map_df.empty:
                st.info("אין קואורדינטות עדיין — הן מחושבות אחרי הסריקה לפי כתובות שנמצאו בפוסטים.")
            else:
                m = folium.Map(
                    location=[map_df["lat"].mean(), map_df["lon"].mean()],
                    zoom_start=15,
                    tiles="OpenStreetMap",
                )
                for _, row in map_df.iterrows():
                    price_str = f"{int(row['price']):,} ₪" if pd.notna(row.get("price")) and row.get("price") else "מחיר לא ידוע"
                    rooms_str = f"{row['rooms']} חד׳" if pd.notna(row.get("rooms")) and row.get("rooms") else ""
                    size_str  = f"{int(row['size_sqm'])} מ״ר" if pd.notna(row.get("size_sqm")) and row.get("size_sqm") else ""
                    floor_str = f"קומה {row['floor']}" if row.get("floor") else ""
                    addr_str  = row.get("address") or ""
                    source_str = {"facebook": "פייסבוק", "madlan": "מדלן", "yad2": "יד2"}.get(row.get("source", ""), row.get("source", ""))

                    tags = []
                    if row.get("has_mamad"):    tags.append('ממ"ד')
                    if row.get("has_parking"):  tags.append("חניה")
                    if row.get("has_balcony"):  tags.append("מרפסת")
                    if row.get("has_elevator"): tags.append("מעלית")
                    tags_str = " · ".join(tags)

                    link_html = (f'<a href="{row["post_url"]}" target="_blank" style="color:#e53e3e;">פתח מודעה ←</a>'
                                 if row.get("post_url") else "")

                    # Days on market for popup
                    days = _days_on_market(row.to_dict())
                    days_str = f"{days} ימים בשוק" if days is not None else ""

                    popup_html = f"""
                    <div dir="rtl" style="font-family:Arial,sans-serif;min-width:220px;line-height:1.7">
                        <div style="font-size:.8em;color:#888">{source_str}</div>
                        <b style="font-size:1.05em">{addr_str}</b><br>
                        <span style="color:#e53e3e;font-size:1.2em;font-weight:bold">{price_str}</span><br>
                        <span>{" &nbsp;·&nbsp; ".join(filter(None, [rooms_str, size_str, floor_str]))}</span><br>
                        {"<span style='color:#2d7d46'>✓ " + tags_str + "</span><br>" if tags_str else ""}
                        {"<span style='color:#888;font-size:.85em'>⏱ " + days_str + "</span><br>" if days_str else ""}
                        {link_html}
                    </div>
                    """

                    color = "#2d7d46" if row.get("seen") else "#e53e3e"
                    folium.CircleMarker(
                        location=[row["lat"], row["lon"]],
                        radius=10,
                        color=color,
                        fill=True,
                        fill_color=color,
                        fill_opacity=0.85,
                        weight=2,
                        popup=folium.Popup(popup_html, max_width=280),
                        tooltip=f"{addr_str} | {price_str}",
                    ).add_to(m)

                result = st_folium(m, width="100%", height=520, returned_objects=["last_object_clicked"])

                clicked = result.get("last_object_clicked") if result else None
                if clicked and isinstance(clicked, dict):
                    clat, clng = clicked.get("lat"), clicked.get("lng")
                    if clat and clng:
                        dists = ((map_df["lat"] - clat)**2 + (map_df["lon"] - clng)**2)
                        apt_row = map_df.loc[dists.idxmin()].to_dict()
                        st.divider()
                        st.subheader(apt_row.get("address") or "פרטי דירה")
                        _render_apt_detail(apt_row)

                st.caption(f"{len(map_df)} דירות על המפה  |  ירוק = ראיתי")
    else:
        st.info("לא נמצאו דירות — נסה להרחיב את המסננים או להריץ סריקה")

    st.divider()
    if st.button("🔍 סרוק עכשיו", type="primary", use_container_width=True):
        import subprocess, sys

        status_box = st.empty()
        messages = []
        with st.spinner("סורק... (חלון דפדפן ייפתח)"):
            proc = subprocess.Popen(
                [sys.executable, "scrapers/scraper.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                cwd=str(APP_DIR),
            )
            results = {"new_apartments": 0, "groups_scanned": 0, "errors": []}
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("__RESULT__:"):
                    import json as _j
                    results = _j.loads(line[len("__RESULT__:"):])
                else:
                    messages.append(line)
                    status_box.info("\n".join(messages[-5:]))
            proc.wait()

        st.success(f"הסריקה הסתיימה! {results['new_apartments']} דירות חדשות מתוך {results['groups_scanned']} קבוצות")
        if results["errors"]:
            st.warning("שגיאות: " + ", ".join(results["errors"]))
        st.rerun()

# ── Settings page ─────────────────────────────────────────────────────────────

elif page == "הגדרות":
    st.title("הגדרות חיפוש")
    config = load_config()

    st.subheader("מיקום ומילות חיפוש")
    location = st.text_input("עיר / אזור", config["חיפוש"].get("מיקום", ""))
    search_terms_raw = st.text_area(
        "מילות חיפוש לקבוצות (כל שורה = מילה אחת)",
        "\n".join(config["חיפוש"].get("מילות_חיפוש_קבוצות", [])),
        height=100,
    )

    st.subheader("מסנני נתונים")
    c1, c2 = st.columns(2)
    with c1:
        min_rooms  = st.number_input("חדרים מינימום",   1.0, 10.0, float(config["חדרים"]["מינימום"]), 0.5)
        max_rooms  = st.number_input("חדרים מקסימום",   1.0, 10.0, float(config["חדרים"]["מקסימום"]), 0.5)
        min_price  = st.number_input("מחיר מינימום ₪",  0, 20_000_000, config["מחיר"]["מינימום"], 50_000)
        max_price  = st.number_input("מחיר מקסימום ₪",  0, 20_000_000, config["מחיר"]["מקסימום"], 50_000)
    with c2:
        min_size   = st.number_input("גודל מינימום מ״ר", 20, 500, config["גודל_במטר"]["מינימום"], 5)
        max_size   = st.number_input("גודל מקסימום מ״ר", 20, 500, config["גודל_במטר"]["מקסימום"], 5)
        only_price = st.checkbox("רק פוסטים עם מחיר", config["מחיר"].get("רק_פוסטים_עם_מחיר", True))
        scan_hours = st.number_input("סריקה אוטומטית כל X שעות", 1, 24, config["סריקה"].get("כל_כמה_שעות", 2))

    st.subheader("מילות מפתח")
    required_raw = st.text_area(
        "מילות חובה (כל שורה = מילה, ריק = בלי חובה)",
        "\n".join(config.get("מילות_מפתח_חובה", [])), height=80,
    )
    blocked_raw = st.text_area(
        "מילות חסימה", "\n".join(config.get("מילות_חסימה", [])), height=80,
    )

    if st.button("שמור הגדרות", type="primary"):
        config["חיפוש"]["מיקום"] = location
        config["חיפוש"]["מילות_חיפוש_קבוצות"] = [l.strip() for l in search_terms_raw.splitlines() if l.strip()]
        config["חדרים"]        = {"מינימום": min_rooms, "מקסימום": max_rooms}
        config["מחיר"]         = {"מינימום": min_price, "מקסימום": max_price, "רק_פוסטים_עם_מחיר": only_price}
        config["גודל_במטר"]    = {"מינימום": min_size,  "מקסימום": max_size}
        config["מילות_מפתח_חובה"] = [l.strip() for l in required_raw.splitlines() if l.strip()]
        config["מילות_חסימה"]  = [l.strip() for l in blocked_raw.splitlines() if l.strip()]
        config["סריקה"]["כל_כמה_שעות"] = scan_hours
        save_config(config)
        st.success("ההגדרות נשמרו!")

# ── Groups page ───────────────────────────────────────────────────────────────

elif page == "קבוצות":
    st.title("קבוצות פייסבוק")
    groups = get_groups()
    if groups:
        df = pd.DataFrame(groups)[["group_name", "group_id", "added_at"]]
        df.columns = ["שם הקבוצה", "ID", "נוסף בתאריך"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("עדיין לא נמצאו קבוצות — הרץ סריקה ראשונה מעמוד התוצאות")
