import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_TARGET = "Seedance 2 专用视频生产故事板";
const SEEDANCE_PROMPT_CHAR_LIMIT = 2000;

export function generateSeedance2Storyboards({
  projectName = "未命名项目",
  source = "",
  headers,
  rows,
  characterBible,
  verifyReferenceFiles = true,
  characterBiblePath = "",
  storyboardImageRefs = {},
  artStyleBible = null
}) {
  if (!Array.isArray(headers) || !Array.isArray(rows)) {
    throw new Error("headers and rows are required to generate Seedance 2 storyboards.");
  }
  if (!characterBible) {
    throw new Error("characterBible is required for Seedance 2 storyboard generation.");
  }

  const columns = mapColumns(headers.map((header) => String(header ?? "").trim()));
  validateColumns(columns, headers);

  const characters = normalizeCharacters(characterBible);
  const aliasIndex = buildAliasIndex(characters);
  const baseDir = characterBiblePath ? path.dirname(path.resolve(characterBiblePath)) : process.cwd();
  const shots = rows
    .map((row, index) => normalizeShot(row, index, columns, aliasIndex, baseDir, verifyReferenceFiles))
    .filter(Boolean);

  const longShots = shots.filter((shot) => shot.durationSec > 15);
  if (longShots.length) {
    throw new Error(`Source shot exceeds 15 seconds and must be split before Seedance 2 generation: ${longShots.map((shot) => `${shot.shotNo}=${shot.durationSec}s`).join(", ")}`);
  }

  const groups = groupShotsNearFifteen(shots);
  const boards = groups.map((group, index) => buildSeedance2Board({
    group,
    boardNo: index + 1,
    projectName,
    storyboardImageRefs,
    artStyleBible
  }));

  const manifest = {
    projectName,
    source,
    characterBiblePath,
    target: DEFAULT_TARGET,
    rule: {
      targetSeconds: ">0 and <=15; no minimum duration",
      hardMaxSeconds: 15,
      ordering: "strict consecutive source storyboard indices",
      references: "Seedance 2 @ aliases for characters, images, scenes, and storyboard sheets"
    },
    generatedAt: new Date().toISOString(),
    boardCount: boards.length,
    sourceShotCount: shots.length,
    sourceShotNos: shots.map((shot) => shot.shotNo),
    warnings: collectManifestWarnings(boards),
    boards
  };

  return manifest;
}

export function validateSeedance2Manifest(manifest) {
  if (!manifest || !Array.isArray(manifest.boards)) {
    throw new Error("Invalid Seedance 2 manifest: missing boards.");
  }

  const allShotNos = [];
  for (const board of manifest.boards) {
    if (board.totalDurationSec > 15) {
      throw new Error(`${board.boardId} exceeds Seedance 2 hard max: ${board.totalDurationSec}s.`);
    }
    if (!Array.isArray(board.timeSegments) || !board.timeSegments.length) {
      throw new Error(`${board.boardId} is missing timeSegments.`);
    }

    let expectedStart = 0;
    const segmentShotNos = [];
    for (const segment of board.timeSegments) {
      if (segment.startSec !== expectedStart) {
        throw new Error(`${board.boardId} has non-contiguous time segment at ${segment.label}.`);
      }
      if (segment.endSec <= segment.startSec || segment.endSec > board.totalDurationSec) {
        throw new Error(`${board.boardId} has invalid time segment: ${segment.label}.`);
      }
      expectedStart = segment.endSec;
      segmentShotNos.push(...segment.sourceShotNos);
    }
    if (expectedStart !== board.totalDurationSec) {
      throw new Error(`${board.boardId} final segment ends at ${expectedStart}s but board duration is ${board.totalDurationSec}s.`);
    }
    assertSameOrderedValues(segmentShotNos, board.sourceShotNos, `${board.boardId} time segment coverage`);

    const prompt = board.seedance2MultiRefVideoPrompt || "";
    for (const character of board.characters || []) {
      assertPromptContains(prompt, character.alias, `${board.boardId} missing character alias ${character.alias}`);
    }
    for (const imageRef of board.imageRefs || []) {
      assertPromptContains(prompt, imageRef.alias, `${board.boardId} missing image alias ${imageRef.alias}`);
    }
    for (const sceneRef of board.sceneRefs || []) {
      assertPromptContains(prompt, sceneRef.alias, `${board.boardId} missing scene alias ${sceneRef.alias}`);
    }
    if (board.storyboardImageRef?.alias) {
      assertPromptContains(prompt, board.storyboardImageRef.alias, `${board.boardId} missing storyboard alias ${board.storyboardImageRef.alias}`);
    }

    allShotNos.push(...board.sourceShotNos);
  }

  assertSameOrderedValues(allShotNos, manifest.sourceShotNos || allShotNos, "manifest source shot coverage");
  ensureStrictAscendingShotOrder(allShotNos);
}

