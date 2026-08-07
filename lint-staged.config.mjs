import { execFileSync } from "node:child_process";
import path from "node:path";

const appName = (file) => {
  const match = file.match(/^apps\/([^/]+)\//);
  return match ? `@webchat/${match[1]}` : null;
};

export default {
  "*.{ts,tsx,js,jsx}": (files) => {
    const groups = new Map();
    for (const file of files) {
      const name = appName(file);
      if (!name) continue;
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(path.resolve(file));
    }
    for (const [name, paths] of groups) {
      execFileSync("pnpm", ["--filter", name, "exec", "eslint", "--fix", ...paths], {
        stdio: "inherit",
      });
    }
    return [];
  },
  "*.{ts,tsx,js,jsx,json,css,md}": ["prettier --write"],
  "*.py": ["uv run ruff check --fix"]
}
