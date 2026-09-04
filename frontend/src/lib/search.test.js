import { describe, expect, it } from "vitest";

import { matchesQuery, newestFirst, normaliseQuery, searchEmails, selectView } from "./search.js";

const EMAILS = [
  { id: "1", sender_name: "Sarah Chen", sender: "sarah.chen.mel@gmail.com",
    subject: "Dinner this weekend?", snippet: "A few of us are getting together Saturday",
    received_at: "2026-08-24T19:10:00+10:00" },
  { id: "2", sender_name: "David Robinson", sender: "d.robinson@northgate.com.au",
    subject: "Project deadline moved to Friday", snippet: "Can we reschedule our Thursday meeting",
    received_at: "2026-08-25T09:24:00+10:00" },
  { id: "3", sender_name: "Monash Enrolments", sender: "no-reply@monash.edu",
    subject: "Semester 2 unit registration now open", snippet: "Your registration window has opened",
    received_at: "2026-08-25T08:10:00+10:00" },
];

describe("matching", () => {
  it("matches on sender name", () => {
    expect(searchEmails(EMAILS, "sarah").map((e) => e.id)).toEqual(["1"]);
  });

  it("matches on email address, so a domain finds a sender", () => {
    expect(searchEmails(EMAILS, "monash.edu").map((e) => e.id)).toEqual(["3"]);
  });

  it("matches on subject", () => {
    expect(searchEmails(EMAILS, "deadline").map((e) => e.id)).toEqual(["2"]);
  });

  it("matches on the preview line", () => {
    expect(searchEmails(EMAILS, "reschedule").map((e) => e.id)).toEqual(["2"]);
  });

  it("is case insensitive", () => {
    expect(searchEmails(EMAILS, "SARAH").map((e) => e.id)).toEqual(["1"]);
  });

  it("matches partial words, so half a name is enough", () => {
    expect(searchEmails(EMAILS, "robin").map((e) => e.id)).toEqual(["2"]);
  });

  it("can match several messages at once", () => {
    expect(searchEmails(EMAILS, "e").length).toBeGreaterThan(1);
  });

  it("returns nothing when nothing matches", () => {
    expect(searchEmails(EMAILS, "zzzznotpresent")).toEqual([]);
  });
});

describe("empty and whitespace queries", () => {
  it("an empty query shows the whole inbox, not an empty one", () => {
    expect(searchEmails(EMAILS, "").length).toBe(EMAILS.length);
  });

  it("whitespace alone is treated as no query", () => {
    expect(normaliseQuery("   ")).toBe("");
    expect(searchEmails(EMAILS, "   ").length).toBe(EMAILS.length);
  });

  it("surrounding whitespace is trimmed rather than failing to match", () => {
    expect(searchEmails(EMAILS, "  sarah  ").map((e) => e.id)).toEqual(["1"]);
  });
});

describe("ordering", () => {
  it("results are newest first", () => {
    expect(searchEmails(EMAILS, "").map((e) => e.id)).toEqual(["2", "3", "1"]);
  });

  it("newestFirst sorts descending by received_at", () => {
    const sorted = [...EMAILS].sort(newestFirst);
    expect(sorted[0].id).toBe("2");
  });
});

describe("robustness", () => {
  it("a missing field does not throw", () => {
    expect(matchesQuery({ subject: "hello" }, "hello")).toBe(true);
    expect(matchesQuery({ subject: "hello" }, "sarah")).toBe(false);
  });

  it("a null email does not throw", () => {
    expect(matchesQuery(null, "x")).toBe(false);
  });

  it("bodies are not searched, since the list only carries snippets", () => {
    const withBody = [{ id: "9", subject: "s", snippet: "p", body: "secret word", received_at: "2026-01-01" }];
    expect(searchEmails(withBody, "secret")).toEqual([]);
  });
});

describe("which view the inbox shows", () => {
  const ORDER = ["Work", "Personal", "Promotions", "Studies", "Review"];
  const GROUPS = {
    Work: [EMAILS[1]],
    Personal: [EMAILS[0]],
    Promotions: [],
    Studies: [EMAILS[2]],
    Review: [],
  };
  const view = (filter, query = "") => selectView({ groups: GROUPS, order: ORDER, filter, query });

  it("All is one flat list, not five stacked groups", () => {
    const v = view("all");
    expect(v.mode).toBe("flat");
    expect(v.list).toHaveLength(3);
  });

  it("choosing a category shows ONLY that category", () => {
    // The reported bug: every group rendered regardless of the chosen chip.
    const v = view("Personal");
    expect(v.mode).toBe("grouped");
    expect(v.names).toEqual(["Personal"]);
  });

  it.each(["Work", "Personal", "Studies"])("%s shows itself and nothing else", (name) => {
    expect(view(name).names).toEqual([name]);
  });

  it("an empty category says so instead of rendering a bare heading", () => {
    const v = view("Promotions");
    expect(v.names).toEqual(["Promotions"]);
    expect(v.empty).toBe(true);
  });

  it("searching flattens, so hits are not buried under five headings", () => {
    const v = view("Work", "sarah");
    expect(v.mode).toBe("flat");
    expect(v.searching).toBe(true);
    expect(v.list.map((e) => e.id)).toEqual(["1"]);
  });

  it("clearing the search returns to the chosen category", () => {
    expect(view("Work", "   ").mode).toBe("grouped");
    expect(view("Work", "   ").names).toEqual(["Work"]);
  });

  it("an unknown filter shows nothing rather than everything", () => {
    expect(view("Nonsense").names).toEqual([]);
  });
});
