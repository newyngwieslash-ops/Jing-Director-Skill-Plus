import fs from "node:fs/promises";
import path from "node:path";

const args = parseArgs(process.argv.slice(2));

if (!args.input) {
  console.error("Usage: node validate-character-bible.mjs --input character_bible.json [--strict] [--verbose]");
  process.exit(1);
}

const inputPath = path.resolve(args.input);
const strict = Boolean(args.strict);
const verbose = Boolean(args.verbose);
const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const characters = normalizeCharacters(data.characters);

if (!characters.length) {
  console.error(JSON.stringify({
    ok: false,
    inputPath,
    error: "No characters found. Expected top-level `characters` array or object."
  }, null, 2));
  process.exit(1);
}

const minimumMissing = [];
const recommendedMissing = [];
const seenNames = new Map();
const duplicateNames = [];

for (const character of characters) {
  const name = getName(character);
  const normalizedName = normalizeName(name);

  if (!name) addMissing(minimumMissing, character, "name");
  if (!hasVisualTraits(character)) addMissing(minimumMissing, character, "visual_traits");
  if (!hasKeyVisualTraits(character)) addMissing(minimumMissing, character, "key_visual_traits");
  for (const field of recommendedFields(character)) {
    addMissing(recommendedMissing, character, field);
  }

  if (normalizedName) {
    const existing = seenNames.get(normalizedName);
    if (existing) {
      duplicateNames.push({ normalizedName, first: existing, duplicate: name });
    } else {
      seenNames.set(normalizedName, name);
    }
  }
}

const ok = minimumMissing.length === 0 && duplicateNames.length === 0 && (!strict || recommendedMissing.length === 0);
const result = {
  ok,
  inputPath,
  strict,
  characterCount: characters.length,
  duplicateNames,
  minimumMissing,
  recommendedMissingCount: recommendedMissing.length,
  recommendedMissing: verbose ? recommendedMissing : recommendedMissing.slice(0, 20),
  truncatedRecommendedMissing: !verbose && recommendedMissing.length > 20,
  note: "minimumMissing fails normal validation; recommendedMissing fails only with --strict."
};

console.log(JSON.stringify(result, null, 2));
process.exit(ok ? 0 : 1);

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      i += 1;
    }
  }
  return parsed;
}

function normalizeCharacters(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (value && typeof value === "object") {
    return Object.entries(value).map(([id, character]) => {
      if (character && typeof character === "object" && !Array.isArray(character)) {
        return { id, ...character };
      }
      return { id, value: character };
    });
  }
  return [];
}

function getName(character) {
  return firstText(character.name, character.name_cn, character.name_en, character.id);
}

function normalizeName(value) {
  return String(value ?? "")
    .replace(/\s*（[^）]*）/g, "")
    .replace(/\s*\([^)]*\)/g, "")
    .replace(/[@#]/g, "")
    .replace(/[\s_]+/g, " ")
    .trim()
    .toLowerCase();
}

function hasVisualTraits(character) {
  return hasText(character.visual_traits)
    || hasObject(character.physical_design)
    || hasObject(character.face_design)
    || hasObject(character.costume_system)
    || hasItems(character.image_prompt_tokens);
}

function hasKeyVisualTraits(character) {
  return hasItems(character.key_visual_traits)
    || hasItems(character.image_prompt_tokens)
    || hasItems(character.do_not_change)
    || hasItems(character.continuity_rules)
    || hasItems(character.narrative_function);
}

function hasDialogueTraits(character) {
  return hasText(character.dialogue_traits) || hasObject(character.voice_behavior);
}

function recommendedFields(character) {
  const missing = [];
  if (!hasText(character.id)) missing.push("id");
  if (!hasItems(character.aliases)) missing.push("aliases");
  if (!hasText(character.era_background)) missing.push("era_background");
  if (!hasText(character.occupation) && !hasText(character.role)) missing.push("occupation");
  if (!hasText(character.role_description) && !hasItems(character.narrative_function)) missing.push("role_description");
  if (!hasText(character.visual_traits)) missing.push("visual_traits");
  if (!hasItems(character.key_visual_traits)) missing.push("key_visual_traits");
  if (!hasText(character.dialogue_traits)) missing.push("dialogue_traits");
  if (!hasObject(character.reference_assets)) missing.push("reference_assets");
  if (!hasText(character.triple_view_prompt)) missing.push("triple_view_prompt");
  return missing;
}

function addMissing(collection, character, field) {
  collection.push({
    id: firstText(character.id, ""),
    name: getName(character),
    field
  });
}

function firstText(...values) {
  for (const value of values) {
    if (hasText(value)) return String(value).trim();
  }
  return "";
}

function hasText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function hasItems(value) {
  return Array.isArray(value) && value.length > 0;
}

function hasObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
}
