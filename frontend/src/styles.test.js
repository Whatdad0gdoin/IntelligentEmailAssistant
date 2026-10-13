/**
 * Stylesheet regression tests.
 *
 * These exist because of a bug that was invisible in code review and obvious on
 * screen: the Approve button rendered as a white rectangle and the AI tools
 * rendered as plain text.
 *
 * The cause was specificity, not a missing rule. `.iq button` sets
 * `background: transparent; border: none` and scores (0,1,1). A rule written as
 * `.ai-approve { background: ... }` scores (0,1,0) and therefore loses, so the
 * button was stripped no matter what its own rule said. Every button reads
 * correctly in the source and wrong in the browser, which is the worst kind of
 * bug to eyeball.
 *
 * So the check is mechanical: any rule that gives a button a background or a
 * border must out-specify the reset.
 */

import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "styles.css"), "utf8");

/** [ids, classes, elements] for one selector. */
function specificity(selector) {
  const clean = selector
    .replace(/::[a-z-]+/g, " ")               // pseudo-elements counted below
    .replace(/:not\(([^)]*)\)/g, " $1 ");     // :not() itself adds nothing
  const ids = (clean.match(/#[\w-]+/g) || []).length;
  const classes =
    (clean.match(/\.[\w-]+/g) || []).length +
    (clean.match(/\[[^\]]+\]/g) || []).length +
    (clean.match(/:[a-z-]+(\([^)]*\))?/g) || []).length;
  const elements = (clean.match(/(^|[\s>+~])[a-z][\w-]*/gi) || []).length;
  return [ids, classes, elements];
}

function beats(a, b) {
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}

/** Every rule in the sheet as { selector, body }. */
function rules() {
  const out = [];
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(withoutComments)) !== null) {
    const selectorList = m[1].trim();
    if (!selectorList || selectorList.startsWith("@")) continue;
    for (const selector of selectorList.split(",")) {
      out.push({ selector: selector.trim(), body: m[2] });
    }
  }
  return out;
}

const RESET = specificity(".iq button");

// Classes actually rendered on a <button>, discovered by scanning the JSX
// rather than listed by hand. A button added next semester is covered without
// anyone remembering to update this file, which is the point: the bug this
// guards against is invisible in review.
function buttonClassesInJsx() {
  const found = new Set();
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".jsx")) {
        const src = readFileSync(full, "utf8");
        // <button ... className="a b" ...> and className={`a ${x}`}
        for (const m of src.matchAll(/<button[^>]*className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
          const raw = (m[1] || m[2] || "").replace(/\$\{[^}]*\}/g, " ");
          for (const cls of raw.split(/\s+/)) {
            if (cls && /^[a-z][\w-]*$/.test(cls)) found.add(cls);
          }
        }
      }
    }
  };
  walk(here);
  return [...found].sort();
}

const BUTTON_CLASSES = buttonClassesInJsx();

describe("the global button reset", () => {
  it("found buttons to check, so this suite is not passing vacuously", () => {
    expect(BUTTON_CLASSES.length).toBeGreaterThan(4);
  });

  it("still exists, so these tests are testing something real", () => {
    expect(css).toMatch(/\.iq button\s*\{[^}]*background\s*:\s*transparent/);
  });

  it.each(BUTTON_CLASSES)(
    "%s declares its background and border with enough specificity to win",
    (cls) => {
      const declaring = rules().filter(
        (r) =>
          r.selector.includes(`.${cls}`) &&
          /(^|;|\s)(background|border)\s*:/.test(r.body) &&
          !r.selector.includes(":hover") &&
          !r.selector.includes(":disabled") &&
          !r.selector.includes(":active")
      );

      // A class with no background/border rule at all is fine - it is meant to
      // inherit the transparent reset (.ai-close, .trace and friends).
      if (declaring.length === 0) return;

      const winners = declaring.filter((r) => beats(specificity(r.selector), RESET));
      expect(
        winners.length,
        `.${cls} sets background/border but every rule loses to .iq button ` +
          `(${RESET.join(",")}). Qualify it as ".iq button.${cls}". ` +
          `Rules found: ${declaring.map((r) => r.selector).join(" | ")}`
      ).toBeGreaterThan(0);
    }
  );
});

