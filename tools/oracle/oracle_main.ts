// Independent correctness oracle: the audited Our Notes normalizer.
// Emits JSON on stdout: { ssVersion, rawNoteCount, judgedCount, ... }
import fs from "node:fs";
import zlib from "node:zlib";
import { parseScore } from "../../.vendor/cassiopeia-plugin-our-notes/src/core/parser.ts";
import { buildChart } from "../../.vendor/cassiopeia-plugin-our-notes/src/core/chart.ts";

function main(): void {
  const file = process.argv[2];
  if (!file) throw new Error("usage: oracle.cjs <chart.bytes>");
  let raw: Buffer = fs.readFileSync(file);
  if (raw.length >= 2 && raw[0] === 0x1f && raw[1] === 0x8b) raw = zlib.gunzipSync(raw);
  const root = parseScore(raw.toString("utf8"));
  const chart = buildChart(root);
  const judged = chart.notes.filter((note) => note.judged).length;
  const authoredJudge = chart.notes.filter(
    (note) => note.judged && note.operateType !== 120 && note.operateType !== 121,
  ).length;
  const combo = chart.notes.filter((note) => note.operateType === 120).length;
  const comboSkip = chart.notes.filter((note) => note.operateType === 121).length;
  const histogram: Record<string, number> = {};
  for (const note of chart.notes) {
    const key = String(note.operateType);
    histogram[key] = (histogram[key] ?? 0) + 1;
  }
  process.stdout.write(
    JSON.stringify({
      oracle: "cassiopeia-plugin-our-notes",
      ssVersion: root.version,
      rawNoteCount: root.notes.length,
      totalNotes: chart.notes.length,
      judgedCount: judged,
      authoredJudgedCount: authoredJudge,
      generatedComboCount: combo,
      generatedComboSkipCount: comboSkip,
      lineCount: chart.lines.length,
      durationMs: chart.durationMs,
      operateTypeHistogram: histogram,
    }),
  );
}
main();
