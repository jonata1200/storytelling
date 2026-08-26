# ruff: noqa: E501

from nicegui import ui

from app.config.settings import get_settings
from app.ui.layout.theme_css import THEME_HEAD_HTML
from app.ui.shared.page_config import BRAND_MARK_URL


def apply_body_style() -> None:
    ui.colors(primary="#5aa3f0")
    ui.dark_mode(value=get_settings().user_theme != "light")
    ui.page_title(get_settings().app_name)
    ui.query("body").classes("studio-body")
    ui.add_head_html(f'<link rel="icon" type="image/png" href="{BRAND_MARK_URL}">')
    ui.add_head_html(THEME_HEAD_HTML)
    ui.add_head_html(
        r"""
        <style>
          :root {
            --studio-bg:#05070c;
            --studio-bg-2:#07121d;
            --studio-panel:#0c1722;
            --studio-panel-2:#101f2d;
            --studio-line:rgba(90,163,240,.18);
            --studio-line-strong:rgba(90,163,240,.46);
            --studio-text:#eaf8ff;
            --studio-muted:#86a1b2;
            --studio-cyan:#5aa3f0;
            --studio-blue:#5aa3f0;
            --studio-aqua:#5aa3f0;
            --studio-success:#58d6a7;
            --studio-warning:#ffd166;
            --studio-danger:#ff6b81;
            --studio-glow:0 0 22px rgba(90,163,240,.28);
            --studio-shadow:0 24px 70px rgba(0,0,0,.44);
          }
          html { background:var(--studio-bg); }
          body.studio-body {
            min-height:100vh;
            color:var(--studio-text);
            background:
              linear-gradient(115deg, rgba(90,163,240,.18) 0%, rgba(90,163,240,.07) 28%, transparent 54%),
              linear-gradient(180deg, #05070c 0%, #08131d 48%, #04070c 100%) !important;
            font-family:'DM Sans',sans-serif;
            overflow-x:hidden;
          }
          .studio-body .nicegui-content {
            background:
              linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px),
              linear-gradient(180deg, rgba(255,255,255,.025) 1px, transparent 1px);
            background-size:72px 72px;
          }
          .brand-type {
            font-family:'Manrope',sans-serif;
            letter-spacing:0;
          }
          .acid {
            color:var(--studio-cyan)!important;
            text-shadow:0 0 18px rgba(90,163,240,.38);
          }
          .acid-bg,
          .studio-primary-button {
            background:linear-gradient(135deg, var(--studio-cyan), var(--studio-blue))!important;
            color:#031019!important;
            border:1px solid rgba(90,163,240,.7)!important;
            box-shadow:0 0 0 1px rgba(90,163,240,.18), var(--studio-glow)!important;
            font-weight:700!important;
          }
          .acid-bg:hover,
          .studio-primary-button:hover {
            filter:brightness(1.08);
            box-shadow:0 0 0 1px rgba(90,163,240,.4), 0 0 32px rgba(90,163,240,.38)!important;
          }
          .blue-status-badge,
          .blue-status-badge .q-badge__content,
          .blue-status-badge span {
            color:#ffffff!important;
          }
          .glass,
          .entity-card,
          .q-card {
            color:var(--studio-text)!important;
            background:
              linear-gradient(180deg, rgba(20,38,54,.88), rgba(7,15,24,.92))!important;
            border:1px solid var(--studio-line)!important;
            border-radius:8px!important;
            box-shadow:0 1px 0 rgba(255,255,255,.04) inset, var(--studio-shadow)!important;
          }
          .entity-card {
            position:relative;
            overflow:hidden;
            transition:border-color .18s ease, box-shadow .18s ease, transform .18s ease;
          }
          .entity-card::before {
            content:"";
            position:absolute;
            inset:0;
            pointer-events:none;
            background:linear-gradient(90deg, rgba(90,163,240,.13), transparent 34%, rgba(90,163,240,.08));
            opacity:.42;
          }
          .entity-card > *,
          .glass > * { position:relative; }
          .entity-card:hover {
            transform:translateY(-1px);
            border-color:var(--studio-line-strong)!important;
            box-shadow:0 0 0 1px rgba(90,163,240,.15), 0 22px 68px rgba(0,0,0,.48), var(--studio-glow)!important;
          }
          .chat-shell {
            border-radius:8px!important;
            border:1px solid var(--studio-line-strong)!important;
            background:
              linear-gradient(180deg, rgba(15,31,45,.92), rgba(5,10,16,.94))!important;
            box-shadow:0 0 0 1px rgba(90,163,240,.13), 0 28px 80px rgba(0,0,0,.5), var(--studio-glow)!important;
          }
          .prompt-composer {
            min-height:220px;
          }
          .prompt-composer-input .q-field__control {
            min-height:220px!important;
            border-radius:8px!important;
            background:
              linear-gradient(180deg, rgba(8,18,28,.94), rgba(5,10,16,.96))!important;
            box-shadow:
              inset 0 0 0 1px rgba(90,163,240,.18),
              0 12px 34px rgba(0,0,0,.2)!important;
          }
          .prompt-composer-input.q-field--focused .q-field__control {
            box-shadow:
              inset 0 0 0 1px var(--studio-cyan),
              0 0 24px rgba(90,163,240,.18)!important;
          }
          .prompt-composer-input textarea {
            min-height:160px!important;
            padding:18px 18px 78px!important;
            line-height:1.55!important;
            resize:none!important;
          }
          .prompt-composer-toolbar {
            left:14px;
            right:14px;
            bottom:14px;
            min-height:44px;
            z-index:2;
          }
          .prompt-tool-button {
            min-height:36px!important;
            height:36px;
            padding:0 12px!important;
            color:#d9ecff!important;
            background:rgba(90,163,240,.10)!important;
            border:1px solid rgba(90,163,240,.28)!important;
            box-shadow:inset 0 0 0 1px rgba(255,255,255,.03);
          }
          .prompt-tool-button:hover {
            color:#ffffff!important;
            background:rgba(90,163,240,.18)!important;
            border-color:rgba(90,163,240,.48)!important;
          }
          .prompt-tool-button .q-icon,
          .prompt-tool-button .q-btn__content,
          .prompt-tool-button .q-btn__content span {
            color:inherit!important;
          }
          .prompt-send-button {
            width:44px!important;
            height:44px!important;
            min-height:44px!important;
            flex:0 0 44px;
          }
          .prompt-send-button .q-icon,
          .prompt-send-button .q-btn__content {
            color:#031019!important;
          }
          body:not(.body--dark) .prompt-send-button .q-icon,
          body:not(.body--dark) .prompt-send-button .q-btn__content {
            color:#ffffff!important;
          }
          body:not(.body--dark) .prompt-composer-input .q-field__control {
            background:#ffffff!important;
            box-shadow:
              inset 0 0 0 1px rgba(90,163,240,.24),
              0 14px 34px rgba(29,68,96,.10)!important;
          }
          body:not(.body--dark) .prompt-tool-button {
            color:#256fa8!important;
            background:#edf6ff!important;
            border-color:#c9e2f8!important;
          }
          body:not(.body--dark) .prompt-tool-button:hover {
            color:#0f4770!important;
            background:#dff0ff!important;
            border-color:#9dccf1!important;
          }
          .visual-placeholder {
            background:
              linear-gradient(135deg, rgba(90,163,240,.22), rgba(90,163,240,.08) 42%, rgba(5,10,16,.96) 100%)!important;
          }
          .visual-library-panels,
          .visual-library-panels .q-tab-panels,
          .visual-library-panels .q-panel,
          .visual-library-panels .q-panel > div,
          .visual-library-panels .scroll,
          .visual-library-panels .q-tab-panel {
            height:auto!important;
            max-height:none!important;
            min-height:0!important;
            overflow:visible!important;
          }
          .workspace-header {
            color:var(--studio-text);
            background:
              linear-gradient(90deg, rgba(5,9,15,.96), rgba(10,28,43,.94) 54%, rgba(5,9,15,.96))!important;
            border-bottom:1px solid var(--studio-line)!important;
            box-shadow:0 12px 34px rgba(0,0,0,.34);
            backdrop-filter:blur(18px);
          }
          .workspace-layout {
            background:
              linear-gradient(180deg, rgba(8,22,34,.72), rgba(4,7,12,.88))!important;
          }
          .workspace-main {
            background:transparent!important;
            scrollbar-gutter:stable;
          }
          .right-assistant {
            position:relative;
            width:380px!important;
            min-width:380px!important;
            background:transparent!important;
            border:0!important;
            border-radius:0!important;
            margin:0!important;
            height:100%!important;
            min-height:0!important;
            padding:22px 30px 28px 30px!important;
            box-shadow:none!important;
            backdrop-filter:none;
          }
          .right-assistant::before {
            content:"";
            position:absolute;
            inset:4px 14px 14px 16px;
            pointer-events:none;
            border:1px solid var(--studio-line);
            border-radius:20px;
            background:
              linear-gradient(180deg, rgba(8,19,29,.96), rgba(4,9,15,.98));
            box-shadow:
              0 0 0 1px rgba(90,163,240,.1),
              -18px 18px 52px rgba(0,0,0,.34),
              var(--studio-glow);
            backdrop-filter:blur(18px);
          }
          .right-assistant > * {
            position:relative;
            z-index:1;
          }
          .right-assistant .assistant-chat-messages {
            width:calc(100% + 30px)!important;
            max-width:calc(100% + 30px)!important;
            margin-right:-30px;
            padding-right:30px;
          }
          .assistant-chat-messages {
            scrollbar-width:thin;
            scrollbar-color:rgba(90,163,240,.42) transparent;
          }
          .assistant-chat-bubble.glass,
          .assistant-chat-bubble {
            border-radius:8px!important;
          }
          .assistant-chat-user-bubble {
            background:linear-gradient(135deg, var(--studio-blue), var(--studio-cyan))!important;
            color:#ffffff!important;
          }
          .assistant-chat-user-bubble * { color:#ffffff!important; }
          .desktop-nav {
            background:
              linear-gradient(180deg, rgba(6,11,18,.98), rgba(7,18,29,.98))!important;
            border-color:var(--studio-line)!important;
          }
          .desktop-nav .cursor-pointer:hover {
            background:rgba(90,163,240,.08);
            box-shadow:inset 0 0 0 1px rgba(90,163,240,.18);
          }
          .nav-pill {
            color:var(--studio-muted)!important;
            border-radius:8px!important;
          }
          .nav-pill:hover {
            color:var(--studio-text)!important;
            background:rgba(90,163,240,.09)!important;
            box-shadow:inset 0 0 0 1px rgba(90,163,240,.16);
          }
          .nav-active {
            color:#031019!important;
            background:linear-gradient(135deg, var(--studio-cyan), var(--studio-blue))!important;
            border-color:rgba(90,163,240,.72)!important;
            box-shadow:var(--studio-glow)!important;
          }
          .nav-active .q-btn__content,
          .nav-active .q-btn__content span,
          .nav-active .q-icon { color:#031019!important; }
          .nav-locked,
          .nav-locked:hover {
            color:rgba(134,161,178,.72)!important;
            background:transparent!important;
            box-shadow:none!important;
          }
          .idea-badge-genre {
            background:rgba(90,163,240,.12)!important;
            color:#bdf5ff!important;
            border:1px solid rgba(90,163,240,.24);
          }
          .idea-badge-emotion {
            background:rgba(88,214,167,.12)!important;
            color:#c7ffe7!important;
            border:1px solid rgba(88,214,167,.22);
          }
          .idea-badge-duration {
            background:rgba(255,209,102,.12)!important;
            color:#ffe6a1!important;
            border:1px solid rgba(255,209,102,.2);
          }
          body:not(.body--dark) .idea-badge-genre {
            background:#e4f1ff!important;
            color:#155f9f!important;
            border:1px solid rgba(21,95,159,.28);
          }
          body:not(.body--dark) .idea-badge-emotion {
            background:#e6f6e9!important;
            color:#1e6a48!important;
            border:1px solid rgba(30,106,72,.24);
          }
          body:not(.body--dark) .idea-badge-duration {
            background:#fff3d0!important;
            color:#8a5a00!important;
            border:1px solid rgba(138,90,0,.24);
          }
          .idea-badge-genre,
          .idea-badge-emotion,
          .idea-badge-duration {
            display:inline-flex;
            align-items:center;
            line-height:1.25;
            font-weight:700!important;
            text-shadow:none!important;
          }
          .q-btn {
            border-radius:8px!important;
            min-height:36px;
          }
          .q-field__control {
            background:rgba(8,18,28,.92)!important;
            border-radius:8px!important;
            color:var(--studio-text)!important;
            box-shadow:inset 0 0 0 1px rgba(90,163,240,.1);
          }
          .q-field__control::before {
            border-color:rgba(90,163,240,.18)!important;
          }
          .q-field--focused .q-field__control {
            box-shadow:inset 0 0 0 1px var(--studio-cyan), 0 0 24px rgba(90,163,240,.16);
          }
          .q-field__label,
          .q-placeholder::placeholder {
            color:var(--studio-muted)!important;
          }
          .q-field__native,
          .q-field__input,
          .q-textarea textarea {
            color:var(--studio-text)!important;
          }
          .q-menu,
          .q-dialog__inner > .q-card {
            background:linear-gradient(180deg, var(--studio-panel-2), var(--studio-panel))!important;
            color:var(--studio-text)!important;
            border:1px solid var(--studio-line)!important;
          }
          .q-tab {
            border-radius:8px 8px 0 0;
          }
          .q-tab--active {
            color:var(--studio-cyan)!important;
            text-shadow:0 0 14px rgba(90,163,240,.32);
          }
          .q-badge {
            border-radius:6px!important;
            box-shadow:inset 0 0 0 1px rgba(255,255,255,.08);
          }
          .text-cyan-100,
          .text-cyan-200,
          .text-cyan-300 {
            color:var(--studio-cyan)!important;
          }
          .bg-cyan-900,
          .bg-cyan-950 {
            background:rgba(90,163,240,.14)!important;
          }
          .border-cyan-800 {
            border-color:rgba(90,163,240,.36)!important;
          }
          .bg-slate-900,
          .bg-slate-800,
          .bg-\[\#0b0d0c\],
          .bg-\[\#090b0a\],
          .bg-\[\#0d0f0e\],
          .bg-\[\#0d100e\] {
            background:var(--studio-panel)!important;
          }
          .border-slate-800,
          .border-\[\#222622\],
          .border-\[\#242824\],
          .border-\[\#252925\],
          .border-\[\#292d29\],
          .border-\[\#30362b\],
          .border-\[\#343934\],
          .border-\[\#363b36\] {
            border-color:var(--studio-line)!important;
          }
          .text-slate-100,
          .text-slate-300,
          .text-\[\#b8bdb8\],
          .text-\[\#c8ccc8\],
          .text-\[\#d1d4d1\],
          .text-\[\#d4d8d4\],
          .text-\[\#d7dbd7\],
          .text-\[\#d8dbd8\],
          .text-\[\#d9dcd9\] {
            color:var(--studio-text)!important;
          }
          .text-slate-400,
          .text-slate-500,
          .text-\[\#747a75\],
          .text-\[\#777d78\],
          .text-\[\#7f8580\],
          .text-\[\#858b86\],
          .text-\[\#878d88\],
          .text-\[\#8d938e\],
          .text-\[\#8e948f\],
          .text-\[\#8f9590\],
          .text-\[\#939994\],
          .text-\[\#969c97\],
          .text-\[\#999f9a\],
          .text-\[\#9aa29b\],
          .text-\[\#a9aea9\],
          .text-\[\#aeb3ae\] {
            color:var(--studio-muted)!important;
          }
          .bg-\[\#243342\],
          .bg-\[\#26301f\],
          .bg-\[\#2f3321\],
          .bg-\[\#30362b\] {
            background:rgba(90,163,240,.14)!important;
          }
          .text-\[\#eaf878\],
          .text-\[\#eefa83\],
          .text-\[\#bdc77b\],
          .text-\[\#bfe2ff\] {
            color:var(--studio-aqua)!important;
          }
          ::-webkit-scrollbar { width:8px; height:8px; }
          ::-webkit-scrollbar-track { background:transparent; }
          ::-webkit-scrollbar-thumb {
            background:linear-gradient(180deg, rgba(90,163,240,.44), rgba(90,163,240,.28));
            border-radius:8px;
          }
          body:not(.body--dark).studio-body {
            background:
              linear-gradient(135deg, rgba(90,163,240,.12), transparent 48%),
              linear-gradient(180deg, #eef8ff, #f8fbff)!important;
            color:#07121d!important;
          }
          body:not(.body--dark) .glass,
          body:not(.body--dark) .entity-card,
          body:not(.body--dark) .q-card {
            background:rgba(255,255,255,.88)!important;
            color:#07121d!important;
            border-color:rgba(31,110,160,.16)!important;
            box-shadow:0 20px 60px rgba(13,43,68,.13)!important;
          }
          body:not(.body--dark) .workspace-header {
            color:#07121d!important;
            background:rgba(248,251,255,.95)!important;
            border-bottom-color:rgba(90,163,240,.22)!important;
            box-shadow:0 12px 30px rgba(13,43,68,.12)!important;
          }
          body:not(.body--dark) .workspace-header label,
          body:not(.body--dark) .workspace-header span {
            color:#07121d!important;
            text-shadow:none!important;
          }
          body:not(.body--dark) .workspace-header .workspace-episode {
            color:#5d7488!important;
          }
          body:not(.body--dark) .workspace-layout {
            background:linear-gradient(180deg, #f5faff 0%, #eaf3fb 100%)!important;
          }
          body:not(.body--dark) .workspace-main {
            color:#07121d!important;
            background:transparent!important;
          }
          body:not(.body--dark) .right-assistant {
            color:#07121d!important;
            background:transparent!important;
            border-color:transparent!important;
            box-shadow:none!important;
          }
          body:not(.body--dark) .right-assistant::before {
            border-color:rgba(90,163,240,.22)!important;
            background:rgba(251,253,255,.96)!important;
            box-shadow:
              0 0 0 1px rgba(90,163,240,.08),
              -18px 18px 42px rgba(13,43,68,.1)!important;
          }
          body:not(.body--dark) .right-assistant label,
          body:not(.body--dark) .workspace-main label {
            color:inherit;
            text-shadow:none!important;
          }
          .q-dialog__inner > .q-card,
          .q-dialog__inner > .entity-card {
            background:#0c1722!important;
            background-image:none!important;
            opacity:1!important;
            backdrop-filter:none!important;
          }
          .q-dialog__inner > .entity-card::before {
            display:none!important;
          }
          body:not(.body--dark) .q-dialog__inner > .q-card,
          body:not(.body--dark) .q-dialog__inner > .entity-card {
            background:#ffffff!important;
            background-image:none!important;
            color:#07121d!important;
            opacity:1!important;
            backdrop-filter:none!important;
          }
        </style>
        """
    )
