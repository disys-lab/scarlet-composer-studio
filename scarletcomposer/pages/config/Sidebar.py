import streamlit as st
import os, socket, pkg_resources, logging, json, yaml


def _make_logo_images():
    from PIL import Image as PILImage, ImageDraw, ImageFont

    bg     = (26, 16, 8)
    orange = (239, 108, 0)
    white  = (255, 255, 255)
    muted  = (160, 140, 120)

    # Wide logo at 2x — aspect ratio ~5:1 so at 80px tall it spans ~400px wide
    lw, lh = 800, 160
    logo = PILImage.new("RGB", (lw, lh), bg)
    ld = ImageDraw.Draw(logo)
    ld.rectangle([0, 0, 10, lh], fill=orange)
    try:
        f_main = ImageFont.load_default(size=52)
        f_sub  = ImageFont.load_default(size=24)
    except TypeError:
        f_main = f_sub = ImageFont.load_default()
    ld.text((24, 10),      "SCARLET",      fill=orange, font=f_main)
    ld.text((24, 76),      "COMPOSER",     fill=white,  font=f_main)
    ld.text((26, lh - 32), "S T U D I O", fill=muted,  font=f_sub)

    # Small icon for collapsed state — keep it genuinely small (40x40 display px at 2x = 80x80)
    sz = 80
    icon = PILImage.new("RGB", (sz, sz), bg)
    id_ = ImageDraw.Draw(icon)
    id_.rounded_rectangle([4, 4, sz - 4, sz - 4], radius=14, fill=orange)
    try:
        f_icon = ImageFont.load_default(size=32)
    except TypeError:
        f_icon = ImageFont.load_default()
    id_.text((sz // 2, sz // 2), "SC", fill=white, font=f_icon, anchor="mm")

    return logo, icon


def sidebarInit():
    st.markdown("""
    <style>
    /* Sidebar width — only when expanded */
    [data-testid="stSidebar"][aria-expanded="true"] {
        min-width: 240px !important;
        max-width: 260px !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] {
        min-width: 0 !important;
        max-width: 0 !important;
        overflow: hidden !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding-top: 0.5rem;
        padding-left: 0.75rem;
        padding-right: 0.75rem;
    }

    /* Override Streamlit's inline max-height on the sidebar logo */
    [data-testid="stSidebarHeader"] img {
        max-height: 52px !important;
        height: 52px !important;
        width: auto !important;
        object-fit: contain !important;
    }
    [data-testid="stSidebarHeader"] {
        padding: 0.25rem 0.5rem !important;
    }

    /* Constrain the collapsed icon so it doesn't take over the page */
    [data-testid="stHeader"] img,
    header[data-testid="stHeader"] a img {
        max-height: 36px !important;
        max-width: 36px !important;
        height: 36px !important;
        width: 36px !important;
        object-fit: contain !important;
    }
    </style>
    """, unsafe_allow_html=True)

    try:
        logo_img, icon_img = _make_logo_images()
        st.logo(image=logo_img, icon_image=icon_img)
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        netwIPAddr = socket.gethostbyname(hostname)
    except Exception:
        netwIPAddr = "127.0.0.1"

    if "REDIS_HOST" not in st.session_state:
        st.session_state.REDIS_HOST = netwIPAddr
    if "REDIS_PORT" not in st.session_state:
        st.session_state.REDIS_PORT = "6379"
    if "REDIS_AUTH_TOKEN" not in st.session_state:
        st.session_state.REDIS_AUTH_TOKEN = ""
    if "MANAGER_HOST" not in st.session_state:
        st.session_state.MANAGER_HOST = netwIPAddr
    if "MANAGER_PORT" not in st.session_state:
        st.session_state.MANAGER_PORT = "8080"
    if "MANAGER_AUTH_TOKEN" not in st.session_state:
        st.session_state.MANAGER_AUTH_TOKEN = "bmVidWxhOm5lYnVsYQ=="
    if "SC_HOST" not in st.session_state:
        st.session_state.SC_HOST = netwIPAddr
    if "SC_PORT" not in st.session_state:
        st.session_state.SC_PORT = os.environ.get("STREAMLIT_LIP_PORT", "9099")
    if "use_https" not in st.session_state:
        st.session_state.use_https = False

    with st.sidebar:
        with st.expander("Node Aliases", expanded=True):
            st.markdown("**Node Alias Map** (identity_file.yaml)")
            uploaded_file = st.file_uploader(
                "Upload identity_file.yaml",
                type=["yaml", "yml"],
                key="IDENTITY_YAML_KEY",
                help="Maps node aliases (e.g. osu1) to their IPs and device groups.",
            )
            if uploaded_file:
                try:
                    identity_data = yaml.safe_load(uploaded_file)
                    st.session_state.identity_data = identity_data
                    st.success(f"Loaded {len(identity_data)} node entries")
                except Exception as e:
                    st.error(f"Could not parse YAML: {e}")

        with st.expander("Redis", expanded=False):
            redis_host = st.text_input("Host", value=st.session_state.REDIS_HOST, key="REDIS_HOST_SUI_KEY")
            redis_port = st.text_input("Port", value=st.session_state.REDIS_PORT, key="REDIS_PORT_SUI_KEY")
            redis_auth_token = st.text_input(
                "Auth Token", value=st.session_state.REDIS_AUTH_TOKEN,
                key="REDIS_AUTH_TOKEN_SUI_KEY", type="password",
            )

        with st.expander("Nebula Manager", expanded=False):
            manager_host = st.text_input("Host", value=st.session_state.MANAGER_HOST, key="MANAGER_HOST_SUI_KEY")
            manager_port = st.text_input("Port", value=st.session_state.MANAGER_PORT, key="MANAGER_PORT_SUI_KEY")
            manager_auth_token = st.text_input(
                "Auth Token", value=st.session_state.MANAGER_AUTH_TOKEN,
                key="MANAGER_AUTH_TOKEN_SUI_KEY", type="password",
            )

        with st.expander("Scarlet Composer Service", expanded=False):
            sc_host = st.text_input("Host", value=st.session_state.SC_HOST, key="SC_HOST_SUI_KEY")
            sc_port = st.text_input("Port", value=st.session_state.SC_PORT, key="SC_PORT_SUI_KEY")

        use_https = st.checkbox("Use HTTPS for Registry", value=st.session_state.use_https)

        if st.button("Save", use_container_width=True):
            st.session_state.REDIS_HOST = redis_host
            st.session_state.REDIS_PORT = redis_port
            st.session_state.REDIS_AUTH_TOKEN = redis_auth_token
            st.session_state.MANAGER_HOST = manager_host
            st.session_state.MANAGER_PORT = manager_port
            st.session_state.MANAGER_AUTH_TOKEN = manager_auth_token
            st.session_state.SC_HOST = sc_host
            st.session_state.SC_PORT = sc_port
            st.session_state.use_https = use_https

            os.environ["REDIS_HOST"] = redis_host
            os.environ["REDIS_PORT"] = redis_port
            os.environ["REDIS_AUTH_TOKEN"] = redis_auth_token
            os.environ["REDIS_DB_HOST"] = redis_host
            os.environ["REDIS_DB_PORT"] = redis_port
            os.environ["REDIS_DB_PWD"] = redis_auth_token

            # MANAGER_HOST/PORT point to the Scarlet Composer Tornado service
            # (for agent containers to call /api/v2/getNodeInfo)
            os.environ["MANAGER_HOST"] = sc_host
            os.environ["MANAGER_PORT"] = sc_port

            # MANAGER_CONTAINER_* point to the Nebula Manager
            os.environ["MANAGER_CONTAINER_HOST"] = manager_host
            os.environ["MANAGER_CONTAINER_PORT"] = manager_port
            os.environ["MANAGER_CONTAINER_AUTH_TOKEN"] = manager_auth_token
            os.environ["NEBULA_AUTH_TOKEN"] = manager_auth_token
            os.environ["APP_ID"] = "ScarletComposer"

            # Persist identity YAML to Redis under the fixed key node-aliases
            if "identity_data" in st.session_state:
                try:
                    import redis as redislib
                    r = redislib.StrictRedis(
                        host=redis_host, port=int(redis_port),
                        password=redis_auth_token, decode_responses=True,
                    )
                    r.set("node-aliases", json.dumps(st.session_state.identity_data))
                    st.toast("Node alias map saved to Redis")
                except Exception as e:
                    st.error(f"Could not save node alias map to Redis: {e}")

            logging.info(f"Settings saved. Composer: {sc_host}:{sc_port}, Redis: {redis_host}:{redis_port}")

        try:
            VERSION = pkg_resources.require("ScarletComposer")[0].version
        except Exception:
            VERSION = "dev"

        st.text(f"ScarletComposer {VERSION}")
