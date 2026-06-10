const root = new URL("..", import.meta.url).pathname.replace(/\/$/, "");

function run(name: string, command: string[], cwd: string) {
  const proc = Bun.spawn(command, {
    cwd,
    stdout: "inherit",
    stderr: "inherit",
    stdin: "inherit",
    env: {
      ...process.env,
      KB_DEFAULT_ROOT: root,
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
