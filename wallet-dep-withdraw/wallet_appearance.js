/**
 * Apply wallet overlay appearance settings to a root .overlay-stack element.
 * Shared by OBS overlay and constructor preview.
 */
(function (global) {
  function setVar(el, name, value) {
    el.style.setProperty(name, value);
  }

  /** 0–100. Accepts legacy 0–1 fractions. */
  function opacityPct(val, fallback) {
    var n = Number(val);
    if (!Number.isFinite(n)) n = fallback;
    if (n > 0 && n <= 1) n = Math.round(n * 100);
    return Math.max(0, Math.min(100, Math.round(n)));
  }

  function applyPlateOpacity(nodes, enabled, pct) {
    var show = enabled !== false && pct > 0;
    var op = show ? String(pct / 100) : "0";
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (!el) continue;
      el.style.opacity = op;
      el.style.display = show ? "" : "none";
      el.style.visibility = show ? "visible" : "hidden";
    }
  }

  function applyWalletAppearance(root, s) {
    if (!root || !s) return;

    setVar(root, "--ww-card-width", (s.card_width || 268) + "px");
    setVar(root, "--ww-card-radius", (s.card_radius || 20) + "px");
    setVar(root, "--ww-card-pad-y", (s.card_padding_y || 10) + "px");
    setVar(root, "--ww-card-pad-x", (s.card_padding_x || 13) + "px");
    setVar(root, "--ww-bar-gap", (s.bar_gap || 16) + "px");
    setVar(root, "--ww-stack-gap", (s.stack_gap || 13) + "px");
    setVar(root, "--ww-icon-size", (s.icon_size || 56) + "px");
    setVar(root, "--ww-icon-radius", (s.icon_radius || 14) + "px");
    setVar(root, "--ww-amt-font", (s.amt_font_size || 42) + "px");
    setVar(root, "--ww-dep-amt-font", (s.dep_amt_font_size || s.amt_font_size || 42) + "px");
    setVar(root, "--ww-out-amt-font", (s.out_amt_font_size || s.amt_font_size || 42) + "px");
    setVar(root, "--ww-card-lbl-font", (s.card_label_font_size || 32) + "px");
    setVar(root, "--ww-dep-lbl-font", (s.dep_label_font_size || s.card_label_font_size || 32) + "px");
    setVar(root, "--ww-out-lbl-font", (s.out_label_font_size || s.card_label_font_size || 32) + "px");
    setVar(root, "--ww-likes-font", (s.likes_font_size || 40) + "px");
    setVar(root, "--ww-likes-radius", (s.likes_card_radius || 18) + "px");

    setVar(root, "--ww-dep-amt", s.dep_amt_color || "#eef9ff");
    setVar(root, "--ww-dep-lbl", s.dep_label_color || "#7dd3fc");
    setVar(root, "--ww-out-empty-amt", s.out_empty_amt_color || "#f0a0a0");
    setVar(root, "--ww-out-filled-amt", s.out_filled_amt_color || "#4ade80");
    setVar(root, "--ww-out-lbl", s.out_label_color || "#f0a0a0");
    setVar(root, "--ww-out-filled-lbl", s.out_filled_label_color || "#86efac");
    setVar(root, "--ww-likes-lbl", s.likes_label_color || "#c9a86e");
    setVar(root, "--ww-likes-cur", s.likes_cur_color || "#fff8ee");
    setVar(root, "--ww-likes-goal", s.likes_goal_color || "#9a9288");

    setVar(root, "--ww-dep-border", s.dep_border_color || "rgba(186, 230, 253, 0.42)");
    setVar(root, "--ww-dep-bg-1", s.dep_bg_1 || "#2a4256");
    setVar(root, "--ww-dep-bg-2", s.dep_bg_2 || "#1a2e42");
    setVar(root, "--ww-out-empty-border", s.out_empty_border || "rgba(248, 113, 113, 0.42)");
    setVar(root, "--ww-out-empty-bg-1", s.out_empty_bg_1 || "#4d2228");
    setVar(root, "--ww-out-empty-bg-2", s.out_empty_bg_2 || "#32161b");
    setVar(root, "--ww-out-filled-border", s.out_filled_border || "rgba(74, 222, 128, 0.32)");
    setVar(root, "--ww-out-filled-bg-1", s.out_filled_bg_1 || "#1a3024");
    setVar(root, "--ww-out-filled-bg-2", s.out_filled_bg_2 || "#102218");
    setVar(root, "--ww-likes-border", s.likes_border_color || "rgba(212, 175, 95, 0.26)");
    setVar(root, "--ww-likes-bg-1", s.likes_bg_1 || "#2a2620");
    setVar(root, "--ww-likes-bg-2", s.likes_bg_2 || "#1a1713");
    setVar(root, "--ww-likes-fill-1", s.likes_fill_1 || "#d4af5f");
    setVar(root, "--ww-likes-fill-2", s.likes_fill_2 || "#f0d78c");

    var moneyPct = opacityPct(s.money_bg_opacity, 100);
    var likesPct = opacityPct(s.likes_bg_opacity, 100);
    // Keep CSS vars for constructor preview fallbacks
    setVar(root, "--ww-money-bg-opacity", String(s.money_bg_enabled === false ? 0 : moneyPct / 100));
    setVar(root, "--ww-likes-bg-opacity", String(s.likes_bg_enabled === false ? 0 : likesPct / 100));

    // OBS CEF often breaks opacity: var(--x) — set inline on plates
    applyPlateOpacity(
      root.querySelectorAll(".card > .card-bg"),
      s.money_bg_enabled,
      moneyPct
    );
    applyPlateOpacity(
      root.querySelectorAll(".likes-card > .card-bg"),
      s.likes_bg_enabled,
      likesPct
    );

    var align = s.align_h === "left" ? "flex-start" : s.align_h === "right" ? "flex-end" : "center";
    root.style.alignItems = align;

    var mode = s.card_side_mode;
    if (mode !== "icon" && mode !== "text" && mode !== "none") {
      mode = s.show_icons === false ? "none" : "icon";
    }

    root.classList.toggle("no-glow", s.glow_enabled === false);
    root.classList.toggle("no-money-bg", s.money_bg_enabled === false || moneyPct <= 0);
    root.classList.toggle("no-likes-bg", s.likes_bg_enabled === false || likesPct <= 0);
    root.classList.toggle("side-icon", mode === "icon");
    root.classList.toggle("side-text", mode === "text");
    root.classList.toggle("side-none", mode === "none");
    root.classList.toggle("hide-icons", mode !== "icon");

    var dep = root.querySelector(".card.dep");
    var out = root.querySelector(".card.out");
    var likes = root.querySelector(".likes-card");
    if (dep) dep.style.display = s.show_dep === false ? "none" : "";
    if (out) out.style.display = s.show_out === false ? "none" : "";
    if (likes) {
      // runtime hide из дока важнее конструкторного show_likes
      if (likes.classList.contains("likes-visually-hidden")) {
        likes.style.display = "none";
      } else {
        likes.style.display = s.show_likes === false ? "none" : "";
      }
    }

    var depLbl = root.querySelector(".card.dep .card-lbl");
    var outLbl = root.querySelector(".card.out .card-lbl");
    if (depLbl && typeof s.dep_label === "string") depLbl.textContent = s.dep_label;
    if (outLbl && typeof s.out_label === "string") outLbl.textContent = s.out_label;

    var likesLbl = root.querySelector(".likes-lbl");
    if (likesLbl && typeof s.likes_label === "string") {
      likesLbl.textContent = s.likes_label;
    }
  }

  function settingsUrl(token) {
    var u = new URL("/wallet/api/widget-settings", location.origin);
    if (token) u.searchParams.set("token", token);
    return u.toString();
  }

  async function fetchWalletAppearance(token) {
    var res = await fetch(settingsUrl(token), { credentials: "same-origin" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    var data = await res.json();
    return (data && data.settings) || data;
  }

  global.applyWalletAppearance = applyWalletAppearance;
  global.fetchWalletAppearance = fetchWalletAppearance;
  global.walletSettingsUrl = settingsUrl;
})(typeof window !== "undefined" ? window : globalThis);
