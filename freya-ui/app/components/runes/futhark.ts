/**
 * The Elder Futhark — the 24 runes of the oldest runic alphabet, in their
 * three ættir (families of eight), with the meaning each carries. The UI uses
 * them as ornament and as meaning: a rune per activity phase, per tool kind,
 * per mode, and carved transliterations of panel titles.
 */

export interface Rune {
  glyph: string;
  name: string;
  sound: string;
  meaning: string;
}

export const FUTHARK: Rune[] = [
  // Freyr's ætt
  { glyph: "ᚠ", name: "Fehu", sound: "f", meaning: "wealth" },
  { glyph: "ᚢ", name: "Uruz", sound: "u", meaning: "strength" },
  { glyph: "ᚦ", name: "Thurisaz", sound: "th", meaning: "the thorn" },
  { glyph: "ᚨ", name: "Ansuz", sound: "a", meaning: "the voice of Odin" },
  { glyph: "ᚱ", name: "Raidho", sound: "r", meaning: "the journey" },
  { glyph: "ᚲ", name: "Kenaz", sound: "k", meaning: "the torch" },
  { glyph: "ᚷ", name: "Gebo", sound: "g", meaning: "the gift" },
  { glyph: "ᚹ", name: "Wunjo", sound: "w", meaning: "joy" },
  // Hagal's ætt
  { glyph: "ᚺ", name: "Hagalaz", sound: "h", meaning: "the storm" },
  { glyph: "ᚾ", name: "Nauthiz", sound: "n", meaning: "need" },
  { glyph: "ᛁ", name: "Isa", sound: "i", meaning: "stillness" },
  { glyph: "ᛃ", name: "Jera", sound: "j", meaning: "the harvest" },
  { glyph: "ᛇ", name: "Eihwaz", sound: "ei", meaning: "the yew, Yggdrasil" },
  { glyph: "ᛈ", name: "Perthro", sound: "p", meaning: "mystery" },
  { glyph: "ᛉ", name: "Algiz", sound: "z", meaning: "protection" },
  { glyph: "ᛊ", name: "Sowilo", sound: "s", meaning: "the sun" },
  // Tyr's ætt
  { glyph: "ᛏ", name: "Tiwaz", sound: "t", meaning: "order" },
  { glyph: "ᛒ", name: "Berkano", sound: "b", meaning: "growth" },
  { glyph: "ᛖ", name: "Ehwaz", sound: "e", meaning: "partnership" },
  { glyph: "ᛗ", name: "Mannaz", sound: "m", meaning: "humankind" },
  { glyph: "ᛚ", name: "Laguz", sound: "l", meaning: "flow" },
  { glyph: "ᛜ", name: "Ingwaz", sound: "ng", meaning: "gestation" },
  { glyph: "ᛞ", name: "Dagaz", sound: "d", meaning: "daylight" },
  { glyph: "ᛟ", name: "Othala", sound: "o", meaning: "heritage" },
];

/** Runic word separator (U+16EB, runic single punctuation). */
export const RUNE_SEP = "᛫";

const LETTER: Record<string, string> = {
  a: "ᚨ", b: "ᛒ", c: "ᚲ", d: "ᛞ", e: "ᛖ", f: "ᚠ", g: "ᚷ", h: "ᚺ", i: "ᛁ",
  j: "ᛃ", k: "ᚲ", l: "ᛚ", m: "ᛗ", n: "ᚾ", o: "ᛟ", p: "ᛈ", q: "ᚲ", r: "ᚱ",
  s: "ᛊ", t: "ᛏ", u: "ᚢ", v: "ᚹ", w: "ᚹ", x: "ᚲᛊ", y: "ᛃ", z: "ᛉ",
};

/** Transliterate Latin text into Elder Futhark (decorative, not linguistic). */
export function toRunes(text: string): string {
  const s = text.toLowerCase();
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const two = s.slice(i, i + 2);
    if (two === "th") { out += "ᚦ"; i++; continue; }
    if (two === "ng") { out += "ᛜ"; i++; continue; }
    const ch = s[i];
    if (LETTER[ch]) out += LETTER[ch];
    else if (/\s|[-_/]/.test(ch)) { if (!out.endsWith(RUNE_SEP)) out += RUNE_SEP; }
    // digits and punctuation are dropped: runes had neither
  }
  return out.replace(new RegExp(`^${RUNE_SEP}|${RUNE_SEP}$`, "g"), "");
}

/** A rune for each dashboard mode, by meaning. Unknown modes get Jera. */
export const MODE_RUNE: Record<string, string> = {
  default: "ᚨ",             // Ansuz — her voice
  night_guardian: "ᛉ",      // Algiz — protection
  language_learning: "ᚷ",   // Gebo — the gift of words
  coding: "ᛏ",              // Tiwaz — order
  brainstorming: "ᚲ",       // Kenaz — the torch of ideas
  complex_tasks: "ᛇ",       // Eihwaz — the world tree, deep work
  trading_teacher: "ᚠ",     // Fehu — wealth
  horny: "ᚹ",               // Wunjo — joy
};

export const modeRune = (id: string) => MODE_RUNE[id] ?? "ᛃ";