describe("contrast", () => {
  const luminance = (hex) => {
    const h = hex.replace("#", "");
    const parts = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
    const [r, g, b] = parts.map((c) =>
      c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    );
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a, b) => {
    const [x, y] = [luminance(a), luminance(b)].sort((m, n) => n - m);
    return (x + 0.05) / (y + 0.05);
  };

  const token = (name) => {
    const m = css.match(new RegExp(`--${name}\\s*:\\s*(#[0-9A-Fa-f]{6})`));
    if (!m) throw new Error(`token --${name} not found`);
    return m[1];
  };

  // WCAG AA: 4.5:1 for body text.
  it.each([
    ["ink", 4.5], ["ink-2", 4.5], ["ink-3", 4.5],
    ["grey", 4.5], ["grey-2", 4.5],
    ["blue", 4.5], ["blue-deep", 4.5],
    ["amber", 4.5], ["coral", 4.5], ["green", 4.5],
  ])("--%s reads on white at AA", (name, min) => {
    expect(ratio(token(name), "#FFFFFF")).toBeGreaterThanOrEqual(min);
  });

  it.each(["ink", "grey", "grey-2", "blue", "amber", "green"])(
    "--%s reads on the paper background at AA",
    (name) => {
      expect(ratio(token(name), token("paper"))).toBeGreaterThanOrEqual(4.5);
    }
  );

  // WCAG 2.1 non-text contrast: 3:1 for the boundary of an interactive control.
  it("the AI tool button border is visible against the white reader card", () => {
    const m = css.match(/\.iq button\.action-btn\s*\{[^}]*border:\s*[\d.]+px\s+solid\s+(#[0-9A-Fa-f]{6})/);
    expect(m, "action-btn border colour not found").not.toBeNull();
    expect(ratio(m[1], "#FFFFFF")).toBeGreaterThanOrEqual(3.0);
  });
});

describe("reader layout", () => {
  it("the message, the toolbar and the panels share one gutter", () => {
    const gutter = (re) => {
      const matches = [...css.matchAll(re)];
      return matches.length ? matches[matches.length - 1][1] : null;
    };
    const body = gutter(/\.reader-body\s*\{[^}]*padding:\s*\d+px\s+(\d+)px/g);
    const toolbar = gutter(/\.reader-toolbar\s*\{[^}]*padding:\s*\d+px\s+(\d+)px/g);
    const panel = gutter(/\.ai-panel\s*\{[^}]*margin-left:\s*(\d+)px/g);
    expect(body).not.toBeNull();
    expect(toolbar).toBe(body);
    expect(panel).toBe(body);
  });

  it("the reader scrolls, so a long message cannot hide the toolbar below it", () => {
    const matches = [...css.matchAll(/\.reader\s*\{([^}]*)\}/g)];
    const last = matches[matches.length - 1][1];
    expect(last).toMatch(/overflow-y:\s*auto/);
  });

  it("the split's row is bounded, so that overflow-y actually takes effect", () => {
    // Measured in Chromium: with the default auto row, an open summary grew the
    // reader to its content (912px in a 527px pane) and the whole page
    // scrolled; the reader's own overflow-y never engaged. jsdom does no
    // layout, so the rule that prevents it is what can be pinned here.
    const rows = [...css.matchAll(/\.inbox-split\s*\{([^}]*)\}/g)]
      .map((m) => m[1].match(/grid-template-rows:\s*([^;]+)/))
      .filter(Boolean)
      .map((m) => m[1].trim());
    // Declared once in the base rule; the narrow-screen override changes only
    // the columns, so it must not redeclare the rows as anything else.
    expect(rows.length).toBeGreaterThan(0);
    for (const value of rows) expect(value).toMatch(/^minmax\(\s*0\s*,\s*1fr\s*\)$/);
  });

  // The list has the page until an email is open (the last section of
  // styles.css): the first column is the whole width, an open email brings it
  // in to 400px, and the change between the two is animated, as is the change
  // back when the email is closed. None of that happens in jsdom, so what it
  // rests on is read from the sheet.
  const sheet = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const squash = (text) => text.replace(/\s+/g, "");

  /** Every `@media <query>` block: where it starts and what is inside it. */
  const mediaBlocks = (query) => {
    const found = [];
    for (const m of sheet.matchAll(/@media([^{]+)\{/g)) {
      if (squash(m[1]) !== squash(query)) continue;
      const start = m.index + m[0].length;
      // Rules nest one level inside the block, so count braces to its end.
      let depth = 1;
      let end = start;
      while (end < sheet.length) {
        if (sheet[end] === "{") depth += 1;
        if (sheet[end] === "}") depth -= 1;
        if (depth === 0) break;
        end += 1;
      }
      found.push({ at: m.index, text: sheet.slice(start, end) });
    }
    return found;
  };

  /** The declarations of the first rule in `text` written with this selector. */
  const ruleBody = (text, selector) => {
    for (const m of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (squash(m[1]) === squash(selector)) return m[2];
    }
    return null;
  };

  /** The value of `prop` among a rule's declarations, or null. */
  const decl = (body, prop) => {
    const m = (body || "").match(new RegExp("(?:^|;)\\s*" + prop + "\\s*:\\s*([^;]+)"));
    return m ? m[1].trim() : null;
  };

  const px = (value) => {
    expect(value).toMatch(/^-?[\d.]+px$/);
    return parseFloat(value);
  };

  // The one-pane rule's query, and its exact opposite: every width gets one
  // layout or the other. `min-width:1081px` would leave 1080.5px with neither.
  const NARROW = "(max-width:1080px)";
  const WIDE = `not all and ${NARROW}`;

  const wideBlock = () => {
    const blocks = mediaBlocks(WIDE);
    expect(blocks, `expected one "@media ${WIDE}" block`).toHaveLength(1);
    return blocks[0];
  };

  /** The base rule, and the split's two states on a wide window. */
  const splitStates = () => {
    const wide = wideBlock().text;
    return {
      base: ruleBody(sheet, ".inbox-split"),
      closed: ruleBody(wide, ".inbox-split"),
      open: ruleBody(wide, ".inbox-split.has-selection"),
    };
  };

  const tracks = (body) => {
    const value = decl(body, "grid-template-columns");
    expect(value, "no grid-template-columns").not.toBeNull();
    const [, first, rest] = value.match(/^(\S+)\s+(.+)$/);
    return { first, rest: squash(rest) };
  };

  /** A rule's `transition` as { property: "duration easing" }. */
  const timings = (body) => {
    const transition = decl(body, "transition");
    expect(transition, "no transition").not.toBeNull();
    return Object.fromEntries(
      transition.split(/,(?![^(]*\))/).map((part) => {
        const [prop, ...rest] = part.trim().split(/\s+/);
        return [prop, rest.join(" ")];
      })
    );
  };

  /** The slide: how long the list's column takes to change, and on what curve. */
  const slide = () => timings(splitStates().closed)["grid-template-columns"];

  it("with nothing open the list's column is the whole width, and an open email restores the split", () => {
    const { base, closed, open } = splitStates();

    expect(tracks(closed).first).toBe("100%");
    // No gap beside a column that is already the full width: 100% and 20px
    // more is 20px wider than the page.
    expect(parseFloat(decl(closed, "column-gap"))).toBe(0);
    // The column and the gap the split has always had.
    expect(tracks(open).first).toBe(tracks(base).first);
    expect(decl(open, "column-gap")).toBe(decl(base, "gap"));
  });

  it("the two states are track lists a browser can animate between", () => {
    const { closed, open } = splitStates();

    // A length or a percentage first in both: 100% to 400px interpolates. 1fr
    // to 400px does not, and the list would jump instead of narrowing.
    expect(tracks(closed).first).toMatch(/^[\d.]+(%|px)$/);
    expect(tracks(open).first).toMatch(/^[\d.]+(%|px)$/);
    // Then the same flexible track, which is the reading pane at no width.
    expect(tracks(closed).rest).toBe("minmax(0,1fr)");
    expect(tracks(open).rest).toBe(tracks(closed).rest);
  });

  it("the split animates its columns, and the gap in step with them", () => {
    const timing = timings(splitStates().closed);

    expect(parseFloat(timing["grid-template-columns"])).toBeGreaterThan(0);
    // Same duration and easing. A gap that opened at once, beside a column
    // still close to 100%, would push the page 20px too wide for a moment.
    expect(timing["column-gap"]).toBe(timing["grid-template-columns"]);
  });

  it("the slide takes about half a second, on a curve that starts and stops at rest", () => {
    const [, seconds, curve] = slide().match(/^([\d.]+)s\s+cubic-bezier\(([^)]+)\)$/);
    const [x1, y1, x2, y2] = curve.split(",").map(Number);

    expect(Number(seconds)).toBeGreaterThanOrEqual(0.4);
    expect(Number(seconds)).toBeLessThanOrEqual(0.6);
    // A curve leaves (0,0) towards its first control point and arrives at
    // (1,1) from its second, so y1 of 0 and y2 of 1 are no speed at the start
    // and none at the end. The curve this replaced, (0.22,1,0.36,1), left at
    // 1/0.22, four and a half times its average speed: measured in Chrome,
    // 482 of the list's 708px were covered in the first 124ms, a jump and
    // then a long tail.
    expect(y1).toBe(0);
    expect(y2).toBe(1);
    expect(x1).toBeGreaterThan(0);
    // The same from either end, so closing is opening backwards.
    expect(x1 + x2).toBeCloseTo(1, 10);
    // Such a curve is fastest half way, at 1/(1 - x1) times its average
    // speed. Twice is the most allowed here: (0.65,0,0.35,1) reaches 2.9
    // times, which puts the jump in the middle instead of at the start.
    expect(1 / (1 - x1)).toBeLessThanOrEqual(2);
  });

  it("the animation is switched off for anyone who asks for reduced motion", () => {
    const off = mediaBlocks("(prefers-reduced-motion:reduce)")
      .filter((block) => decl(ruleBody(block.text, ".inbox-split"), "transition") === "none");

    expect(off, "no reduced-motion rule turns the split's transition off").toHaveLength(1);
    // The pane's fade goes with the slide it is timed to.
    expect(decl(ruleBody(off[0].text, ".inbox-right"), "transition")).toBe("none");
    // Each has the selector of the rule that sets the transition, so it wins
    // only by coming after it.
    expect(off[0].at).toBeGreaterThan(wideBlock().at);
  });

  it("neither state touches the bounded row", () => {
    // The test above reads rules written exactly `.inbox-split`. This one
    // reads the split in any state, and looks for the shorthands and the
    // `display` that would undo the rows without naming them.
    const onSplit = rules().filter((r) => /^\.inbox-split(\.[\w-]+)*$/.test(r.selector));
    expect(onSplit.map((r) => r.selector)).toContain(".inbox-split.has-selection");

    for (const { selector, body } of onSplit) {
      const rows = decl(body, "grid-template-rows");
      if (rows !== null) expect(squash(rows), selector).toBe("minmax(0,1fr)");
      expect(decl(body, "grid-template"), selector).toBeNull();
      expect(decl(body, "grid"), selector).toBeNull();
      expect(decl(body, "display") ?? "grid", selector).toBe("grid");
    }
    const { base } = splitStates();
    expect(decl(base, "display")).toBe("grid");
    expect(squash(decl(base, "grid-template-rows"))).toBe("minmax(0,1fr)");
  });

  it("the reader's minimum width fits the pane in the narrowest window that splits", () => {
    const wide = wideBlock().text;
    const { open } = splitStates();
    // One pixel past the widest window the one-pane rule covers, less the
    // sidebar, the page's padding on both sides, the list and the gap: 329px.
    const narrowest = px(NARROW.match(/max-width:([\d.]+px)/)[1]) + 1;
    const sidebar = px(decl(ruleBody(sheet, ".dash-root"), "grid-template-columns").split(/\s+/)[0]);
    const pagePadding = px(decl(ruleBody(sheet, ".dash-main"), "padding").split(/\s+/)[1]);
    const pane = narrowest - sidebar - 2 * pagePadding - px(tracks(open).first) - px(decl(open, "column-gap"));

    const minimum = px(decl(ruleBody(wide, ".inbox-right > *"), "min-width"));
    expect(minimum).toBeGreaterThan(0);
    // Any larger and the reader's right edge is cut off there for good.
    expect(minimum).toBeLessThanOrEqual(pane);
    // A minimum only uncovers the reader, rather than overflowing the page,
    // if the pane clips it.
    expect(decl(ruleBody(wide, ".inbox-right"), "overflow")).toBe("hidden");
  });

  it("the reader is laid out at its finished width from the start, so it slides in and does not re-wrap", () => {
    const wide = wideBlock().text;
    const { closed, open } = splitStates();

    // The finished width is the split's, less the list and the gap. 100cqi is
    // the split's width only because the split is a size container, in both
    // its states; with no container the unit is the window's width, which is
    // the sidebar and the page's padding too many.
    expect(decl(closed, "container-type")).toBe("inline-size");
    expect(decl(open, "container-type")).toBeNull();
    const width = squash(decl(ruleBody(wide, ".inbox-right > *"), "width") ?? "");
    expect(width).toMatch(/^calc\(100cqi-[\d.]+px\)$/);
    expect(px(width.match(/-([\d.]+px)\)$/)[1])).toBe(px(tracks(open).first) + px(decl(open, "column-gap")));
    // It is wider than the pane until the pane has finished widening, and
    // only the pane's clipping keeps that off the page.
    expect(decl(ruleBody(wide, ".inbox-right"), "overflow")).toBe("hidden");
  });

  it("inside the split the reader has no entrance of its own: the pane fades on the slide's clock", () => {
    const wide = wideBlock().text;

    // cardUp rises and scales as well as fading, and ran on top of the slide.
    expect(decl(ruleBody(wide, ".inbox-right > *"), "animation")).toBe("none");
    // The pane is clear when closed and solid when open, and goes from one to
    // the other exactly as the columns do, whichever way they are going.
    expect(parseFloat(decl(ruleBody(wide, ".inbox-right"), "opacity"))).toBe(0);
    expect(parseFloat(decl(ruleBody(wide, ".inbox-split.has-selection .inbox-right"), "opacity"))).toBe(1);
    expect(timings(ruleBody(wide, ".inbox-right")).opacity).toBe(slide());
  });

  it("cardUp is left on everything else that has it, the narrow window's reader included", () => {
    for (const selector of [".login-card", ".reader", ".feature-card", ".ai-panel"]) {
      expect(decl(ruleBody(sheet, selector), "animation"), selector).toMatch(/^cardUp\s/);
    }
  });

  it("a closed reader is kept for longer than the slide, and only where the sheet slides", () => {
    const inbox = readFileSync(join(here, "views", "Inbox.jsx"), "utf8");
    // The timer stands in for a transitionend that never comes. Shorter than
    // the slide, it would take the reader away while it could still be seen.
    const fallback = Number(inbox.match(/CLOSE_FALLBACK_MS\s*=\s*(\d+)/)[1]);
    expect(fallback).toBeGreaterThan(parseFloat(slide()) * 1000);
    // The transition whose end it waits for is the one this sheet runs.
    expect(inbox).toContain('"grid-template-columns"');
    // And it asks this sheet's two queries before keeping a reader at all: the
    // one-pane rule's, and the one that turns the slide off. On any other
    // answer it would wait out a slide that was never going to run.
    expect(squash(inbox)).toContain(`matchMedia("${squash(NARROW)}")`);
    expect(squash(inbox)).toContain('matchMedia("(prefers-reduced-motion:reduce)")');
  });

  it("a pane with a reader in it is padded in by what it overhangs, with room for the reader's shadow", () => {
    const wide = wideBlock().text;
    // The rule reads the pane, not the mark on the split. The mark goes the
    // moment a close begins, and a shadow tied to it would be cut while the
    // reader was still on its way out. An empty pane does not overhang: it
    // would lie over the edge of the list.
    for (const selector of [".inbox-right", ".inbox-split.has-selection .inbox-right"]) {
      expect(decl(ruleBody(wide, selector), "margin"), selector).toBeNull();
      expect(decl(ruleBody(wide, selector), "padding"), selector).toBeNull();
    }
    const pane = ruleBody(wide, ".inbox-right:not(:empty)");
    expect(pane, "no rule for a pane with something in it").not.toBeNull();
    const sides = (value) => {
      const p = value.split(/\s+/).map(px);
      return [p[0], p[1] ?? p[0], p[2] ?? p[0], p[3] ?? p[1] ?? p[0]];
    };
    const padding = sides(decl(pane, "padding"));

    // Equal and opposite on every side, or the reader is no longer the size
    // and in the place it was before the pane started clipping.
    expect(sides(decl(pane, "margin")).map((v) => -v)).toEqual(padding);
    // --shadow-md, the reader's shadow: its larger layer is `0 <y> <blur>`.
    const [offsetY, blur] = css.match(/--shadow-md:\s*0\s+(\d+)px\s+(\d+)px/).slice(1).map(Number);
    const [top, right, bottom, left] = padding;
    expect(top).toBeGreaterThanOrEqual(blur - offsetY);
    expect(right).toBeGreaterThanOrEqual(blur);
    expect(bottom).toBeGreaterThanOrEqual(blur + offsetY);
    expect(left).toBeGreaterThanOrEqual(blur);
  });

  it("none of it applies at 1080px and below, where the split is still one pane at a time", () => {
    const narrow = mediaBlocks(NARROW).map((block) => block.text).join(" ");
    expect(squash(decl(ruleBody(narrow, ".inbox-split"), "grid-template-columns"))).toBe("1fr");
    expect(decl(ruleBody(narrow, ".inbox-right"), "display")).toBe("none");
    expect(decl(ruleBody(narrow, ".inbox-split.has-selection .inbox-left"), "display")).toBe("none");
    expect(decl(ruleBody(narrow, ".inbox-split.has-selection .inbox-right"), "display")).toBe("block");

    // With the wide-window block taken out, nothing left animates the split or
    // makes it a container, clips or fades the pane or makes it overhang, or
    // holds the reader to a width or takes its entrance away.
    const rest = sheet.replace(wideBlock().text, "");
    const own = /(^|\s)\.inbox-(split(\.[\w-]+)*|right(:not\(:empty\))?(\s*>\s*\*)?)$/;
    const wideOnly = ["overflow", "opacity", "margin", "padding", "width", "container-type", "animation"];
    let seen = 0;
    for (const m of rest.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = m[1].trim();
      if (!own.test(selector)) continue;
      seen += 1;
      expect(decl(m[2], "transition") ?? "none", selector).toBe("none");
      expect(parseFloat(decl(m[2], "min-width") ?? "0"), selector).toBe(0);
      for (const prop of wideOnly) expect(decl(m[2], prop), `${selector} { ${prop} }`).toBeNull();
    }
    // The base rules and the one-pane rules, at least, were read.
    expect(seen).toBeGreaterThanOrEqual(5);
  });
});

