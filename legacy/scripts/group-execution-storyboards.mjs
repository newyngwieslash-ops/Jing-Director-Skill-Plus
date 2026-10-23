import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const args = parseArgs(process.argv.slice(2));
if (!args.input) {
  console.error("Usage: node group-execution-storyboards.mjs --input storyboard.xlsx [--output boards.json] [--project ProjectName] [--character-bible character_bible.json]");
  process.exit(1);
}

const inputPath = path.resolve(args.input);
const projectName = args.project || cleanProjectName(path.basename(inputPath, path.extname(inputPath)));
const outputPath = path.resolve(args.output || inputPath.replace(/\.xlsx$/i, "_execution_storyboards.json"));
const promptOutputPath = outputPath.replace(/\.json$/i, "_gpt_image_2_prompts.md");
const characterBiblePath = path.resolve(args["character-bible"] || "character_bible.json");

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = args.sheet ? workbook.worksheets.getItem(args.sheet) : workbook.worksheets.getActiveWorksheet();
const raw = sheet.getRange("A1:Z2000").values;
const table = trimMatrix(raw);
const headers = table[0].map((value) => String(value ?? "").trim());
const rows = table.slice(1).filter((row) => row.some((cell) => cell !== null && cell !== undefined && String(cell).trim() !== ""));

const columns = mapColumns(headers);
validateColumns(columns, headers);

const characterBible = await maybeLoadJson(characterBiblePath);
if (!characterBible) {
  throw new Error(`Missing required character bible: ${characterBiblePath}. 第七步必须加载 character_bible.json。`);
}
const characterBibleDir = path.dirname(characterBiblePath);
const characters = Array.isArray(characterBible?.characters)
  ? characterBible.characters
  : Object.values(characterBible?.characters || {});
const aliasIndex = buildAliasIndex(characters);

const shots = rows.map((row, index) => normalizeShot(row, index, columns, aliasIndex)).filter(Boolean);
validateTripleViewReferences(shots);
const groups = groupShots(shots);
const boards = groups.map((group, index) => buildBoard(group, index + 1, projectName));
validateWardrobeLockContinuity(boards);
validateBottomCharacterReferenceStrip(boards);

const manifest = {
  projectName,
  source: inputPath,
  characterBiblePath: characterBible ? characterBiblePath : "",
  target: "不超过15秒分镜执行故事板",
  rule: {
    targetSeconds: ">0 and <=15",
    acceptedSeconds: ">0 and <=15",
    hardMaxSeconds: 15,
    ordering: "strict consecutive source storyboard indices"
  },
  generatedAt: new Date().toISOString(),
  boardCount: boards.length,
  sourceShotCount: shots.length,
  warnings: collectWarnings(shots, boards),
  boards
};

await fs.writeFile(outputPath, JSON.stringify(manifest, null, 2), "utf8");
await fs.writeFile(promptOutputPath, `\ufeff${renderPromptMarkdown(manifest)}`, "utf8");

console.log(JSON.stringify({
  outputPath,
  promptOutputPath,
  boardCount: boards.length,
  sourceShotCount: shots.length,
  warnings: manifest.warnings
}, null, 2));

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