export function renderSeedance2PromptMarkdown(manifest) {
  const lines = [
    `# ${manifest.projectName} Seedance 2 视频生产故事板`,
    "",
    `源文件：${manifest.source || "未记录"}`,
    `目标：${manifest.target}`,
    `执行板数量：${manifest.boardCount}`,
    ""
  ];

  for (const board of manifest.boards) {
    lines.push(`## ${board.boardId} | 分镜 ${board.shotRange} | ${board.totalDurationSec}秒`);
    lines.push("");
    lines.push("### Reference Aliases");
    lines.push("");
    lines.push("| Alias | Type | Source | Status |");
    lines.push("|---|---|---|---|");
    for (const ref of flattenReferenceAliases(board)) {
      lines.push(`| ${ref.alias} | ${ref.type} | ${ref.source || ref.path || ""} | ${ref.status || ""} |`);
    }
    lines.push("");
    lines.push("### GPT image 2 Storyboard Prompt");
    lines.push("");
    lines.push("```text");
    lines.push(board.gptImage2Prompt);
    lines.push("```");
    lines.push("");
    lines.push("### Seedance 2 Multi-Reference Video Prompt");
    lines.push("");
    lines.push("```text");
    lines.push(board.seedance2MultiRefVideoPrompt);
    lines.push("```");
    lines.push("");
  }

  return lines.join("\n");
}

export async function loadStoryboardRowsFromExcel(inputPath, sheetName = "") {
  const { FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool");
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
  const sheet = sheetName ? workbook.worksheets.getItem(sheetName) : workbook.worksheets.getActiveWorksheet();
  const raw = sheet.getRange("A1:Z2000").values;
  const table = trimMatrix(raw);
  return {
    headers: table[0].map((value) => String(value ?? "").trim()),
    rows: table.slice(1).filter((row) => row.some((cell) => !isBlank(cell)))
  };
}

function normalizeCharacters(characterBible) {
  if (Array.isArray(characterBible.characters)) return characterBible.characters;
  return Object.values(characterBible.characters || {});
}

function mapColumns(headers) {
  return {
    shotNo: findColumn(headers, ["镜头号", "镜号", "分镜", "编号"]),
    duration: findColumn(headers, ["时长", "持续时间", "秒数"]),
    cameraAngle: findColumn(headers, ["摄影角度", "机位", "角度"]),
    shotSize: findColumn(headers, ["景别", "镜别"]),
    image: findColumn(headers, ["画面内容", "画面", "视觉内容"]),
    scene: findColumn(headers, ["场景", "场次", "地点"]),
    sound: findColumn(headers, ["声音", "台词/声音", "音效/音乐"]),
    camera: findColumn(headers, ["机位/运动", "运镜", "镜头移动", "备注"]),
    purpose: findColumn(headers, ["叙事目的", "目的"]),
    videoPrompt: findColumn(headers, ["视频提示词", "AI视频提示词", "文生视频提示词"]),
    dialogue: findColumn(headers, ["台词/人物", "人物", "对白", "台词"])
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
    throw new Error(`Missing required storyboard columns: ${missing.join(", ")}. Headers: ${headers.join(" | ")}`);
  }
}

function buildAliasIndex(characters) {
  const index = [];
  for (const character of characters) {
    const aliases = new Set([
      character.id,
      character.name,
      character.name_cn,
      character.name_en,
      ...(character.aliases || [])
    ].filter(Boolean));
    for (const alias of aliases) {
      index.push({ alias: String(alias), bareAlias: String(alias).replace(/^@/, ""), character });
    }
  }
  return index.sort((left, right) => right.alias.length - left.alias.length);
}

function normalizeShot(row, index, columns, aliasIndex, baseDir, verifyReferenceFiles) {
  const shot = {
    sourceIndex: index + 1,
    shotNo: valueAt(row, columns.shotNo) || String(index + 1),
    durationSec: parseDurationSeconds(valueAt(row, columns.duration)),
    cameraAngle: valueAt(row, columns.cameraAngle),
    shotSize: valueAt(row, columns.shotSize),
    image: valueAt(row, columns.image),
    scene: valueAt(row, columns.scene),
    sound: valueAt(row, columns.sound),
    camera: valueAt(row, columns.camera),
    purpose: valueAt(row, columns.purpose),
    videoPrompt: valueAt(row, columns.videoPrompt),
    dialogue: valueAt(row, columns.dialogue)
  };
  shot.characters = detectCharacters(shot, aliasIndex, baseDir, verifyReferenceFiles);
  return shot;
}

function valueAt(row, index) {
  if (index < 0) return "";
  const value = row[index];
  return value === null || value === undefined ? "" : String(value).trim();
}

function parseDurationSeconds(value) {
  const text = String(value ?? "").trim();
  if (!text) return 3;
  const seconds = text.match(/(\d+(?:\.\d+)?)\s*秒/);
  if (seconds) return roundSeconds(Number(seconds[1]));
  const range = text.match(/(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})/);
  if (range) {
    const start = Number(range[1]) * 60 + Number(range[2]);
    const end = Number(range[3]) * 60 + Number(range[4]);
    return Math.max(1, roundSeconds(end - start));
  }
  const numeric = text.match(/\d+(?:\.\d+)?/);
  return numeric ? roundSeconds(Number(numeric[0])) : 3;
}

