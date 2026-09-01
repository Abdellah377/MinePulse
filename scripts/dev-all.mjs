/**
 * One-terminal MinePulse launcher.
 * Starts FastAPI (with embedded simulator) + Vite UI.
 * Ctrl+C stops both.
 */
import { spawn, spawnSync } from "node:child_process"
import path from "node:path"
import { fileURLToPath } from "node:url"

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const backend = path.join(root, "backend")
const isWin = process.platform === "win32"
const py = isWin ? "python" : "python3"

/** @type {import('node:child_process').ChildProcess[]} */
const children = []
let shuttingDown = false

function prefix(name, colorCode) {
  return `\x1b[${colorCode}m[${name}]\x1b[0m`
}

function pipe(child, name, colorCode) {
  const tag = prefix(name, colorCode)
  const handle = (buf, stream) => {
    const text = buf.toString()
    for (const line of text.split(/\r?\n/)) {
      if (line.length) stream.write(`${tag} ${line}\n`)
    }
  }
  child.stdout?.on("data", (d) => handle(d, process.stdout))
  child.stderr?.on("data", (d) => handle(d, process.stderr))
}

function start(name, colorCode, command, args, cwd) {
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    shell: isWin,
    stdio: ["ignore", "pipe", "pipe"],
  })
  children.push(child)
  pipe(child, name, colorCode)
  child.on("exit", (code, signal) => {
    if (shuttingDown) return
    console.log(`${prefix(name, colorCode)} exited (code=${code}, signal=${signal})`)
    shutdown(code ?? 1)
  })
  return child
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForApiReady(url, timeoutMs = 45_000) {
  const started = Date.now()
  let announced = false

  while (!shuttingDown) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(1_500) })
      if (res.ok) return true
    } catch {
      /* FastAPI is still starting. */
    }

    if (!announced) {
      console.log(`${prefix("api", "36")} waiting for FastAPI readiness…`)
      announced = true
    }

    if (Date.now() - started > timeoutMs) return false
    await wait(500)
  }

  return false
}

async function probeMinePulseApi(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1_500) })
    if (!res.ok) return false
    const payload = await res.json()
    return payload?.status === "ok" && typeof payload?.simulator === "object"
  } catch {
    return false
  }
}

async function probeMinePulseUi(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1_500) })
    if (!res.ok) return false
    const html = await res.text()
    return html.includes("<title>MinePulse") && html.includes('id="root"')
  } catch {
    return false
  }
}

function shutdown(code = 0) {
  if (shuttingDown) return
  shuttingDown = true
  console.log("\nStopping MinePulse…")
  for (const child of children) {
    if (!child.killed) {
      try {
        if (isWin) {
          spawn("taskkill", ["/pid", String(child.pid), "/f", "/t"], { stdio: "ignore" })
        } else {
          child.kill("SIGTERM")
        }
      } catch {
        /* ignore */
      }
    }
  }
  setTimeout(() => process.exit(code), 500)
}

process.on("SIGINT", () => shutdown(0))
process.on("SIGTERM", () => shutdown(0))

console.log(`
MinePulse — one terminal
  API + embedded simulator  →  http://127.0.0.1:8000
  UI                        →  http://localhost:5173
  Simulation Centre         →  http://localhost:5173/dev/simulation

Press Ctrl+C to stop everything.
`)

console.log(`${prefix("db", "33")} applying pending database migrations…`)
const migration = spawnSync(py, ["-m", "alembic", "upgrade", "head"], {
  cwd: backend,
  env: { ...process.env, PYTHONUNBUFFERED: "1" },
  stdio: "inherit",
})
if (migration.error || migration.status !== 0) {
  console.error(`${prefix("db", "33")} migration failed; API and UI were not started.`)
  process.exit(migration.status ?? 1)
}
console.log(`${prefix("db", "33")} database schema is current.`)

const healthUrl = "http://127.0.0.1:8000/health"
const reuseApi = await probeMinePulseApi(healthUrl)
if (reuseApi) {
  console.log(
    `${prefix("api", "36")} an existing healthy MinePulse API already owns port 8000; reusing it.`,
  )
} else {
  start(
    "api",
    "36",
    py,
    [
      "-m",
      "uvicorn",
      "app.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
      "--reload",
      "--reload-dir",
      "app",
      "--reload-dir",
      "simulator",
      "--reload-exclude",
      "*.json",
      "--reload-exclude",
      "*.jsonl",
    ],
    backend,
  )
}

const ready = reuseApi || (await waitForApiReady(healthUrl))
if (!ready && !shuttingDown) {
  console.log(`${prefix("api", "36")} readiness timed out; starting UI so the app can show degraded API state.`)
}

if (!shuttingDown) {
  const reuseUi = await probeMinePulseUi("http://127.0.0.1:5173/")
  if (reuseUi) {
    console.log(
      `${prefix("web", "35")} an existing healthy MinePulse UI already owns port 5173; reusing it.`,
    )
  } else {
    start(
      "web",
      "35",
      isWin ? "npm.cmd" : "npm",
      ["run", "dev", "--", "--host", "127.0.0.1", "--strictPort"],
      root,
    )
  }
}
