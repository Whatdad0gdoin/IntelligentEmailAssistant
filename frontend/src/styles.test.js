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
});