function roundSeconds(value) {
  return Number.isInteger(value) ? value : Math.round(value * 10) / 10;
}

function detectCharacters(shot, aliasIndex, baseDir, verifyReferenceFiles) {
  const text = `${shot.scene} ${shot.image} ${shot.dialogue} ${shot.sound} ${shot.videoPrompt}`;
  const result = [];
  const seen = new Set();
  for (const entry of aliasIndex) {
    if ((text.includes(entry.alias) || text.includes(entry.bareAlias)) && !seen.has(entry.character.id)) {
      result.push(normalizeCharacterRef(entry.character, baseDir, verifyReferenceFiles));
      seen.add(entry.character.id);
    }
  }
  return result;
}

function normalizeCharacterRef(character, baseDir, verifyReferenceFiles) {
  const rawPath = character.reference_assets?.triple_view_image_path || "";
  const resolvedPath = rawPath
    ? path.isAbsolute(rawPath) ? rawPath : path.resolve(baseDir, rawPath)
    : "";
  const hasFile = resolvedPath && (!verifyReferenceFiles || existsSync(resolvedPath));
  const missingReason = !rawPath
    ? "missing triple-view reference path"
    : hasFile
      ? ""
      : "missing triple-view reference file";

  return {
    id: String(character.id),
    name: character.name_cn || character.name || character.id,
    alias: `@${sanitizeAlias(character.id)}`,
    displayAlias: character.name_cn ? `@${character.name_cn}` : `@${sanitizeAlias(character.id)}`,
    imageAlias: `@image_${sanitizeAlias(character.id)}_triple_view`,
    visualTraits: character.visual_traits || "",
    keyVisualTraits: Array.isArray(character.key_visual_traits) ? character.key_visual_traits : [],
    wardrobeLock: buildWardrobeLock(character),
    tripleViewImagePath: resolvedPath,
    referenceStatus: hasFile ? "ready" : "missing",
    missingReason,
    source: character
  };
}

function buildWardrobeLock(character) {
  const wardrobe = character.wardrobe && typeof character.wardrobe === "object" ? character.wardrobe : {};
  const defaultWardrobe = typeof wardrobe.default === "string" && wardrobe.default.trim()
    ? wardrobe.default.trim()
    : "MISSING wardrobe.default";
  const anchors = Array.isArray(character.key_visual_traits) ? character.key_visual_traits : [];
  return {
    exact_outfit_lock: defaultWardrobe,
    visual_anchor_lock: anchors,
    identity_lock: character.visual_traits || "",
    forbidden_drift: [
      "no face drift",
      "no age drift",
      "no body-shape drift",
      "no hairstyle change",
      "no costume silhouette change",
      "no accessory drift",
      "no unregistered character substitution"
    ]
  };
}

function groupShotsNearFifteen(shots) {
  const memo = new Map();

  function solve(index) {
    if (index >= shots.length) return { score: 0, groups: [] };
    if (memo.has(index)) return memo.get(index);

    let best = null;
    let total = 0;
    for (let end = index; end < shots.length && end < index + 8; end += 1) {
      total = roundSeconds(total + shots[end].durationSec);
      if (total > 15) break;
      const group = shots.slice(index, end + 1);
      const rest = solve(end + 1);
      const candidateScore = scoreGroup(group, total) + rest.score;
      const candidate = { score: candidateScore, groups: [group, ...rest.groups] };
      if (!best || candidate.score < best.score) best = candidate;
    }

    if (!best) {
      throw new Error(`Unable to group shot ${shots[index]?.shotNo || index + 1} within Seedance 2 duration limits.`);
    }
    memo.set(index, best);
    return best;
  }

  return solve(0).groups;
}

function scoreGroup(group, total) {
  const durationBandPenalty = 1; // No lower-duration preference bands.
  const scenePenalty = Math.max(0, new Set(group.map((shot) => shot.scene || "")).size - 1) * 2;
  const panelPenalty = Math.max(0, group.length - 6) * 3;
  const singleShortPenalty = 0; // Single-shot short boards are valid.
  return durationBandPenalty + scenePenalty + panelPenalty + singleShortPenalty;
}

