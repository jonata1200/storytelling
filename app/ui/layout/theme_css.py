# ruff: noqa: E501

THEME_HEAD_HTML = r"""
        <meta name="theme-color" content="#090b0a">
        <style>
          @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');
          :root { --ink:#080a09; --panel:#111412; --line:#272c28; --acid:#5aa3f0; --muted:#969c97; }
          body.studio-body { background:var(--ink); color:#f4f5f2; font-family:'DM Sans',sans-serif; }
          body:not(.body--dark).studio-body { background:#f4f5ef; color:#171a17; }
          body:not(.body--dark) .glass,
          body:not(.body--dark) .entity-card { background:#ffffff; border-color:#d9ded7; }
          body:not(.body--dark) .chat-shell { box-shadow:0 20px 60px rgba(25,35,25,.12); }
          body:not(.body--dark) .desktop-nav,
          body:not(.body--dark) .right-assistant,
          body:not(.body--dark) .bg-slate-900,
          body:not(.body--dark) .bg-slate-800,
          body:not(.body--dark) .bg-\[\#0b0d0c\],
          body:not(.body--dark) .bg-\[\#090b0a\],
          body:not(.body--dark) .bg-\[\#0d0f0e\],
          body:not(.body--dark) .bg-\[\#0d100e\] { background:#f8faf6!important; }
          body:not(.body--dark) .border-slate-800,
          body:not(.body--dark) .border-\[\#222622\],
          body:not(.body--dark) .border-\[\#242824\],
          body:not(.body--dark) .border-\[\#252925\],
          body:not(.body--dark) .border-\[\#343934\],
          body:not(.body--dark) .border-\[\#363b36\] { border-color:#d9ded7!important; }
          body:not(.body--dark) .text-slate-100,
          body:not(.body--dark) .text-slate-300,
          body:not(.body--dark) .text-\[\#b8bdb8\],
          body:not(.body--dark) .text-\[\#c8ccc8\],
          body:not(.body--dark) .text-\[\#d1d4d1\],
          body:not(.body--dark) .text-\[\#d4d8d4\],
          body:not(.body--dark) .text-\[\#d7dbd7\],
          body:not(.body--dark) .text-\[\#d8dbd8\],
          body:not(.body--dark) .text-\[\#d9dcd9\] { color:#20261f!important; }
          body:not(.body--dark) .text-slate-400,
          body:not(.body--dark) .text-\[\#747a75\],
          body:not(.body--dark) .text-\[\#777d78\],
          body:not(.body--dark) .text-\[\#7f8580\],
          body:not(.body--dark) .text-\[\#858b86\],
          body:not(.body--dark) .text-\[\#878d88\],
          body:not(.body--dark) .text-\[\#8d938e\],
          body:not(.body--dark) .text-\[\#8e948f\],
          body:not(.body--dark) .text-\[\#8f9590\],
          body:not(.body--dark) .text-\[\#939994\],
          body:not(.body--dark) .text-\[\#969c97\],
          body:not(.body--dark) .text-\[\#999f9a\],
          body:not(.body--dark) .text-\[\#9aa29b\] { color:#626b62!important; }
          body:not(.body--dark) .bg-\[\#243342\] { background:#edf6ff!important; }
          body:not(.body--dark) .bg-\[\#2f3321\],
          body:not(.body--dark) .bg-\[\#30362b\],
          body:not(.body--dark) .bg-\[\#26301f\] { background:#eff5dc!important; }
          body:not(.body--dark) .text-\[\#bfe2ff\] { color:#5aa3f0!important; }
          body:not(.body--dark) .text-\[\#dff57b\],
          body:not(.body--dark) .text-\[\#e6f59b\],
          body:not(.body--dark) .text-\[\#eaf878\] { color:#4f6417!important; }
          body:not(.body--dark) .visual-placeholder { background:radial-gradient(circle at 70% 15%,#e6e9c9 0,#d9ddcf 42%,#eef0e9 80%); }
          body:not(.body--dark) .q-field__control { background:#ffffff!important; }
          body:not(.body--dark) .q-field__native,
          body:not(.body--dark) .q-field__input,
          body:not(.body--dark) .q-textarea textarea { color:#171a17!important; }
          body:not(.body--dark) .q-menu { background:#ffffff!important; color:#171a17!important; }
          .studio-body .nicegui-content { padding:0; }
          .brand-type { font-family:'Manrope',sans-serif; letter-spacing:-.04em; }
          .glass { background:rgba(17,20,18,.88); border:1px solid var(--line); }
          .acid { color:var(--acid); }
          .acid-bg { background:var(--acid)!important; color:#10120d!important; }
          .workspace-header {
            display:grid;
            grid-template-columns:minmax(260px,.75fr) minmax(420px,1.25fr) auto;
            align-items:center;
            gap:16px;
            min-height:64px;
            padding:0 20px;
          }
          .workspace-titlebar { min-width:0; flex-wrap:nowrap!important; }
          .workspace-titlebar .q-btn { flex:0 0 auto; }
          .workspace-nav {
            min-width:0;
            overflow-x:auto;
            flex-wrap:nowrap!important;
            justify-content:center;
            scrollbar-width:none;
          }
          .workspace-nav::-webkit-scrollbar { display:none; }
          .workspace-actions { flex-wrap:nowrap!important; justify-content:flex-end; min-width:max-content; }
          .mobile-bottom-nav {
            display:none;
            position:fixed;
            left:12px;
            right:12px;
            bottom:calc(10px + env(safe-area-inset-bottom));
            z-index:40;
            min-height:62px;
            padding:8px;
            border:1px solid rgba(90,163,240,.26);
            border-radius:18px;
            background:rgba(8,15,22,.94);
            box-shadow:0 18px 48px rgba(0,0,0,.42);
            backdrop-filter:blur(18px);
            gap:6px;
          }
          .mobile-nav-item {
            appearance:none;
            border:0;
            border-radius:14px;
            background:transparent;
            color:#9db1c0;
            display:flex;
            flex:1 1 0;
            min-width:0;
            min-height:48px;
            align-items:center;
            justify-content:center;
            flex-direction:column;
            gap:2px;
            padding:5px 3px;
            cursor:pointer;
          }
          .mobile-nav-icon { font-size:21px!important; line-height:1!important; }
          .mobile-nav-label {
            max-width:100%;
            overflow:hidden;
            text-overflow:ellipsis;
            white-space:nowrap;
            font-size:11px!important;
            line-height:14px!important;
            color:inherit!important;
          }
          .mobile-nav-active {
            color:#ffffff!important;
            background:rgba(90,163,240,.22)!important;
            box-shadow:inset 0 0 0 1px rgba(90,163,240,.34);
          }
          .mobile-nav-disabled {
            color:rgba(157,177,192,.42)!important;
            cursor:not-allowed;
          }
          .nav-pill {
            border:1px solid transparent;
            color:#8c918d;
            transition:.2s ease;
            flex:0 0 auto;
            min-height:36px!important;
            height:36px;
          }
          .nav-pill .q-btn__content { flex-wrap:nowrap; white-space:nowrap; gap:6px; }
          .nav-pill:hover { color:#eaf3ff; background:#171a18; }
          .nav-active { color:#ffffff!important; background:var(--acid)!important; border-color:rgba(255,255,255,.45)!important; min-width:92px; }
          .nav-active .q-btn__content,
          .nav-active .q-btn__content span,
          .nav-active .q-icon { color:#ffffff!important; opacity:1!important; }
          .nav-locked { color:#5aa3f0!important; background:transparent!important; border-color:transparent!important; }
          .nav-locked:hover { color:#5aa3f0!important; background:transparent!important; }
          body:not(.body--dark) .nav-pill { color:#6d756f; }
          body:not(.body--dark) .nav-pill:hover { color:#5aa3f0; background:#edf6ff; }
          body:not(.body--dark) .nav-active { color:#ffffff!important; background:var(--acid)!important; border-color:transparent!important; }
          body:not(.body--dark) .nav-active .q-btn__content,
          body:not(.body--dark) .nav-active .q-btn__content span,
          body:not(.body--dark) .nav-active .q-icon { color:#ffffff!important; opacity:1!important; }
          body:not(.body--dark) .nav-locked,
          body:not(.body--dark) .nav-locked:hover { color:#5aa3f0!important; background:transparent!important; border-color:transparent!important; }
          body:not(.body--dark) .mobile-bottom-nav {
            background:rgba(248,250,246,.94);
            border-color:#d2e5f7;
            box-shadow:0 18px 44px rgba(13,43,68,.14);
          }
          body:not(.body--dark) .mobile-nav-item { color:#5d7488; }
          body:not(.body--dark) .mobile-nav-active {
            color:#0f3956!important;
            background:#e5f3ff!important;
            box-shadow:inset 0 0 0 1px rgba(90,163,240,.28);
          }
          body:not(.body--dark) .mobile-nav-disabled { color:rgba(93,116,136,.42)!important; }
          .idea-badge-genre { background:#243342!important; color:#dcecff!important; }
          .idea-badge-emotion { background:#2f3321!important; color:#f1ff9f!important; }
          .idea-badge-duration { background:#2d2636!important; color:#eadfff!important; }
          body:not(.body--dark) .idea-badge-genre { background:#edf6ff!important; color:#5aa3f0!important; }
          body:not(.body--dark) .idea-badge-emotion { background:#eaf5c6!important; color:#40540e!important; }
          body:not(.body--dark) .idea-badge-duration { background:#eee4ff!important; color:#54358a!important; }
          .entity-card { background:#151816; border:1px solid #252a26; transition:.2s ease; }
          .entity-card:hover { transform:translateY(-2px); border-color:#555d4c; }
          .workspace-summary-card.entity-card {
            display:flex!important;
            flex-direction:column!important;
            gap:16px!important;
            min-height:132px!important;
            padding:24px!important;
            overflow:visible!important;
          }
          .visual-placeholder { background:radial-gradient(circle at 70% 15%,#4e5531 0,#24281e 32%,#141614 70%); }
          .chat-shell { box-shadow:0 30px 90px rgba(0,0,0,.45); }
          .script-upload-control {
            width:auto!important;
            min-width:172px;
          }
          .script-upload-control .q-uploader {
            width:auto!important;
            min-width:172px;
            max-height:44px!important;
            border-radius:14px!important;
            background:rgba(90,163,240,.10)!important;
            border:1px solid rgba(90,163,240,.30)!important;
            box-shadow:none!important;
            overflow:hidden!important;
          }
          .script-upload-control .q-uploader__header {
            min-height:42px!important;
            padding:0 12px!important;
            background:transparent!important;
            color:#d9ecff!important;
          }
          .script-upload-control .q-uploader__list,
          .script-upload-control .q-uploader__subtitle {
            display:none!important;
          }
          body:not(.body--dark) .script-upload-control .q-uploader {
            background:#edf6ff!important;
            border-color:#c9e2f8!important;
          }
          body:not(.body--dark) .script-upload-control .q-uploader__header {
            color:#256fa8!important;
          }
          .q-field__label { color: #b9beb9 !important; }
          .q-field__native, .q-field__input, .q-textarea textarea {
            color: #f8fafc !important;
          }
          .q-field__control {
            background: #181b19 !important;
            border-radius: 14px !important;
          }
          .assistant-chat-messages { overscroll-behavior:contain; }
          .assistant-chat-bubble { white-space:pre-wrap; overflow-wrap:anywhere; }
          .assistant-chat-user-bubble,
          .assistant-chat-user-bubble * { color:#ffffff!important; }
          .assistant-chat-input .q-field__control { min-height:48px!important; height:auto!important; max-height:132px!important; }
          .assistant-chat-input .q-field__native,
          .assistant-chat-input.q-textarea textarea {
            min-height:24px!important;
            max-height:96px!important;
            line-height:20px!important;
            padding-top:12px!important;
            padding-bottom:12px!important;
            resize:none!important;
            overflow-y:auto!important;
          }
          .script-editor-textarea,
          .script-editor-textarea .q-field__control,
          .script-editor-textarea .q-field__native,
          .script-editor-textarea textarea {
            height:100%!important;
            min-height:0!important;
          }
          .storyboard-prompt-textarea,
          .storyboard-prompt-textarea .q-field__control,
          .storyboard-prompt-textarea .q-field__native,
          .storyboard-prompt-textarea textarea {
            height:100%!important;
            min-height:0!important;
          }
          .script-editor-textarea textarea,
          .storyboard-prompt-textarea textarea {
            resize:none!important;
            overflow-y:auto!important;
          }
          .storyboard-frame-media,
          .storyboard-frame-media .q-img,
          .storyboard-frame-media .q-img__container,
          .storyboard-frame-media .q-img__image {
            width:100%!important;
            height:100%!important;
          }
          .storyboard-frame-media .q-img__image {
            object-fit:cover!important;
          }
          body.studio-body:has(.workspace-layout) {
            overflow:hidden;
          }
          .studio-body .nicegui-content:has(.workspace-layout) {
            height:100vh;
            height:100dvh;
            overflow:hidden;
          }
          .workspace-layout {
            margin:0!important;
            gap:0!important;
            height:calc(100vh - 64px);
            height:calc(100dvh - 64px);
            min-height:calc(100vh - 64px);
            overflow:hidden!important;
          }
          .workspace-layout > * { margin-top:0!important; }
          .workspace-main {
            height:calc(100vh - 64px)!important;
            height:calc(100dvh - 64px)!important;
            min-height:0!important;
          }
          .right-assistant {
            margin-top:0!important;
            padding-top:0!important;
            height:100%!important;
            overflow:hidden!important;
            box-sizing:border-box;
          }
          .right-assistant > :first-child { margin-top:0!important; }
          .right-assistant::-webkit-scrollbar { display:none; }
          .q-field__control::before { border-color: #303530 !important; }
          .q-field__control::after { color: var(--acid) !important; }
          .q-field--focused .q-field__label { color: var(--acid) !important; }
          .q-placeholder::placeholder { color: #777d78 !important; }
          .q-menu { background: #151816 !important; color: #f8fafc !important; }
          ::-webkit-scrollbar { width:7px; height:7px } ::-webkit-scrollbar-thumb { background:#363b36; border-radius:10px }
          @media(max-width:1180px){
            .workspace-header {
              grid-template-columns:minmax(240px,1fr) auto;
              grid-template-areas:"title actions" "nav nav";
              height:auto!important;
              padding-top:8px;
              padding-bottom:8px;
              row-gap:8px;
            }
            .workspace-titlebar { grid-area:title; }
            .workspace-nav { grid-area:nav; justify-content:flex-start; }
            .workspace-actions { grid-area:actions; }
            .workspace-layout {
              height:calc(100vh - 112px)!important;
              height:calc(100dvh - 112px)!important;
              min-height:calc(100vh - 112px)!important;
            }
            .workspace-main {
              height:calc(100vh - 112px)!important;
              height:calc(100dvh - 112px)!important;
            }
          }
          @media(max-width:900px){
            .desktop-nav{display:none!important}
            .mobile-bottom-nav{display:flex!important}
            body.studio-body:has(.mobile-home-nav) .nicegui-content{padding-bottom:88px!important}
            .workspace-header{
              grid-template-columns:minmax(0,1fr) auto;
              grid-template-areas:"title actions";
              min-height:64px;
              padding:8px 12px;
            }
            .workspace-titlebar{grid-area:title;gap:8px!important}
            .workspace-titlebar .q-img{width:34px!important;height:34px!important}
            .workspace-titlebar .q-btn{width:34px!important;height:34px!important}
            .workspace-titlebar .q-badge{display:none!important}
            .workspace-actions{grid-area:actions;gap:6px!important;min-width:0}
            .workspace-export-button{min-width:42px!important;padding:0 10px!important}
            .workspace-export-button .q-btn__content span{display:none!important}
            .workspace-layout{
              height:calc(100vh - 136px)!important;
              height:calc(100dvh - 136px)!important;
              min-height:calc(100vh - 136px)!important;
            }
            .workspace-main{
              height:calc(100vh - 136px)!important;
              height:calc(100dvh - 136px)!important;
              padding:18px!important;
            }
            .right-assistant{display:none!important}
          }
          @media(max-width:520px){
            .mobile-bottom-nav{left:8px;right:8px;bottom:calc(8px + env(safe-area-inset-bottom));border-radius:16px}
            .mobile-nav-label{font-size:10px!important}
            .workspace-header{padding-left:10px;padding-right:10px}
            .workspace-titlebar .font-semibold{max-width:44vw!important}
            .workspace-main{padding:14px!important}
            .entity-card{border-radius:8px!important}
          }
        </style>
        """