async function maybeLoadJson(filePath) {
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

function cleanProjectName(name) {
  return name.replace(/分镜表|storyboard/gi, "").replace(/_with_video_prompts/gi, "").trim() || "未命名项目";
}

function trimMatrix(matrix) {
  const rows = matrix.map((row) => row.slice());
  while (rows.length && rows[rows.length - 1].every(isBlank)) rows.pop();
  let lastCol = 0;
  for (const row of rows) {
    row.forEach((cell, index) => {
      if (!isBlank(cell)) lastCol = Math.max(lastCol, index + 1);
    });
  }
  return rows.map((row) => row.slice(0, lastCol));
}

function isBlank(value) {
  return value === null || value === undefined || String(value).trim() === "";
}

function mapColumns(headers) {
  return {
    shotNo: findColumn(headers, ["镜头号", "镜号", "分镜", "编号"]),
    duration: findColumn(headers, ["时长", "持续时间", "秒数"]),
    scene: findColumn(headers, ["场景", "场次", "地点"]),
    shotSize: findColumn(headers, ["景别", "镜别"]),
    camera: findColumn(headers, ["机位/运动", "运镜", "镜头移动", "摄影角度", "备注"]),
    image: findColumn(headers, ["画面内容", "画面", "视觉内容"]),
    dialogue: findColumn(headers, ["台词/人物", "人物", "对白", "台词"]),
    sound: findColumn(headers, ["声音", "台词/声音", "音效/音乐"]),
    purpose: findColumn(headers, ["叙事目的", "目的"]),
    videoPrompt: findColumn(headers, ["视频提示词", "AI视频提示词", "文生视频提示词"])
  };
}

function findColumn(headers, aliases) {
  for (const alias of aliases) {
    const exact = headers.findIndex((header) => header === alias);
    if (exact >= 0) return exact;
  }
  for (const alias of aliases) {
    const partial = headers.findIndex((header) => header.includes(alias));
    if (partial >= 0) return partial;
  }
  return -1;
}

function validateColumns(columns, headers) {
  const required = ["shotNo", "duration", "image"];
  const missing = required.filter((field) => columns[field] < 0);
  if (missing.length) {
    throw new Error(`Missing required columns: ${missing.join(", ")}. Headers found: ${headers.join(" | ")}`);
  }
}

function buildAliasIndex(list) {
  const index = [];
  for (const character of list) {
    const aliases = new Set([
      character.id,
      character.name_cn,
      character.name_en,
      ...(character.aliases || [])
    ].filter(Boolean));
    for (const alias of aliases) {
      index.push({ alias: String(alias), character });
    }
  }
  return index.sort((left, right) => right.alias.length - left.alias.length);
}

function normalizeShot(row, index, columns, aliasIndex) {
  const shot = {
    sourceIndex: index + 1,
    shotNo: valueAt(row, columns.shotNo) || String(index + 1),
    durationSec: parseDurationSeconds(valueAt(row, columns.duration)),
    scene: valueAt(row, columns.scene),
    shotSize: valueAt(row, columns.shotSize),
    camera: valueAt(row, columns.camera),
    image: valueAt(row, columns.image),
    dialogue: valueAt(row, columns.dialogue),
    sound: valueAt(row, columns.sound),
    purpose: valueAt(row, columns.purpose),
    videoPrompt: valueAt(row, columns.videoPrompt)
  };
  shot.characters = detectCharacters(shot, aliasIndex);
  return shot;
}

function valueAt(row, index) {
  if (index < 0) return "";
  const value = row[index];
  return value === null || value === undefined ? "" : String(value).trim();
}

function detectCharacters(shot, aliasIndex) {
  const text = `${shot.scene} ${shot.image} ${shot.dialogue} ${shot.sound} ${shot.videoPrompt}`;
  const result = [];
  const seen = new Set();
  for (const { alias, character } of aliasIndex) {
    if (text.includes(alias) && !seen.has(character.id)) {
      result.push({
        id: character.id,
        name_cn: character.name_cn || character.name || character.id,
        anchor: (character.key_visual_traits || []).slice(0, 3),
        brief: buildCharacterBrief(character),
        tripleViewImagePath: resolveTripleViewImagePath(character),
        source: character
      });
      seen.add(character.id);
    }
  }
  if (text.includes("三人")) {
    for (const leadId of ["gao_xing", "li_xin", "shi_yucheng"]) {
      if (seen.has(leadId)) continue;
      const found = aliasIndex.find((entry) => entry.character.id === leadId);
      if (!found) continue;
      result.push({
        id: found.character.id,
        name_cn: found.character.name_cn || found.character.name || found.character.id,
        anchor: (found.character.key_visual_traits || []).slice(0, 3),
        brief: buildCharacterBrief(found.character),
        tripleViewImagePath: resolveTripleViewImagePath(found.character),
        source: found.character
      });
      seen.add(leadId);
    }
  }
  return result;
}

function resolveTripleViewImagePath(character) {
  const rawPath = character.reference_assets?.triple_view_image_path;
  if (!rawPath || typeof rawPath !== "string") return "";
  return path.isAbsolute(rawPath) ? rawPath : path.resolve(characterBibleDir, rawPath);
}

function validateTripleViewReferences(shots) {
  const missing = new Map();
  const missingFiles = new Map();
  for (const shot of shots) {
    for (const character of shot.characters) {
      if (!character.tripleViewImagePath) {
        missing.set(character.id, character.name_cn || character.id);
      } else if (!existsSync(character.tripleViewImagePath)) {
        missingFiles.set(character.id, `${character.name_cn || character.id}: ${character.tripleViewImagePath}`);
      }
    }
  }

  const messages = [];
  if (missing.size) {
    messages.push(`缺少 reference_assets.triple_view_image_path：${[...missing.entries()].map(([id, name]) => `${name}(${id})`).join(", ")}`);
  }
  if (missingFiles.size) {
    messages.push(`reference_assets.triple_view_image_path 指向的图片不存在：${[...missingFiles.values()].join("; ")}`);
  }
  if (messages.length) {
    throw new Error(`${messages.join(" | ")}。第七步生成 GPT image 2 执行故事板图片前，必须先为涉及角色提供实际三视图图片路径。`);
  }
}

function buildWardrobeLock(character, scene) {
  const source = character.source || character;
  const wardrobe = source.wardrobe && typeof source.wardrobe === "object" ? source.wardrobe : {};
  const sceneVariant = pickSceneWardrobeVariant(wardrobe.scene_variants, scene);
  const domainVariant = !sceneVariant && isDomainScene(scene) && hasText(wardrobe.domain_variant)
    ? String(wardrobe.domain_variant).trim()
    : "";
  const defaultWardrobe = hasText(wardrobe.default) ? String(wardrobe.default).trim() : "";
  const exactOutfitLock = sceneVariant || domainVariant || defaultWardrobe || "MISSING wardrobe.default";
  const sceneWardrobeSource = sceneVariant
    ? `wardrobe.scene_variants[${sceneVariant.key}]`
    : domainVariant
      ? "wardrobe.domain_variant"
      : defaultWardrobe
        ? "wardrobe.default"
        : "missing wardrobe.default";
  const keyVisualTraits = Array.isArray(source.key_visual_traits) ? source.key_visual_traits : [];

  return {
    character_id: character.id,
    character_name: character.name_cn || source.name || source.name_cn || character.id,
    scene,
    reference_image: character.tripleViewImagePath,
    scene_wardrobe_source: sceneWardrobeSource,
    exact_outfit_lock: exactOutfitLock,
    wardrobe_default: defaultWardrobe,
    wardrobe_scene_variant: sceneVariant?.value || "",
    key_visual_traits: keyVisualTraits,
    visual_traits: source.visual_traits || "",
    body_and_hair_lock: buildBodyAndHairLock(source, keyVisualTraits),
    forbidden_drift: [
      "no jacket change",
      "no shirt or inner-layer color change",
      "no silhouette change",
      "no body-shape change",
      "no hairstyle change",
      "no glasses change",
      "no age drift",
      "no profession-level drift",
      "do not change business/casual/workwear level unless wardrobe.scene_variants explicitly says so"
    ],
    warning: defaultWardrobe ? "" : "Missing wardrobe.default; wardrobe lock may be underspecified."
  };
}

function pickSceneWardrobeVariant(sceneVariants, scene) {
  if (!sceneVariants || typeof sceneVariants !== "object" || Array.isArray(sceneVariants)) return null;
  const entries = Object.entries(sceneVariants).filter(([, value]) => hasText(value));
  if (!entries.length) return null;
  const sceneText = normalizeSceneKey(scene);

  for (const [key, value] of entries) {
    if (normalizeSceneKey(key) === sceneText) return { key, value: String(value).trim() };
  }
  for (const [key, value] of entries) {
    const normalizedKey = normalizeSceneKey(key);
    if (sceneText.includes(normalizedKey) || normalizedKey.includes(sceneText)) {
      return { key, value: String(value).trim() };
    }
  }
  return null;
}

function isDomainScene(scene) {
  return /穿越|域|中世纪|百年战争|法兰西|战场|奥尔良|英军|法军/i.test(String(scene || ""));
}

function buildBodyAndHairLock(source, keyVisualTraits) {
  const traits = [
    ...(keyVisualTraits || []),
    source.visual_traits || ""
  ].filter(Boolean).join("；");
  return traits || "Use character_bible visual_traits and triple-view reference image exactly.";
}

function normalizeSceneKey(value) {
  return String(value || "")
    .replace(/\s+/g, "")
    .replace(/[：:，,。.;；]/g, "")
    .toLowerCase();
}

function hasText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function buildCharacterBrief(character) {
  const parts = [];
  if (character.age_impression) parts.push(character.age_impression);
  if (character.occupation || character.role) parts.push(character.occupation || character.role);
  if (character.key_visual_traits?.length) parts.push(character.key_visual_traits.slice(0, 2).join("、"));
  return parts.join("，");
}

function parseDurationSeconds(value) {
  const text = String(value ?? "").trim();
  if (!text) return 3;
  const seconds = text.match(/(\d+(?:\.\d+)?)\s*秒/);
  if (seconds) return Math.round(Number(seconds[1]));
  const range = text.match(/(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/);
  if (range) {
    const start = Number(range[1]) * 60 + Number(range[2]);
    const end = Number(range[3]) * 60 + Number(range[4]);
    return Math.max(1, end - start);
  }
  const numeric = text.match(/\d+(?:\.\d+)?/);
  return numeric ? Math.round(Number(numeric[0])) : 3;
}

function groupShots(shots) {
  const memo = new Map();
  const limit = shots.length;

  function solve(index) {
    if (index >= limit) return { score: 0, groups: [] };
    if (memo.has(index)) return memo.get(index);

    let best = null;
    let total = 0;
    for (let end = index; end < limit && end < index + 8; end += 1) {
      total += shots[end].durationSec;
      if (total > 15) break;
      if (total > 0) {
        const group = shots.slice(index, end + 1);
        const rest = solve(end + 1);
        const scenePenalty = Math.max(0, new Set(group.map((shot) => shot.scene || "")).size - 1) * 0.2;
        const targetPenalty = 1; // No minimum-duration penalty; prefer fewer boards when continuity permits.
        const countPenalty = Math.max(0, group.length - 6) * 0.5;
        const score = scenePenalty + targetPenalty + countPenalty + rest.score;
        const candidate = { score, groups: [group, ...rest.groups] };
        if (!best || candidate.score < best.score) best = candidate;
      }
    }

    if (!best) {
      const fallback = solve(index + 1);
      best = { score: 1000 + fallback.score, groups: [[shots[index]], ...fallback.groups] };
    }

    memo.set(index, best);
    return best;
  }

  return solve(0).groups;
}

function buildBoard(group, boardNo, projectName) {
  const totalDurationSec = group.reduce((sum, shot) => sum + shot.durationSec, 0);
  const first = group[0];
  const last = group[group.length - 1];
  const boardId = `EB-${String(boardNo).padStart(3, "0")}`;
  const characterMap = new Map();
  const characterSceneMap = new Map();
  for (const shot of group) {
    for (const character of shot.characters) {
      if (!characterMap.has(character.id)) characterMap.set(character.id, character);
      if (!characterSceneMap.has(character.id)) characterSceneMap.set(character.id, shot.scene || "未明确场景");
    }
  }
  const characterRefs = [...characterMap.values()].map((character) => {
    const scene = characterSceneMap.get(character.id) || "未明确场景";
    return {
      ...character,
      wardrobeLock: buildWardrobeLock(character, scene)
    };
  });

  const board = {
    boardId,
    boardNo,
    layout_standard: "execution_storyboard_with_bottom_character_reference_strip",
    visual_consistency_status: "pending_image_generation",
    visual_consistency_failure_statuses: [
      "failed_missing_bottom_character_reference_strip",
      "failed_visual_consistency"
    ],
    shotRange: `${first.shotNo}-${last.shotNo}`,
    sourceShotNos: group.map((shot) => shot.shotNo),
    totalDurationSec,
    title: `《${projectName}》分镜 ${first.shotNo}-${last.shotNo} 执行故事板`,
    sceneSummary: summarizeScenes(group),
    layout: chooseLayout(group.length),
    characterRefs,
    required_reference_images: characterRefs.map((character) => ({
      character_id: character.id,
      character_name: character.name_cn,
      triple_view_image_path: character.tripleViewImagePath
    })),
    wardrobe_lock: characterRefs.map((character) => character.wardrobeLock),
    bottom_character_reference_strip: buildBottomCharacterReferenceStrip(characterRefs),
    panels: group.map((shot, index) => ({
      panelNo: index + 1,
      shotNo: shot.shotNo,
      durationSec: shot.durationSec,
      scene: shot.scene,
      shotSize: shot.shotSize,
      image: shot.image,
      camera: shot.camera,
      dialogueSound: [shot.dialogue, shot.sound].filter(Boolean).join(" / "),
      purpose: shot.purpose,
      characterIds: shot.characters.map((character) => character.id),
      tripleViewImagePaths: shot.characters.map((character) => character.tripleViewImagePath).filter(Boolean)
    }))
  };
  board.gptImage2Prompt = buildImagePrompt(board, projectName);
  return board;
}

function buildBottomCharacterReferenceStrip(characterRefs) {
  return {
    required: true,
    title: "角色参考（服装造型一致）",
    visible_character_ids: characterRefs.map((character) => character.id),
    reference_images: characterRefs.map((character) => ({
      character_id: character.id,
      character_name: character.name_cn,
      triple_view_image_path: character.tripleViewImagePath,
      views_required: ["front", "90_degree_side", "back"],
      wardrobe_lock_summary: summarizeWardrobeLock(character.wardrobeLock)
    })),
    failure_status_if_missing_after_generation: "failed_missing_bottom_character_reference_strip",
    failure_status_if_visual_drift_after_generation: "failed_visual_consistency"
  };
}

function summarizeWardrobeLock(lock) {
  if (!lock) return "";
  const traits = Array.isArray(lock.key_visual_traits) ? lock.key_visual_traits.slice(0, 3).join("；") : "";
  return [lock.exact_outfit_lock, traits].filter(Boolean).join("；");
}

function validateWardrobeLockContinuity(boards) {
  const previousByCharacterScene = new Map();
  const failures = [];
  for (const board of boards) {
    for (const lock of board.wardrobe_lock || []) {
      const key = `${lock.character_id}::${normalizeSceneKey(lock.scene)}`;
      const previous = previousByCharacterScene.get(key);
      if (previous && previous.exact_outfit_lock !== lock.exact_outfit_lock) {
        failures.push(`${lock.character_name}(${lock.character_id}) scene=${lock.scene}: ${previous.boardId}="${previous.exact_outfit_lock}" vs ${board.boardId}="${lock.exact_outfit_lock}"`);
      }
      previousByCharacterScene.set(key, {
        boardId: board.boardId,
        exact_outfit_lock: lock.exact_outfit_lock
      });
    }
  }
  if (failures.length) {
    throw new Error(`同一角色在同一场景连续执行板中 wardrobe_lock 不一致：${failures.join("; ")}`);
  }
}

function validateBottomCharacterReferenceStrip(boards) {
  const failures = [];
  for (const board of boards) {
    if (board.characterRefs.length && board.layout_standard !== "execution_storyboard_with_bottom_character_reference_strip") {
      failures.push(`${board.boardId}: missing layout_standard`);
    }
    if (board.characterRefs.length && !board.bottom_character_reference_strip?.required) {
      failures.push(`${board.boardId}: missing required bottom_character_reference_strip`);
    }
    for (const character of board.characterRefs) {
      const image = board.bottom_character_reference_strip?.reference_images?.find((item) => item.character_id === character.id);
      if (!image) {
        failures.push(`${board.boardId}: bottom_character_reference_strip missing ${character.id}`);
        continue;
      }
      if (image.triple_view_image_path !== character.tripleViewImagePath) {
        failures.push(`${board.boardId}: bottom strip image path mismatch for ${character.id}`);
      }
      if (!image.wardrobe_lock_summary) {
        failures.push(`${board.boardId}: bottom strip wardrobe_lock_summary missing for ${character.id}`);
      }
      if (!board.gptImage2Prompt.includes(character.tripleViewImagePath)) {
        failures.push(`${board.boardId}: prompt missing triple_view_image_path for ${character.id}`);
      }
      if (!board.gptImage2Prompt.includes(image.wardrobe_lock_summary)) {
        failures.push(`${board.boardId}: prompt missing wardrobe_lock_summary for ${character.id}`);
      }
    }

    const requiredPromptPhrases = [
      "Bottom character reference strip is mandatory",
      "角色参考（服装造型一致）",
      "show front view, 90-degree side view, back view",
      "failed_missing_bottom_character_reference_strip",
      "failed_visual_consistency"
    ];
    for (const phrase of requiredPromptPhrases) {
      if (board.characterRefs.length && !board.gptImage2Prompt.includes(phrase)) {
        failures.push(`${board.boardId}: prompt missing required phrase: ${phrase}`);
      }
    }
  }
  if (failures.length) {
    throw new Error(`执行故事板底部角色参考区约束失败：${failures.join("; ")}`);
  }
}

function summarizeScenes(group) {
  const scenes = [...new Set(group.map((shot) => shot.scene).filter(Boolean))];
  return scenes.length ? scenes.join(" / ") : "未明确场景";
}

function chooseLayout(count) {
  if (count <= 2) return "2 panels, one row";
  if (count <= 4) return "2x2 panels";
  if (count <= 6) return "3x2 panels";
  return "4x2 panels";
}

function buildImagePrompt(board, projectName) {
  const panelLines = board.panels.map((panel) => {
    return [
      `Panel ${String(panel.panelNo).padStart(2, "0")} / 分镜 ${panel.shotNo} / ${panel.durationSec}秒`,
      `景别：${panel.shotSize || "未明确"}。`,
      `画面：${panel.image || "未明确画面"}。`,
      `运镜：${panel.camera || "按原分镜机位"}。`,
      `台词/声音：${panel.dialogueSound || "无明确对白或声音"}。`,
      `角色ID：${panel.characterIds.join(", ") || "无主要人物"}。`
    ].join(" ");
  }).join("\n");

  const characterLines = board.characterRefs.length
    ? board.characterRefs.map((character) => `- ${character.name_cn} (${character.id}): ${character.brief || "按角色圣经执行"}；视觉锚点：${character.anchor.join("、") || "按角色圣经执行"}；三视图参考图：${character.tripleViewImagePath}`).join("\n")
    : "- 无主要人物";

  const referenceImageLines = board.characterRefs.length
    ? board.characterRefs.map((character) => `- ${character.name_cn} (${character.id}) => ${character.tripleViewImagePath}`).join("\n")
    : "- 无主要人物参考图";

  const wardrobeLockLines = board.wardrobe_lock?.length
    ? board.wardrobe_lock.map((lock) => [
      `- ${lock.character_id} / ${lock.character_name}:`,
      `  reference image: ${lock.reference_image}`,
      `  scene wardrobe source: ${lock.scene_wardrobe_source}`,
      `  exact outfit lock: ${lock.exact_outfit_lock}`,
      `  body and hair lock: ${lock.body_and_hair_lock}`,
      `  forbidden drift: ${lock.forbidden_drift.join("; ")}`
    ].join("\n")).join("\n")
    : "- 无主要人物服装锁";

  const bottomReferenceLines = board.bottom_character_reference_strip?.reference_images?.length
    ? board.bottom_character_reference_strip.reference_images.map((image) => [
      `- ${image.character_name} / ${image.character_id}`,
      `  source image: ${image.triple_view_image_path}`,
      "  show: front view, 90-degree side view, back view",
      `  wardrobe_lock summary: ${image.wardrobe_lock_summary}`
    ].join("\n")).join("\n")
    : "- 无主要人物底部参考区";

  return [
    "Create a polished cinematic execution storyboard sheet for GPT image 2.",
    `Project: ${projectName}.`,
    `Board: ${board.title}, total ${board.totalDurationSec} seconds, for Seedance 2.0 video generation, using the actual board duration (maximum 15 seconds).`,
    `Scene summary: ${board.sceneSummary}.`,
    `layout_standard: ${board.layout_standard}.`,
    `Layout: ${board.layout}; wide horizontal sheet; aged ivory paper; thin table grid; each panel has a cinematic image frame above and a compact Chinese information table below.`,
    "Storyboard image layout:",
    "- Top header: project title, board id, shot range, total duration.",
    "- Middle storyboard panels: 2-8 panels, each panel contains image frame + compact information table.",
    "- Bottom character reference strip: mandatory when visible recurring characters exist.",
    "- The bottom strip must show the actual triple-view reference thumbnails for every visible recurring character.",
    "- Each character reference block must be labelled with Chinese name and stable character_id.",
    "- The character reference strip is part of the storyboard image, not a separate file.",
    "Bottom character reference strip is mandatory.",
    "The generated image must contain the visible bottom title: 角色参考（服装造型一致）.",
    "Visual priority: the panel images must be clear, sequential, and consistent; table text can be compact but should look like a real professional storyboard execution sheet.",
    "Style: inherit the project's character bible, art style bible, lighting, color palette, costume continuity, camera language, and scene atmosphere.",
    "Character consistency requirement: load character_bible.json before generation; match every visible recurring character by stable id; preserve face, age, body build, hairstyle, costume silhouette, color palette, props, dialogue traits, and performance traits.",
    "Reference image requirement: before calling GPT image 2, attach the exact local image files listed below from each character's reference_assets.triple_view_image_path. These image files are mandatory visual references, not optional text hints. Do not substitute other images.",
    "Required reference_assets.triple_view_image_path files to attach:",
    referenceImageLines,
    "Required bottom character reference strip:",
    bottomReferenceLines,
    "show front view, 90-degree side view, back view reference thumbnails inside the generated storyboard image.",
    "Do not only mention triple-view references in the prompt; the generated storyboard image itself must include the bottom character reference strip.",
    "Wardrobe lock:",
    wardrobeLockLines,
    "The generated storyboard must copy each character's outfit from the attached triple-view reference image unless a scene-specific wardrobe variant is explicitly defined in character_bible.json.",
    "If the generated image lacks the bottom character reference strip, mark visual_consistency_status as failed_missing_bottom_character_reference_strip and do not mark it confirmed.",
    "If any main character's jacket, inner layer, color palette, outfit silhouette, body build, hairstyle, glasses, or age drifts from Wardrobe lock, mark visual_consistency_status as failed_visual_consistency and do not mark it confirmed.",
    "Characters in this board:",
    characterLines,
    panelLines,
    `Header text: ${board.title}`,
    "Footer note: 本执行板用于 Seedance 2.0 按本板实际时长生成不超过15秒的连续视频；保持镜头顺序、角色一致性、场景连续性和动作节奏。",
    "Negative requirements: no watermark, no platform logo, no bilibili mark, no random signature, no poster composition, no unrelated characters, no invented plot."
  ].join("\n");
}

function collectWarnings(shots, boards) {
  const warnings = [];
  const longShots = shots.filter((shot) => shot.durationSec > 15);
  if (longShots.length) {
    warnings.push(`存在超过15秒的单镜头，需要先拆分：${longShots.map((shot) => shot.shotNo).join(", ")}`);
  }
  const invalidBoards = boards.filter((board) => !Number.isFinite(board.totalDurationSec) || board.totalDurationSec <= 0 || board.totalDurationSec > 15);
  if (invalidBoards.length) {
    warnings.push(`存在时长无效或超过15秒的执行板：${invalidBoards.map((board) => `${board.boardId}=${board.totalDurationSec}秒`).join(", ")}`);
  }
  const missingWardrobeDefaults = new Map();
  for (const board of boards) {
    for (const lock of board.wardrobe_lock || []) {
      if (lock.warning) missingWardrobeDefaults.set(lock.character_id, `${lock.character_name}(${lock.character_id})`);
    }
  }
  if (missingWardrobeDefaults.size) {
    warnings.push(`存在角色缺少 wardrobe.default：${[...missingWardrobeDefaults.values()].join(", ")}`);
  }
  return warnings;
}

function renderPromptMarkdown(manifest) {
  const lines = [
    `# ${manifest.projectName} 不超过15秒分镜执行故事板 GPT image 2 提示词`,
    "",
    `源文件：${manifest.source}`,
    `角色档案：${manifest.characterBiblePath || "未加载"}`,
    `执行板数量：${manifest.boardCount}`,
    ""
  ];
  for (const board of manifest.boards) {
    lines.push(`## ${board.boardId} | 分镜 ${board.shotRange} | ${board.totalDurationSec}秒`);
    lines.push("");
    lines.push("```text");
    lines.push(board.gptImage2Prompt);
    lines.push("```");
    lines.push("");
  }
  return lines.join("\n");
}
