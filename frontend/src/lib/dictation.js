/**
 * Turning dictated speech into draft text.
 *
 * The browser's recogniser hands back bare words: no punctuation, no capitals
 * at sentence starts. These helpers apply the few spoken commands every
 * dictation system understands, and join each new phrase onto the draft the
 * way a person typing it would.
 *
 * The command list is deliberately short. "period" is left out because it is
 * also a word ("the trial period ends"); "full stop" is what an Australian
 * speaker says anyway. Each command must be said as its own words.
 */

const COMMANDS = [
  [/[ \t]*\bnew paragraph\b[ \t]*/gi, "\n\n"],
  [/[ \t]*\bnew line\b[ \t]*/gi, "\n"],
  [/[ \t]*\bfull stop\b/gi, "."],
  [/[ \t]*\bcomma\b/gi, ","],
  [/[ \t]*\bquestion mark\b/gi, "?"],
  [/[ \t]*\bexclamation (?:mark|point)\b/gi, "!"],
];

/** Capitalise the first letter of every sentence: at the start, after . ! ? or a line break. */
function capitaliseSentences(text, startsSentence) {
  const capitalised = text.replace(/([.!?][ \t]+|\n[ \t]*)(\p{Ll})/gu, (_, gap, letter) => gap + letter.toUpperCase());
  return startsSentence ? capitalised.replace(/^(\s*)(\p{Ll})/u, (_, gap, letter) => gap + letter.toUpperCase()) : capitalised;
}

/** One recognised phrase as text: commands applied, spacing tidied. */
export function dictatedText(heard) {
  let text = String(heard || "");
  for (const [pattern, mark] of COMMANDS) text = text.replace(pattern, mark);
  return text
    .replace(/[ \t]+/g, " ")
    .replace(/ ([.,?!])/g, "$1")           // "thanks ," -> "thanks,"
    .replace(/([.,?!])(\p{L})/gu, "$1 $2") // "thanks,see" -> "thanks, see"
    .replace(/^ +| +$/gm, "");
}

/** `existing` with a dictated phrase added at the end, as if typed there. */
export function appendDictation(existing, heard) {
  const before = String(existing || "").replace(/[ \t]+$/, "");
  let text = dictatedText(heard);
  if (!text) return existing;

  const startsSentence = !before.trim() || /[.!?]["')\]]*$/.test(before) || /\n$/.test(before);
  text = capitaliseSentences(text, startsSentence);

  const joins = !before || /\n$/.test(before) || /^[.,?!\n]/.test(text);
  return before + (joins ? "" : " ") + text;
}