describe("translation (FR-07)", () => {
  it("keeps the translation's line breaks, which the backend asked the model to keep", () => {
    // jsdom does not load this sheet, so the component test can only see the
    // "\n" in the text node; whether the browser shows it is decided here.
    const rule = css.match(/\.ai-translation-body\s*\{([^}]*)\}/);
    expect(rule, ".ai-translation-body rule not found").not.toBeNull();
    expect(rule[1]).toMatch(/white-space:\s*pre-wrap/);
  });
});

describe("the selected row is not clipped", () => {
  /** Last declaration of `prop` within any rule whose selector matches. */
  const lastDecl = (selectorNeedle, prop) => {
    const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, "");
    let value = null;
    for (const m of withoutComments.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!m[1].includes(selectorNeedle)) continue;
      const pattern = new RegExp("(?:^|;)\\s*" + prop + "\\s*:\\s*([^;]+)", "g");
      const d = [...m[2].matchAll(pattern)];
      if (d.length) value = d[d.length - 1][1].trim();
    }
    return value;
  };

  it("draws its ring inside the element, so a scroll container cannot cut it", () => {
    // The list scrolls and .inbox-left is overflow:hidden, so an outset ring on
    // the first row loses its top and left edges. inset survives both.
    const shadow = lastDecl(".mail-row.sel", "box-shadow");
    expect(shadow, ".mail-row.sel has no box-shadow rule").not.toBeNull();
    expect(shadow).toMatch(/inset/);
  });

  it("the scrolling list has padding on every side, not just the right", () => {
    const padding = lastDecl(".mail-list", "padding");
    expect(padding, ".mail-list has no padding rule").not.toBeNull();
    const parts = padding.split(/\s+/);
    // A single value applies to all sides; otherwise every side must be > 0.
    const sides = parts.length === 1 ? [parts[0], parts[0], parts[0], parts[0]]
      : parts.length === 2 ? [parts[0], parts[1], parts[0], parts[1]]
      : parts.length === 3 ? [parts[0], parts[1], parts[2], parts[1]]
      : parts;
    for (const side of sides) {
      expect(parseFloat(side), `padding side "${side}" leaves no room for the ring`).toBeGreaterThan(0);
    }
  });
});

