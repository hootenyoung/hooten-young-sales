"""Render static HTML previews of the landing page for every role
combination + a sample "Forbidden" screen.

Useful for product / design reviews when you want to see how a
non-admin user with limited roles will experience the platform
without having to create test accounts.

Run with:  uv run python scripts/preview_role_views.py

Outputs files into /tmp/hy-role-views/.  Open the folder and click
through each scenario in a browser.
"""

from __future__ import annotations

from pathlib import Path

OUT_DIR = Path("/tmp/hy-role-views")  # noqa: S108 — dev-only preview artefacts


# Brand palette — mirrors theme.ts / LandingPage.tsx
GOLD = "#bb8c3f"
GOLD_LIGHT = "#e9c46a"
INK = "#0f0a07"
CREAM = "#faf6ee"
PANEL = "rgba(253, 251, 245, 0.62)"


# Each section's identity colour + icon (SVG so it embeds cleanly)
SECTION_DEFS = {
    "distribution": {
        "title": "Distribution",
        "eyebrow": "Sales · Wholesale Flow",
        "caption": "Invoiced volume, distributor performance, and white-space across the chain.",
        "tone": "#326eb8",
        # truck icon (Material Outlined "local_shipping")
        "icon_svg": """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
              <path d="M20 8h-3V4H3c-1.1 0-2 .9-2 2v11h2c0 1.66 1.34 3 3 3s3-1.34 3-3h6c0 1.66 1.34 3 3 3s3-1.34 3-3h2v-5l-3-4zM6 18.5c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm13.5-9 1.96 2.5H17V9.5h2.5zM18 18.5c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/>
            </svg>
        """,
    },
    "depletions": {
        "title": "Depletions",
        "eyebrow": "Sales · Retail Pull-Through",
        "caption": "State, account, and product depletions trends with monthly comparisons.",
        "tone": "#a86b1e",
        # whisky / glass icon
        "icon_svg": """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
              <path d="M3 2l2.6 12.07c.21.99 1.07 1.93 2.4 1.93h8c1.33 0 2.19-.94 2.4-1.93L21 2H3zm9 17c-1.1 0-2 .9-2 2h4c0-1.1-.9-2-2-2zm-5.27-12L5.96 4h12.08l-.77 3H6.73z"/>
            </svg>
        """,
    },
    "marketing": {
        "title": "Marketing",
        "eyebrow": "Intelligence & Insights",
        "caption": "Competitor watch, social patterns, and content recommendations.",
        "tone": "#22865a",
        # megaphone icon
        "icon_svg": """
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
              <path d="M18 11v2h4v-2h-4zm-2 6.61c.96.71 2.21 1.65 3.2 2.39.4-.53.8-1.07 1.2-1.6-.99-.74-2.24-1.68-3.2-2.4-.4.54-.8 1.08-1.2 1.61zM20.4 5.6c-.4-.53-.8-1.07-1.2-1.6-.99.74-2.24 1.68-3.2 2.4.4.53.8 1.07 1.2 1.6.96-.72 2.21-1.65 3.2-2.4zM4 9c-1.1 0-2 .9-2 2v2c0 1.1.9 2 2 2h1v4h2v-4h1l5 3V6L8 9H4zm11.5 3c0-1.33-.58-2.53-1.5-3.35v6.69c.92-.81 1.5-2.01 1.5-3.34z"/>
            </svg>
        """,
    },
}


