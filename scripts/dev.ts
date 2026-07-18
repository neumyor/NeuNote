const root = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const envFile = Bun.file(`${root}/.env`);
if (await envFile.exists()) {
  const content = await envFile.text();
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim().replace(/^["']|["']$/g, "");
    if (!(key in process.env)) process.env[key] = value;
  }
}

const dataRoot = process.env.KB_DEFAULT_ROOT ?? `${process.env.HOME ?? root}/.neunote`;

function run(name: string, command: string[], cwd: string) {
  const proc = Bun.spawn(command, {
    cwd,
    stdout: "inherit",
    stderr: "inherit",
    stdin: "inherit",
    env: {
      ...process.env,
      KB_DEFAULT_ROOT: dataRoot,
      PYTHONUNBUFFERED: "1"
    }
  });

  proc.exited.then((code) => {
    if (code !== 0) {
      console.error(`${name} exited with code ${code}`);
      cleanup();
      process.exit(code ?? 1);
    }
  });

  return proc;
}

const children = [
  run("backend", ["uv", "run", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8765"], `${root}/backend`),
  run("frontend", ["bun", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"], `${root}/frontend`)
];

function cleanup() {
  for (const child of children) child.kill();
}

process.on("SIGINT", () => {
  cleanup();
  process.exit(0);
});

console.log("Backend:  http://127.0.0.1:8765");
console.log("Frontend: http://127.0.0.1:5173");