function buildSeedance2Board({ group, boardNo, projectName, storyboardImageRefs, artStyleBible }) {
  const boardId = `EB-${String(boardNo).padStart(3, "0")}`;
  const totalDurationSec = roundSeconds(group.reduce((sum, shot) => sum + shot.durationSec, 0));
  const first = group[0];
  const last = group[group.length - 1];
  const characters = collectBoardCharacters(group);
  const sceneRefs = buildSceneRefs(group);
  const imageRefs = buildImageRefs(characters);
  const storyboardImageRef = buildStoryboardImageRef(boardId, storyboardImageRefs?.[boardId]);
  const timeSegments = buildTimeSegments(group);
  const validationWarnings = collectBoardWarnings(characters);
  const referenceStatus = validationWarnings.some((warning) => warning.toLowerCase().includes("missing triple-view reference"))
    ? "blocked_missing_character_reference"
    : "ready";
  const shotDescription = group.map((shot) => `分镜${shot.shotNo}: ${shot.image}`).join("\n");
  const dialogueSound = group.map((shot) => `分镜${shot.shotNo}: ${[shot.dialogue, shot.sound].filter(Boolean).join(" / ") || "无对白或声音"}`).join("\n");

  const board = {
    boardId,
    shotRange: `${first.shotNo}-${last.shotNo}`,
    sourceShotNos: group.map((shot) => shot.shotNo),
    totalDurationSec,
    characters: characters.map((character) => ({
      id: character.id,
      name: character.name,
      alias: character.alias,
      displayAlias: character.displayAlias,
      imageAlias: character.imageAlias,
      visualTraits: character.visualTraits,
      keyVisualTraits: character.keyVisualTraits,
      wardrobeLock: character.wardrobeLock,
      referenceStatus: character.referenceStatus,
      missingReason: character.missingReason
    })),
    sceneRefs,
    imageRefs,
    storyboardImageRef,
    referenceAliases: {},
    referenceStatus,
    validationWarnings,
    sceneSummary: summarizeScenes(group),
    actionChain: summarizeActionChain(group),
    shotDescription,
    dialogueSound,
    timeSegments,
    gptImage2Prompt: "",
    seedance2MultiRefVideoPrompt: ""
  };

  board.referenceAliases = buildReferenceAliasMap(board);
  board.gptImage2Prompt = buildGptImage2Prompt(board, projectName, group);
  board.seedance2MultiRefVideoPrompt = buildSeedance2Prompt(board, projectName, group, artStyleBible);
  return board;
}

function collectBoardCharacters(group) {
  const map = new Map();
  for (const shot of group) {
    for (const character of shot.characters) {
      if (!map.has(character.id)) map.set(character.id, character);
    }
  }
  return [...map.values()];
}

function buildSceneRefs(group) {
  const scenes = [...new Set(group.map((shot) => shot.scene).filter(Boolean))];
  return scenes.map((scene, index) => ({
    alias: `@scene_${slugify(scene) || `scene_${index + 1}`}`,
    type: "text_scene_reference",
    source: scene,
    path: "",
    attachable: false,
    status: "text_only"
  }));
}

function buildImageRefs(characters) {
  return characters.map((character) => ({
    alias: character.imageAlias,
    type: "character_triple_view",
    character_id: character.id,
    character_name: character.name,
    path: character.tripleViewImagePath,
    attachable: character.referenceStatus === "ready",
    status: character.referenceStatus,
    missingReason: character.missingReason
  }));
}

function buildStoryboardImageRef(boardId, pathOrRef) {
  return {
    alias: `@storyboard_${boardId}`,
    type: "gpt_image_2_execution_storyboard",
    path: pathOrRef || "",
    attachable: Boolean(pathOrRef),
    status: pathOrRef ? "ready" : "pending_image_generation"
  };
}

function buildTimeSegments(group) {
  let cursor = 0;
  return group.map((shot) => {
    const startSec = cursor;
    const endSec = roundSeconds(cursor + shot.durationSec);
    cursor = endSec;
    const label = `${formatSecond(startSec)}-${formatSecond(endSec)} seconds`;
    return {
      label,
      startSec,
      endSec,
      sourceShotNos: [shot.shotNo],
      scene: shot.scene,
      action: shot.image,
      camera: [shot.cameraAngle, shot.shotSize, shot.camera].filter(Boolean).join(" / "),
      performance: buildPerformanceDetail(shot),
      dialogue: shot.dialogue || extractDialogue(shot.sound),
      sound: shot.sound || "no explicit sound, preserve natural ambient room tone"
    };
  });
}

function buildPerformanceDetail(shot) {
  const names = shot.characters.map((character) => character.alias).join(", ") || "no primary registered character";
  return `${names}; visible physical movement only; preserve subtle breathing, eye movement, hand tension, and action continuity from the source shot.`;
}