SCENARIOS: list[dict[str, object]] = [
    {
        "filename": "01_distribution_only.html",
        "scenario_label": "User with role: distribution",
        "scenario_caption": (
            "An analyst who only handles distributor invoices.  Lands on the platform and "
            "sees a single section card; the user menu shows Profile + Sign out but no Admin "
            "link."
        ),
        "roles": ["distribution"],
        "is_admin": False,
    },
    {
        "filename": "02_depletions_only.html",
        "scenario_label": "User with role: depletions",
        "scenario_caption": (
            "An analyst who only handles retail pull-through.  Same shell as the previous "
            "scenario — just a different section card visible."
        ),
        "roles": ["depletions"],
        "is_admin": False,
    },
    {
        "filename": "03_marketing_only.html",
        "scenario_label": "User with role: marketing",
        "scenario_caption": (
            "A marketing analyst with no sales access.  Only the Marketing card is reachable; "
            "the rest of the platform is invisible to them."
        ),
        "roles": ["marketing"],
        "is_admin": False,
    },
    {
        "filename": "04_distribution_and_depletions.html",
        "scenario_label": "User with roles: distribution + depletions",
        "scenario_caption": (
            "A sales analyst with both halves of the sales section.  Two cards land "
            "side-by-side; the layout adapts naturally as more cards are added."
        ),
        "roles": ["distribution", "depletions"],
        "is_admin": False,
    },
    {
        "filename": "05_all_three_non_admin.html",
        "scenario_label": "User with roles: distribution + depletions + marketing (NOT admin)",
        "scenario_caption": (
            "A full analytics user — three cards, but no admin tooling.  The user menu still "
            "omits the Admin entry, so they can't reach /admin even if they type it in (the "
            "RequireRole gate stops them with a Forbidden screen — see file 07)."
        ),
        "roles": ["distribution", "depletions", "marketing"],
        "is_admin": False,
    },
    {
        "filename": "06_admin_full_access.html",
        "scenario_label": "Admin user (wildcard — sees every section)",
        "scenario_caption": (
            "Administrators get every section regardless of explicit role grants — admin is "
            "a wildcard in RequireRole.  Same three cards plus an Admin entry in the user "
            "menu (Manage users, roles, audit trail)."
        ),
        "roles": ["admin"],
        "is_admin": True,
    },
    {
        "filename": "07_forbidden_section.html",
        "scenario_label": "Forbidden — what users see if they try to open a section they don't have",
        "scenario_caption": (
            "If a depletions-only user types /sales/distribution or /marketing into the URL "
            "bar (or follows an old bookmark), the RequireRole gate intercepts and shows a "
            "branded 'no access' page with a way back to the home screen."
        ),
        "roles": ["depletions"],
        "is_admin": False,
        "is_forbidden_view": True,
    },
]


# ---------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------


def _section_card(key: str) -> str:
    s = SECTION_DEFS[key]
    tone = s["tone"]
    tone_soft = _rgba_from_hex(str(tone), 0.06)
    tone_border = _rgba_from_hex(str(tone), 0.28)
    return f"""
    <div class="card" style="border-color:{tone_border};">
        <div class="card-rule"></div>
        <div class="card-icon" style="background:{tone_soft}; border-color:{tone_border}; color:{tone};">
            {s["icon_svg"]}
        </div>
        <div class="card-title">{s["title"]}</div>
        <div class="card-rule-short"></div>
        <div class="card-eyebrow">{s["eyebrow"]}</div>
        <div class="card-caption">{s["caption"]}</div>
    </div>
    """


def _rgba_from_hex(hex_color: str, alpha: float) -> str:
    v = hex_color.removeprefix("#")
    r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _user_menu(*, is_admin: bool) -> str:
    """Tiny mock of the top-right user menu so reviewers can see when
    the Admin entry is present vs absent."""
    admin_row = ""
    if is_admin:
        admin_row = """
            <li><span class="menu-icon">⚙</span> Administration</li>
            <li class="menu-sep"></li>
        """
    return f"""
    <div class="user-menu">
        <div class="user-chip">
            <span class="user-avatar">P</span>
            <span class="user-name">Prasad Y.</span>
            <span class="user-caret">▾</span>
        </div>
        <div class="user-menu-popover">
            <ul>
                <li><span class="menu-icon">👤</span> My profile</li>
                <li class="menu-sep"></li>
                {admin_row}
                <li><span class="menu-icon">↗</span> Sign out</li>
            </ul>
        </div>
    </div>
    """


