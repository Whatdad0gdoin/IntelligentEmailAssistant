/**
 * Dictated phrases joined onto a draft (lib/dictation.js): spoken punctuation,
 * capitals at sentence starts, and spacing as a person typing would leave it.
 */

import { describe, expect, it } from "vitest";

import { appendDictation, dictatedText } from "./dictation.js";

describe("spoken punctuation", () => {
  it("turns the commands into marks, without a space before them", () => {
    expect(dictatedText("thanks comma see you on friday full stop"))
      .toBe("thanks, see you on friday.");
    expect(dictatedText("can you make it question mark")).toBe("can you make it?");
    expect(dictatedText("great news exclamation mark")).toBe("great news!");
  });

  it("starts new lines and paragraphs", () => {
    expect(dictatedText("thanks new paragraph regards new line james"))
      .toBe("thanks\n\nregards\njames");
  });

  it("leaves 'period' alone, because it is also a word", () => {
    expect(dictatedText("the trial period ends friday")).toBe("the trial period ends friday");
  });

  it("only matches whole words", () => {
    expect(dictatedText("the commandment")).toBe("the commandment");
  });
});

describe("adding a phrase to the draft", () => {
  it("starts an empty draft with a capital", () => {
    expect(appendDictation("", "hi david comma")).toBe("Hi david,");
  });

  it("adds a space mid-sentence and keeps the case", () => {
    expect(appendDictation("Friday works", "for me full stop")).toBe("Friday works for me.");
  });

  it("capitalises after a sentence ends or a line breaks", () => {
    expect(appendDictation("Friday works.", "see you then")).toBe("Friday works. See you then");
    expect(appendDictation("Hi David,\n", "friday works")).toBe("Hi David,\nFriday works");
    expect(appendDictation("", "yes full stop see you then")).toBe("Yes. See you then");
  });

  it("puts punctuation straight after the last word", () => {
    expect(appendDictation("See you then", "full stop")).toBe("See you then.");
  });

  it("drops trailing spaces before joining, never line breaks", () => {
    expect(appendDictation("Thanks   ", "james")).toBe("Thanks james");
    expect(appendDictation("Thanks,\n\n", "james")).toBe("Thanks,\n\nJames");
  });

  it("ignores a phrase with nothing in it", () => {
    expect(appendDictation("Hello", "   ")).toBe("Hello");
  });
});