function extractDialogue(sound) {
  if (!sound) return "no dialogue";
  return /["“”：:]/.test(sound) ? sound : "no dialogue";
}

function collectBoardWarnings(characters) {
  const warnings = [];
  for (const character of characters) {
    if (character.referenceStatus !== "ready") {
      warnings.push(`${character.alias} missing triple-view reference: ${character.missingReason}`);
    }
    if (character.wardrobeLock.exact_outfit_lock.startsWith("MISSING")) {
      warnings.push(`${character.alias} missing wardrobe.default`);
    }
  }
  return warnings;
}

function buildReferenceAliasMap(board) {
  const map = {};
  for (const character of board.characters) {
    map[character.alias] = {
      type: "character",
      id: character.id,
      name: character.name,
      status: character.referenceStatus
    };
  }
  for (const ref of [...board.imageRefs, ...board.sceneRefs, board.storyboardImageRef]) {
    map[ref.alias] = {
      type: ref.type,
      path: ref.path || "",
      source: ref.source || "",
      attachable: ref.attachable,
      status: ref.status
    };
  }
  return map;
}

function buildGptImage2Prompt(board, projectName, group) {
  const beatRows = buildReferenceStyleBeatRows(board, group);

  const refs = flattenReferenceAliases(board)
    .map((ref) => `- ${ref.alias}: ${ref.type}; ${ref.path || ref.source || ref.status}`)
    .join("\n");
  const wardrobeLocks = board.characters.length
    ? board.characters.map((character) => {
      const lock = character.wardrobeLock || {};
      return `- ${character.alias} ${character.displayAlias}: ${clipChars(lock.exact_outfit_lock || "use character bible wardrobe", 96)}; anchors: ${clipChars((lock.visual_anchor_lock || []).join(", ") || character.visualTraits || "use character bible visual anchors", 96)}`;
    }).join("\n")
    : "- no registered recurring characters in this board";
  const durationText = `${formatSecond(board.totalDurationSec)} SECONDS`;

  return [
    "Create a polished cinematic execution storyboard sheet for GPT image 2.",
    `Project: ${projectName}.`,
    `Board: ${board.boardId}, shot range ${board.shotRange}, total ${formatSecond(board.totalDurationSec)} seconds, for Seedance 2 video production.`,
    "Match the uploaded reference style as closely as possible: clean black-line table on white/off-white paper, wide 16:9 sheet, compact production typography, cinematic frame strips, dialogue boxes, and concise notes.",
    `Top header text must read: SCENE: ${board.sceneSummary || "PRIMARY SCENE"} | DURATION: ${durationText} | ASPECT RATIO: 16:9.`,
    "Main table columns must be exactly: TIME | SHOT / ACTION | DIALOGUE | NOTES / VISUALS.",
    "The image must be a production storyboard table, not a movie poster, comic page, moodboard, or single concept frame.",
    "Column rules:",
    "- TIME: left narrow column, bold time range plus duration in seconds.",
    "- SHOT / ACTION: wide cinematic image frame for the beat, letterboxed 16:9 feel, visible physical action only.",
    "- DIALOGUE: speaker label such as HIM/HER/character alias plus a simple speech-bubble box; write no-dialogue if silent.",
    "- NOTES / VISUALS: performance notes, lighting, continuity, camera movement, visual tension, and sourceShotNos.",
    `Bottom line text must read: TOTAL DURATION: ${durationText}.`,
    "Default 15-second row cadence: use eight table rows, 0:00-0:02, 0:02-0:04, 0:04-0:06, 0:06-0:08, 0:08-0:10, 0:10-0:12, 0:12-0:14, 0:14-0:15; map each row to the nearest source shot without reordering.",
    "Reference aliases:",
    refs || "- no references",
    "Character and wardrobe consistency constraints:",
    wardrobeLocks,
    "Reference images remain mandatory for identity consistency: use the declared character image aliases and exact paths, but do not replace the four-column storyboard table with a bottom reference-strip layout.",
    "Storyboard table row plan:",
    beatRows,
    "Negative requirements: no watermark, no platform logo, no random signature, no unrelated characters, no invented plot, no poster composition, no oversized bottom character strip."
  ].join("\n");
}

function buildReferenceStyleBeatRows(board, group) {
  const beats = board.totalDurationSec === 15
    ? [[0, 2], [2, 4], [4, 6], [6, 8], [8, 10], [10, 12], [12, 14], [14, 15]]
    : board.timeSegments.map((segment) => [segment.startSec, segment.endSec]);

  return beats.map(([startSec, endSec], index) => {
    const shots = shotsForBeat(group, startSec, endSec);
    const primaryShot = shots[0] || group[Math.min(index, group.length - 1)];
    const shotNos = shots.map((shot) => shot.shotNo);
    const characters = [...new Map(shots.flatMap((shot) => shot.characters).map((character) => [character.id, character])).values()];
    const dialogue = shots
      .map((shot) => shot.dialogue || extractDialogue(shot.sound))
      .filter(Boolean)
      .join(" / ") || "no dialogue";
    const action = shots
      .map((shot) => `Shot ${shot.shotNo}: ${shot.image || "visible action follows source storyboard"}`)
      .join(" ");
    const notes = [
      `sourceShotNos: ${shotNos.join(",") || primaryShot?.shotNo || ""}`,
      `scene: ${primaryShot ? sceneAliasForShot(board, primaryShot) : board.sceneRefs[0]?.alias || "@scene_unspecified"}`,
      `characters: ${characters.map((character) => character.alias).join(", ") || "none"}`,
      `camera: ${primaryShot ? [primaryShot.cameraAngle, primaryShot.shotSize, primaryShot.camera].filter(Boolean).join(" / ") : "follow source camera language"}`,
      "keep lighting, facial identity, costume silhouette, and emotional continuity strict"
    ].filter(Boolean).join("; ");

    return [
      `${formatStoryboardClock(startSec)}-${formatStoryboardClock(endSec)} (${formatSecond(endSec - startSec)} SEC)`,
      `SHOT / ACTION: ${action}`,
      `DIALOGUE: ${dialogue}`,
      `NOTES / VISUALS: ${notes}`
    ].join(" | ");
  }).join("\n");
}

function shotsForBeat(group, startSec, endSec) {
  const result = [];
  let cursor = 0;
  for (const shot of group) {
    const shotStart = cursor;
    const shotEnd = roundSeconds(cursor + shot.durationSec);
    cursor = shotEnd;
    if (shotStart < endSec && shotEnd > startSec) result.push(shot);
  }
  return result;
}

function formatStoryboardClock(value) {
  const total = Math.round(Number(value) || 0);
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function buildSeedance2Prompt(board, projectName, group, artStyleBible) {
  const characterLine = board.characters.length
    ? board.characters.map((character) => `${character.alias} (${character.displayAlias}, ${character.name}) using ${character.imageAlias}`).join(", ")
    : "no registered recurring characters";
  const imageLine = board.imageRefs.length
    ? board.imageRefs.map((ref) => ref.alias).join(", ")
    : "no character image refs";
  const sceneLine = board.sceneRefs.length
    ? board.sceneRefs.map((ref) => `${ref.alias}=${ref.source}`).join(", ")
    : "no explicit scene refs";
  const style = clipChars(artStyleBible?.series_identity?.core_visual_language || "cinematic, ultra-realistic, coherent lighting, production storyboard faithful", 96);
  const referenceStatus = board.referenceStatus === "ready"
    ? "Refs ready."
    : `Refs unverified: ${board.validationWarnings.map((warning) => warning.split(" missing ")[0]).join(", ")}.`;

  const segments = board.timeSegments.map((segment) => [
    `${segment.label}: sourceShotNos: ${segment.sourceShotNos.join(",")}.`,
    `Scene: ${segment.scene ? sceneAliasForShot(board, segment) : board.sceneRefs[0]?.alias || "@scene_unspecified"}.`,
    `Chars: ${charactersForShot(group, segment.sourceShotNos).map((character) => character.alias).join(",") || "none"}.`,
    `Action: ${clipChars(segment.action || "unspecified visible action", 90)}.`,
    `Camera: ${clipChars(segment.camera || "follow source storyboard camera language", 42)}.`,
    `Perf: subtle breathing/eye/hand motion; keep continuity.`,
    `Dialogue: ${clipChars(segment.dialogue || "no dialogue", 56)}.`,
    `Sound: ${clipChars(segment.sound || "natural ambient sound", 46)}.`
  ].join(" ")).join("\n");

  const prompt = [
    `${formatSecond(board.totalDurationSec)}-second Seedance 2 multi-reference cinematic video storyboard for 《${projectName}》, board ${board.boardId}.`,
    `Duration: ${formatSecond(board.totalDurationSec)} seconds, 16:9 horizontal cinematic framing, up to 1080p production intent.`,
    `Style: ${style}; follow source storyboard; no invented plot; keep shot order.`,
    `Primary scenes: ${sceneLine}.`,
    `Character references: ${characterLine}.`,
    `Image references to attach: ${imageLine}; storyboard sheet reference reserved as ${board.storyboardImageRef.alias} (${board.storyboardImageRef.status}).`,
    `sourceShotNos: ${board.sourceShotNos.join(",")}.`,
    referenceStatus,
    "Continuity lock: same faces, age, body, hair, clothing, props, voice; no drift/deform/artifacts/unregistered characters.",
    buildWardrobePromptLine(board),
    "Lip sync: natural subtle mouth only when speaking; no-dialogue shots keep natural breathing.",
    "Sound: preserve listed dialogue, ambience, Foley, music cues and pauses.",
    segments,
    "Negative constraints: no text/subtitles unless requested, no watermark/logo/signature, no unrelated characters, no extra plot."
  ].join("\n");
  return fitSeedancePromptWithinLimit(prompt, board, group, style, imageLine, sceneLine);
}

function buildWardrobePromptLine(board) {
  if (!board.characters.length) return "Wardrobe lock: no registered recurring characters in this board.";
  const locks = board.characters.map((character) => {
    const lock = character.wardrobeLock;
    return `${character.alias}: ${clipChars(lock.exact_outfit_lock, 42)}; anchors: ${clipChars(lock.visual_anchor_lock.slice(0, 2).join(", ") || character.visualTraits || "use character bible", 48)}`;
  });
  return `Wardrobe and identity lock: ${locks.join(" | ")}. Global forbidden drift: face/age/body/hair/costume/accessories.`;
}

function fitSeedancePromptWithinLimit(prompt, board, group, style, imageLine, sceneLine) {
  if (countChars(prompt) <= SEEDANCE_PROMPT_CHAR_LIMIT) return prompt;

  const compactCharacters = board.characters.length
    ? board.characters.map((character) => `${character.alias}=${character.imageAlias}`).join(", ")
    : "none";
  const compactSegments = board.timeSegments.map((segment) => {
    const chars = charactersForShot(group, segment.sourceShotNos).map((character) => character.alias).join(",") || "none";
    return [
      `${segment.label}: sourceShotNos: ${segment.sourceShotNos.join(",")}.`,
      `${sceneAliasForShot(board, segment)}; ${chars}.`,
      `Action: ${clipChars(segment.action, 72)}.`,
      `Cam: ${clipChars(segment.camera, 32)}.`,
      `Dialog: ${clipChars(segment.dialogue || "no dialogue", 38)}.`,
      `Sound: ${clipChars(segment.sound || "ambient", 32)}.`
    ].join(" ");
  }).join("\n");
  const missing = board.referenceStatus === "ready"
    ? "Refs ready."
    : `Refs unverified: ${board.characters.filter((character) => character.referenceStatus !== "ready").map((character) => character.alias).join(",")}.`;
  const compact = [
    `${formatSecond(board.totalDurationSec)}-second Seedance 2 multi-reference cinematic video storyboard for 《${board.boardId}》.`,
    `Duration ${formatSecond(board.totalDurationSec)}s; 16:9 cinematic; style: ${clipChars(style, 64)}.`,
    `Scenes: ${clipChars(sceneLine, 140)}.`,
    `Refs: chars ${compactCharacters}; images ${clipChars(imageLine, 180)}; storyboard ${board.storyboardImageRef.alias}.`,
    `sourceShotNos: ${board.sourceShotNos.join(",")}. ${missing}`,
    "Lock: same face/age/body/hair/costume/props/voice; no drift, no artifacts, no new characters. Lip sync natural only on dialogue.",
    compactSegments,
    "Negative constraints: no text/subtitles unless requested, no watermark/logo/signature, no extra plot."
  ].join("\n");

  if (countChars(compact) <= SEEDANCE_PROMPT_CHAR_LIMIT) return compact;

  const ultraSegments = board.timeSegments.map((segment) => {
    const chars = charactersForShot(group, segment.sourceShotNos).map((character) => character.alias).join(",") || "none";
    return `${segment.label}: sourceShotNos: ${segment.sourceShotNos.join(",")}. ${sceneAliasForShot(board, segment)} ${chars}. ${clipChars(segment.action, 48)}. Cam ${clipChars(segment.camera, 24)}. ${clipChars(segment.dialogue || "no dialogue", 28)}.`;
  }).join("\n");
  return [
    `${formatSecond(board.totalDurationSec)}-second Seedance 2 multi-reference cinematic video storyboard for 《${board.boardId}》.`,
    `Duration ${formatSecond(board.totalDurationSec)}s; 16:9 cinematic; sourceShotNos: ${board.sourceShotNos.join(",")}.`,
    `Refs: ${compactCharacters}; ${board.storyboardImageRef.alias}; ${board.sceneRefs.map((ref) => ref.alias).join(",")}.`,
    "Lock: same identity/costume/props/voice; natural lip sync; no drift/artifacts/watermark/logo/subtitles/extra plot.",
    ultraSegments
  ].join("\n");
}

function charactersForShot(group, sourceShotNos) {
  const ids = new Set(sourceShotNos);
  const map = new Map();
  for (const shot of group) {
    if (!ids.has(shot.shotNo)) continue;
    for (const character of shot.characters) {
      if (!map.has(character.id)) map.set(character.id, character);
    }
  }
  return [...map.values()];
}

function sceneAliasForShot(board, shotOrSegment) {
  const scene = shotOrSegment.scene || "";
  const exact = board.sceneRefs.find((ref) => ref.source === scene);
  return exact?.alias || board.sceneRefs[0]?.alias || "@scene_unspecified";
}

function flattenReferenceAliases(board) {
  return [
    ...(board.characters || []).map((character) => ({
      alias: character.alias,
      type: "character",
      source: character.name,
      status: character.referenceStatus
    })),
    ...(board.imageRefs || []),
    ...(board.sceneRefs || []),
    board.storyboardImageRef
  ].filter(Boolean);
}

function collectManifestWarnings(boards) {
  return boards.flatMap((board) => board.validationWarnings.map((warning) => `${board.boardId}: ${warning}`));
}

function summarizeScenes(group) {
  const scenes = [...new Set(group.map((shot) => shot.scene).filter(Boolean))];
  return scenes.length ? scenes.join(" / ") : "未明确场景";
}

function summarizeActionChain(group) {
  return group.map((shot) => `分镜${shot.shotNo}:${clipText(shot.purpose || shot.image, 36)}`).join(" -> ");
}

function assertSameOrderedValues(actual, expected, label) {
  if (actual.length !== expected.length || actual.some((value, index) => String(value) !== String(expected[index]))) {
    throw new Error(`${label} mismatch. actual=${actual.join(",")} expected=${expected.join(",")}`);
  }
}

function ensureStrictAscendingShotOrder(values) {
  const numeric = values.map((value) => Number(String(value).match(/\d+/)?.[0] || NaN));
  for (let index = 1; index < numeric.length; index += 1) {
    if (!Number.isNaN(numeric[index]) && !Number.isNaN(numeric[index - 1]) && numeric[index] <= numeric[index - 1]) {
      throw new Error(`Source shot order is not strictly ascending: ${values.join(",")}`);
    }
  }
  if (new Set(values.map(String)).size !== values.length) {
    throw new Error(`Duplicate source shots detected: ${values.join(",")}`);
  }
}

function assertPromptContains(prompt, alias, message) {
  if (alias && !prompt.includes(alias)) throw new Error(message);
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

function sanitizeAlias(value) {
  return String(value || "ref")
    .trim()
    .replace(/^@/, "")
    .replace(/[^\p{L}\p{N}_-]+/gu, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase() || "ref";
}

function slugify(value) {
  const ascii = String(value || "")
    .trim()
    .replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  return ascii || "scene";
}

function formatSecond(value) {
  return Number.isInteger(value) ? String(value) : String(value).replace(/\.0$/, "");
}

function clipText(value, limit) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function countChars(value) {
  return Array.from(String(value || "")).length;
}

function clipChars(value, limit) {
  const chars = Array.from(String(value || "").replace(/\s+/g, " ").trim());
  return chars.length > limit ? `${chars.slice(0, Math.max(0, limit - 1)).join("")}…` : chars.join("");
}

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      index += 1;
    }
  }
  return parsed;
}

async function maybeLoadJson(filePath) {
  if (!filePath) return null;
  try {
    return JSON.parse(await fs.readFile(filePath, "utf8"));
  } catch {
    return null;
  }
}

async function runCli() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.input) {
    console.error("Usage: node generate-seedance2-video-storyboards.mjs --input storyboard.xlsx [--output boards.json] [--project ProjectName] [--character-bible character_bible.json] [--sheet SheetName]");
    process.exit(1);
  }

  const inputPath = path.resolve(args.input);
  const characterBiblePath = path.resolve(args["character-bible"] || "character_bible.json");
  const characterBible = await maybeLoadJson(characterBiblePath);
  if (!characterBible) {
    throw new Error(`Missing required character bible: ${characterBiblePath}`);
  }
  const artStyleBible = await maybeLoadJson(path.resolve(args["art-style-bible"] || "art_style_bible.json"));
  const { headers, rows } = await loadStoryboardRowsFromExcel(inputPath, args.sheet || "");
  const outputPath = path.resolve(args.output || inputPath.replace(/\.xlsx$/i, "_seedance2_storyboards.json"));
  const promptOutputPath = path.resolve(args["prompt-output"] || outputPath.replace(/\.json$/i, "_prompts.md"));
  const projectName = args.project || path.basename(inputPath, path.extname(inputPath)).replace(/_with_video_prompts|storyboard|分镜表/gi, "") || "未命名项目";

  const manifest = generateSeedance2Storyboards({
    projectName,
    source: inputPath,
    headers,
    rows,
    characterBible,
    characterBiblePath,
    verifyReferenceFiles: args["no-verify-reference-files"] ? false : true,
    artStyleBible
  });

  validateSeedance2Manifest(manifest);
  await fs.writeFile(outputPath, JSON.stringify(manifest, null, 2), "utf8");
  await fs.writeFile(promptOutputPath, `\ufeff${renderSeedance2PromptMarkdown(manifest)}`, "utf8");

  console.log(JSON.stringify({
    outputPath,
    promptOutputPath,
    boardCount: manifest.boardCount,
    sourceShotCount: manifest.sourceShotCount,
    warnings: manifest.warnings
  }, null, 2));
}

const currentFile = fileURLToPath(import.meta.url);
if (process.argv[1] && path.resolve(process.argv[1]) === currentFile) {
  runCli().catch((error) => {
    console.error(error?.stack || error?.message || String(error));
    process.exit(1);
  });
}