def _landing(scenario: dict[str, object]) -> str:
    cards_html = "".join(_section_card(k) for k in scenario["roles"] if k in SECTION_DEFS)  # type: ignore[union-attr]
    role_list = ", ".join(scenario["roles"]) or "(none)"  # type: ignore[arg-type]
    admin_label = "yes (wildcard)" if scenario["is_admin"] else "no"
    return f"""
        {_user_menu(is_admin=bool(scenario["is_admin"]))}
        <div class="hero">
            <img src="https://ops-dev.hootenyoung.com/brand/hy-logo.png"
                 alt="Hooten Young"
                 width="160"
                 onerror="this.style.display='none'" />
            <div class="hero-divider">
                <span class="rule"></span>
                <span class="eyebrow">Internal Platform</span>
                <span class="rule"></span>
            </div>
        </div>

        <div class="grid grid-{len(scenario["roles"]) if not scenario["is_admin"] else 3}">  # type: ignore[arg-type]
            {cards_html if cards_html else '<div class="no-access">No sections available for this user.</div>'}
        </div>

        <div class="legend">
            <div><span class="legend-key">Signed-in roles</span> {role_list}</div>
            <div><span class="legend-key">Admin wildcard</span> {admin_label}</div>
        </div>
    """


def _forbidden() -> str:
    return """
        <div class="hero">
            <img src="https://ops-dev.hootenyoung.com/brand/hy-logo.png"
                 alt="Hooten Young"
                 width="140"
                 onerror="this.style.display='none'" />
        </div>

        <div class="forbidden-card">
            <div class="forbidden-icon">⊘</div>
            <div class="forbidden-title">No access to this section</div>
            <div class="forbidden-lead">
                You don't have the role required to view <strong>/sales/distribution</strong>.
                If you think this is an error, ask an administrator to grant you the
                <code>distribution</code> role.
            </div>
            <a class="forbidden-cta" href="#">Return to home</a>
        </div>

        <div class="legend">
            <div><span class="legend-key">Signed-in roles</span> depletions</div>
            <div><span class="legend-key">Tried to open</span> /sales/distribution</div>
            <div><span class="legend-key">Outcome</span> blocked by RequireRole, redirected away</div>
        </div>
    """


