import {spawnSync} from "node:child_process";
import {globSync, mkdtempSync, rmSync} from "node:fs";
import {join, resolve} from "node:path";

const output = mkdtempSync(resolve("node_modules", ".cabinet-tests-"));

function run(args) {
  const child = spawnSync(process.execPath, args, {stdio: "inherit"});
  if (child.error) throw child.error;
  return child.status ?? 1;
}

try {
  const status = run(["node_modules/typescript/bin/tsc", "-p", "tsconfig.tests.json", "--outDir", output]);
  if (status !== 0) {
    process.exitCode = status;
  } else {
    const sources = globSync("**/*.test.tsx", {cwd: "src"}).sort();
    if (!sources.length) throw new Error("No cabinet tests found under src");
    const tests = sources.map(path => join(output, path.replace(/\.tsx$/, ".js")));
    console.log(`Running ${tests.length} cabinet test files`);
    process.exitCode = run(["--require", "./scripts/test-dom.cjs", "--test", ...tests]);
  }
} finally {
  rmSync(output, {recursive: true, force: true});
}
