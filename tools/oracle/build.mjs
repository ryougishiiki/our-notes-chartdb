import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");
const vendorRoot = join(repoRoot, ".vendor");
const lock = JSON.parse(readFileSync(join(here, "vendor.json"), "utf8"));

function git(cwd, args) {
  return execFileSync("git", ["-C", cwd, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

for (const repo of lock.repositories) {
  const destination = join(vendorRoot, repo.name);
  if (!existsSync(join(destination, ".git"))) {
    console.log(`vendoring ${repo.name} @ ${repo.commit.slice(0, 12)}`);
    execFileSync("git", ["clone", "--filter=blob:none", "--no-checkout", repo.url, destination], { stdio: "inherit" });
  }
  git(destination, ["fetch", "--depth=1", "origin", repo.commit]);
  git(destination, ["checkout", "--detach", repo.commit]);
}

await build({
  entryPoints: [join(here, "oracle_main.ts")],
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  outfile: join(here, "oracle.cjs"),
  logLevel: "warning",
  alias: {
    "@haneoka/cassiopeia": join(here, "cassiopeia-shim.ts"),
    "@haneoka/cassiopeia-plugin-our-notes": join(vendorRoot, "cassiopeia-plugin-our-notes", "src", "index.ts"),
  },
});
console.log("built", join(here, "oracle.cjs"));
