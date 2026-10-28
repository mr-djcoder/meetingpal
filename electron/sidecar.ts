import { ChildProcess, execFileSync, spawn } from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as http from 'http';
import * as net from 'net';
import * as path from 'path';
import { app } from 'electron';

export const TOKEN_HEADER = 'x-meetingpal-token';

// ~60s at 500ms poll: cold model load can exceed 15s on slower/CPU machines.
const MAX_HEALTH_RETRIES = 120;
const HEALTH_POLL_MS = 500;
const MAX_CRASH_RESTARTS = 20;
const CRASH_RESTART_BASE_MS = 2000;
const CRASH_RESTART_MAX_MS = 30000;
// A sidecar that stays up this long counts as healthy again: the crash budget resets so
// 20 is "consecutive crashes", not "crashes over the app's lifetime".
const STABLE_UPTIME_MS = 60000;
// Graceful shutdown saves a live session to disk, which can take a few seconds.
const SHUTDOWN_GRACE_MS = 8000;

function getSidecarPath(): string {
  return path.join(process.resourcesPath, 'sidecar', 'meetingpal', 'meetingpal.exe');
}

function getLogPath(): string {
  const logDir = path.join(app.getPath('appData'), 'MeetingPal', 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  return path.join(logDir, 'sidecar.log');
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address() as net.AddressInfo;
      srv.close(() => resolve(port));
    });
  });
}

export class SidecarManager {
  private process: ChildProcess | null = null;
  private logStream: fs.WriteStream | null = null;
  private crashCount = 0;
  private stopping = false;
  private startedAt = 0;
  private _port = 0;
  // Per-launch shared secret. The sidecar rejects every request without it, so other
  // local processes and web pages cannot talk to it (or read the live transcript).
  readonly token = crypto.randomBytes(32).toString('hex');

  /** Called after the sidecar comes back from a crash (its in-memory state is gone). */
  onRestarted: (() => void) | null = null;

  get port(): number {
    return this._port;
  }

  get baseUrl(): string {
    return `http://127.0.0.1:${this._port}`;
  }

  async spawn(): Promise<void> {
    this.stopping = false;
    this._port = await freePort();
    this.logStream = fs.createWriteStream(getLogPath(), { flags: 'a' });
    this._spawnProcess();
    await this._pollHealth();
  }

  async shutdown(): Promise<void> {
    this.stopping = true;
    const proc = this.process;
    if (!proc) return;
    const exited = proc.exitCode !== null
      ? Promise.resolve()
      : new Promise<void>((resolve) => proc.once('exit', () => resolve()));
    // Ask politely first: the sidecar stops capture and saves the session. On Windows
    // kill('SIGTERM') is an immediate hard kill, which would lose a live recording.
    try {
      await httpRequest('POST', `${this.baseUrl}/api/shutdown`, this.token, 2000);
    } catch {
      // already gone or unresponsive; fall through to the kill below
    }
    const timedOut = await Promise.race([
      exited.then(() => false),
      sleep(SHUTDOWN_GRACE_MS).then(() => true),
    ]);
    if (timedOut) proc.kill('SIGKILL');
    this.logStream?.end();
    this.logStream = null;
    this.process = null;
  }

  private _buildArgs(): { cmd: string; args: string[] } {
    const portArgs = ['--port', String(this._port)];
    if (app.isPackaged) {
      return { cmd: getSidecarPath(), args: portArgs };
    }
    // Development: run with Python. On Windows 'python' may resolve to the Microsoft
    // Store stub, which has no packages, so accept a candidate only if uvicorn imports.
    const local = process.env['LOCALAPPDATA'] ?? '';
    const pythonCandidates = process.platform === 'win32'
      ? [
          path.join(local, 'Programs', 'Python', 'Python312', 'python.exe'),
          path.join(local, 'Programs', 'Python', 'Python311', 'python.exe'),
          'python3',
          'python',
        ]
      : ['python3', 'python'];
    const pythonCmd = pythonCandidates.find((p) => {
      try {
        execFileSync(p, ['-c', 'import uvicorn'], { timeout: 5000 });
        return true;
      } catch { return false; }
    }) ?? 'python';
    return { cmd: pythonCmd, args: ['-m', 'backend.main', ...portArgs] };
  }

  private _spawnProcess(): void {
    const { cmd, args } = this._buildArgs();
    const proc = spawn(cmd, args, {
      stdio: 'pipe',
      env: { ...process.env, PYTHONUNBUFFERED: '1', MEETINGPAL_TOKEN: this.token },
    });
    this.process = proc;
    this.startedAt = Date.now();

    const timestamp = () => new Date().toISOString();
    proc.stdout?.on('data', (d: Buffer) => {
      this.logStream?.write(`[${timestamp()}] STDOUT: ${d.toString()}`);
    });
    proc.stderr?.on('data', (d: Buffer) => {
      this.logStream?.write(`[${timestamp()}] STDERR: ${d.toString()}`);
    });

    proc.once('exit', (code) => {
      if (this.stopping || this.process !== proc) return;
      if (Date.now() - this.startedAt >= STABLE_UPTIME_MS) this.crashCount = 0;
      if (this.crashCount >= MAX_CRASH_RESTARTS) {
        this.logStream?.write(`[${timestamp()}] CRASH LOOP: giving up after ${this.crashCount} restarts\n`);
        return;
      }
      this.crashCount++;
      const delay = Math.min(CRASH_RESTART_BASE_MS * 2 ** (this.crashCount - 1), CRASH_RESTART_MAX_MS);
      this.logStream?.write(
        `[${timestamp()}] CRASH #${this.crashCount} (code=${code}), restarting in ${delay}ms\n`
      );
      setTimeout(() => {
        if (this.stopping) return;
        this._spawnProcess();
        this._pollHealth()
          .then(() => { if (!this.stopping) this.onRestarted?.(); })
          .catch((err) => this.logStream?.write(`[${timestamp()}] restart failed: ${err}\n`));
      }, delay);
    });
  }

  private async _pollHealth(): Promise<void> {
    for (let i = 0; i < MAX_HEALTH_RETRIES; i++) {
      await sleep(HEALTH_POLL_MS);
      try {
        if (await httpRequest('GET', `${this.baseUrl}/health`, this.token, 400)) return;
      } catch {
        // Not ready yet
      }
    }
    throw new Error('Sidecar failed to start within timeout');
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function httpRequest(method: string, url: string, token: string, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { method, headers: { [TOKEN_HEADER]: token } }, (res) => {
      resolve(res.statusCode === 200);
      res.resume();
    });
    req.on('error', reject);
    req.setTimeout(timeoutMs, () => { req.destroy(); reject(new Error('timeout')); });
    req.end();
  });
}