describe("the inbox is one divided list", () => {
  /** Rules whose selector passes `match` and that declare `prop`, in file order. */
  const declaring = (match, prop) => {
    const pattern = new RegExp("(?:^|;)\\s*" + prop + "\\s*:\\s*([^;]+)");
    return rules()
      .filter((r) => match(r.selector) && pattern.test(r.body))
      .map((r) => ({ selector: r.selector, value: r.body.match(pattern)[1].trim() }));
  };
  /** The cascade's choice among them: the most specific, and the later on a tie. */
  const winner = (found) =>
    found.reduce(
      (best, r) => (best && beats(specificity(best.selector), specificity(r.selector)) ? best : r),
      null
    );

  // The line between two emails is the second one's top border.
  const divider = winner(declaring((s) => /button\.mail-row\s*\+\s*\.mail-row$/.test(s), "border-top"));

  it("the rows touch, so the line is all that separates them", () => {
    const gap = winner(declaring((s) => /\.mail-list$/.test(s), "gap"));
    expect(gap, ".mail-list has no gap rule").not.toBeNull();
    expect(parseFloat(gap.value)).toBe(0);
  });

  it("a line separates each row from the one before, and survives the button reset", () => {
    // .mail-row is a <button>, and `.iq button` sets border:none.
    expect(divider, "no border-top rule for button.mail-row + .mail-row").not.toBeNull();
    expect(parseFloat(divider.value)).toBeGreaterThan(0);
    expect(divider.value).toMatch(/\bsolid\b/);
    expect(beats(specificity(divider.selector), RESET)).toBe(true);
  });

  it("the line is not one of the two pale greys, which do not show on a white row", () => {
    const colour = divider && divider.value.match(/#[0-9A-Fa-f]{6}/);
    expect(colour, "the divider colour should be a literal hex").not.toBeNull();
    const pale = ["line", "line-2"].map(
      (name) => css.match(new RegExp(`--${name}\\s*:\\s*(#[0-9A-Fa-f]{6})`))[1].toUpperCase()
    );
    expect(pale).not.toContain(colour[0].toUpperCase());
  });

  it("a row does not move on hover, now that there is a row against it", () => {
    const moved = winner(declaring((s) => s.includes(".mail-row") && s.includes(":hover"), "transform"));
    expect(moved ? moved.value : "none").toBe("none");
  });
});