_PAGE_TEMPLATE = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>__TITLE__</title>
<style>
  body {{
    margin: 0;
    background: {CREAM};
    font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif;
    color: {INK};
    min-height: 100vh;
  }}
  /* Title placeholder injected by Python */
  /* Scenario banner — sticky at top so reviewers know what they're looking at */
  .scenario-bar {{
    background: linear-gradient(135deg, {GOLD_LIGHT} 0%, {GOLD} 55%, #8e6a2a 100%);
    color: {INK};
    padding: 14px 28px;
    font-size: 12.5px;
    letter-spacing: 0.04em;
    font-weight: 600;
    border-bottom: 1px solid rgba(15,10,7,0.12);
  }}
  .scenario-bar .label {{ font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.18em; font-size: 11px; }}
  .scenario-bar .caption {{ display:block; margin-top:5px; font-weight:500;
    color: rgba(15,10,7,0.78); font-size:12px; line-height:1.5; max-width: 880px; }}

  /* Brand chrome */
  .stage {{
    position: relative;
    padding: 56px 24px 80px;
    max-width: 1280px;
    margin: 0 auto;
  }}
  .hero {{ text-align:center; margin-bottom: 28px; }}
  .hero img {{ height: 100px; width:auto; display:block; margin: 0 auto 18px; }}
  .hero-divider {{ display:flex; align-items:center; justify-content:center;
    gap: 14px; max-width: 360px; margin: 0 auto; }}
  .hero-divider .rule {{ flex:1; height:1px;
    background: linear-gradient(90deg, transparent, {GOLD}); }}
  .hero-divider .rule:last-child {{ background: linear-gradient(90deg, {GOLD}, transparent); }}
  .hero-divider .eyebrow {{ font-size:10px; font-weight:700; color:{GOLD};
    text-transform:uppercase; letter-spacing:0.36em; white-space: nowrap; }}

  /* Card grid */
  .grid {{ display:grid; gap: 18px; max-width: 920px; margin: 0 auto;
    grid-template-columns: repeat(3, 1fr); }}
  .grid-1 {{ grid-template-columns: 1fr; max-width: 320px; }}
  .grid-2 {{ grid-template-columns: repeat(2, 1fr); max-width: 640px; }}
  .grid-3 {{ grid-template-columns: repeat(3, 1fr); }}
  @media (max-width: 720px) {{
    .grid {{ grid-template-columns: 1fr; max-width: 360px; }}
  }}

  /* Card */
  .card {{ position:relative; background: {PANEL};
    backdrop-filter: blur(8px) saturate(1.05);
    border: 1px solid rgba(255,255,255,0.55); border-radius: 6px;
    padding: 30px 22px; text-align:center; overflow:hidden;
    transition: transform 220ms ease, box-shadow 220ms ease;
    box-shadow: 0 1px 2px rgba(45,45,44,0.02), 0 8px 22px rgba(45,45,44,0.05); }}
  .card-rule {{ position:absolute; top:0; left:0; right:0; height:1px;
    background: linear-gradient(to right, transparent, {GOLD}, transparent); opacity:0.55; }}
  .card-icon {{ width:48px; height:48px; border-radius:50%; border:1px solid; margin: 0 auto 14px;
    display:flex; align-items:center; justify-content:center; }}
  .card-title {{ font-family:'Playfair Display','Palatino',Georgia,serif;
    font-size: 26px; font-weight:500; letter-spacing:-0.015em; line-height:1.1;
    color:{INK}; margin-bottom: 8px; }}
  .card-rule-short {{ width: 22px; height:1px; background:{GOLD}; opacity:0.7;
    margin: 0 auto 12px; }}
  .card-eyebrow {{ font-size:9.5px; font-weight:700; color:{GOLD};
    letter-spacing:0.26em; text-transform:uppercase; margin-bottom: 12px; }}
  .card-caption {{ font-size:12px; color:rgba(15,10,7,0.6); line-height:1.55;
    max-width: 240px; margin: 0 auto; }}

  /* No-access fallback (zero-card edge case) */
  .no-access {{ background: rgba(187,140,63,0.06);
    border:1px dashed {GOLD}66; padding: 36px; border-radius: 6px;
    text-align:center; color:rgba(15,10,7,0.6); font-size: 13px; }}

  /* Forbidden screen */
  .forbidden-card {{ max-width: 520px; margin: 60px auto 0; padding: 40px 36px;
    background: {PANEL}; border: 1px solid rgba(187,140,63,0.22);
    border-radius: 8px; text-align:center; position:relative; }}
  .forbidden-card::before {{ content:""; position:absolute; top:0; left:0; right:0;
    height:2px; background: linear-gradient(to right, transparent, {GOLD}, transparent); }}
  .forbidden-icon {{ width: 56px; height:56px; border-radius:50%;
    background: rgba(178,47,47,0.08); color:#b22f2f;
    display:inline-flex; align-items:center; justify-content:center;
    font-size: 28px; margin-bottom: 16px; }}
  .forbidden-title {{ font-size: 19px; font-weight:700; color:{INK}; letter-spacing:-0.01em;
    margin-bottom: 10px; }}
  .forbidden-lead {{ font-size:13.5px; color:rgba(15,10,7,0.7); line-height:1.55;
    margin-bottom: 24px; }}
  .forbidden-lead code {{ background: rgba(187,140,63,0.12); color:#8e6a2a;
    padding: 1px 6px; border-radius:3px; font-size:12px; }}
  .forbidden-cta {{ display:inline-block; padding: 11px 24px;
    background: linear-gradient(135deg, {GOLD_LIGHT} 0%, {GOLD} 55%, #8e6a2a 100%);
    color:{INK}; text-decoration:none; font-size: 11.5px; font-weight:700;
    letter-spacing:0.06em; text-transform: uppercase; border-radius:3px; }}

  /* Legend at the bottom of the stage — explains the scenario state */
  .legend {{ max-width: 720px; margin: 60px auto 0; padding: 18px 22px;
    background: rgba(187,140,63,0.06); border:1px solid rgba(187,140,63,0.22);
    border-radius: 6px; font-size: 12px; color: rgba(15,10,7,0.72); }}
  .legend > div {{ display:flex; justify-content:space-between; gap:18px;
    padding: 4px 0; border-bottom: 1px dashed rgba(187,140,63,0.22); }}
  .legend > div:last-child {{ border-bottom: none; }}
  .legend-key {{ text-transform:uppercase; letter-spacing:0.16em;
    font-size:10px; font-weight:700; color:{GOLD}; }}

  /* User menu mock */
  .user-menu {{ position:absolute; top: 18px; right: 24px; z-index:5;
    display:flex; flex-direction:column; align-items:flex-end; gap:6px; }}
  .user-chip {{ display:flex; align-items:center; gap: 8px;
    background:rgba(187,140,63,0.10); border:1px solid rgba(187,140,63,0.32);
    padding: 5px 12px 5px 5px; border-radius: 999px; font-size: 12px;
    color: {INK}; font-weight:600; }}
  .user-avatar {{ width:24px; height:24px; border-radius:50%;
    background: linear-gradient(135deg, {GOLD_LIGHT} 0%, {GOLD} 55%, #8e6a2a 100%);
    color: {INK}; display:inline-flex; align-items:center; justify-content:center;
    font-size:11px; font-weight:700; }}
  .user-caret {{ color: rgba(15,10,7,0.45); font-size:10px; margin-left:2px; }}
  .user-menu-popover {{ background:#fdf9f0; border:1px solid rgba(187,140,63,0.28);
    border-radius: 6px; box-shadow: 0 8px 22px rgba(142,106,42,0.12);
    padding: 6px; min-width: 200px; position:relative;
    margin-top: 4px; }}
  .user-menu-popover::before {{ content:""; position:absolute; top:0; left:0; right:0;
    height:1px; background: linear-gradient(to right, transparent, {GOLD}, transparent); }}
  .user-menu-popover ul {{ list-style:none; margin:0; padding:0; }}
  .user-menu-popover li {{ padding: 8px 10px; font-size:12.5px; color:{INK};
    display:flex; align-items:center; gap: 8px; border-radius:3px; }}
  .user-menu-popover li:hover {{ background: rgba(187,140,63,0.10); }}
  .menu-icon {{ width: 18px; text-align:center; color:{GOLD}; }}
  .menu-sep {{ height:1px; background: rgba(187,140,63,0.22); padding:0;
    margin: 4px 4px; }}
</style>
</head>
<body>
  <div class="scenario-bar">
    <div><span class="label">Scenario</span> &middot; __LABEL__</div>
    <span class="caption">__CAPTION__</span>
  </div>
  <div class="stage">
    __BODY__
  </div>
</body>
</html>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for scenario in SCENARIOS:
        body = _forbidden() if scenario.get("is_forbidden_view") else _landing(scenario)
        html = (
            _PAGE_TEMPLATE.replace("__TITLE__", str(scenario["scenario_label"]))
            .replace("__LABEL__", str(scenario["scenario_label"]))
            .replace("__CAPTION__", str(scenario["scenario_caption"]))
            .replace("__BODY__", body)
        )
        target = OUT_DIR / str(scenario["filename"])
        target.write_text(html, encoding="utf-8")
        print(f"  → {target}")

    print(f"\nOpen in browser:  open {OUT_DIR}")


if __name__ == "__main__":
    main()
