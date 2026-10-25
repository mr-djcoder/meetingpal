import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';
import { app } from 'electron';

const PORT = 8001;
const HEALTH_URL = `http://127.0.0.1:${PORT}/health`;
// ~60s at 500ms poll — dual-stream loads two Silero VAD models, so cold model
// load can exceed the old 15s budget on slower/CPU machines.
const MAX_HEALTH_RETRIES = 120;
const HEALTH_POLL_MS = 500;
const MAX_CRASH_RESTARTS = 20;
const CRASH_RESTART_DELAY_MS = 2000;
const CRASH_RESTART_MAX_DELAY_MS = 15000;

function getSidecarPath(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'sidecar', 'meetingpal', 'meetingpal.exe');
  }
  // Dev: assume Python is on PATH and run backend/main.py directly
  return process.execPath; // placeholder; see _buildArgs
}

function getLogPath(): string {
  const logDir = path.join(app.getPath('appData'), 'MeetingPal', 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  return path.join(logDir, 'sidecar.log');
}

export class SidecarManager {
  private process: ChildProcess | null = null;
  private logStream: fs.WriteStream | null = null;
  private crashCount = 0;
  private stopping = false;

  async spawn(): Promise<void> {
    this.stopping = false;
    await this._spawnProcess();
    await this._pollHealth();
  }

  async shutdown(): Promise<void> {
    this.stopping = true;
    if (!this.process) return;
    this.process.kill('SIGTERM');
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        this.process?.kill('SIGKILL');
        resolve();
      }, 3000);
      this.process!.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
    this.logStream?.end();
    this.process = null;
  }

  get port(): number {
    return PORT;
  }

  private _buildArgs(): { cmd: string; args: string[] } {
    if (app.isPackaged) {
      return { cmd: getSidecarPath(), args: ['--port', String(PORT)] };
    }
    // Development: run with Python
    // On Windows, 'python' may resolve to the Microsoft Store stub which has no
    // packages installed. Verify uvicorn is importable before accepting a candidate.
    // Prefer known install paths first so we skip the stub quickly.
    const pythonCandidates = process.platform === 'win32'
      ? [
          path.join(process.env['LOCALAPPDATA'] ?? '', 'Programs', 'Python', 'Python312', 'python.exe'),
          path.join(process.env['LOCALAPPDATA'] ?? '', 'Programs', 'Python', 'Python311', 'python.exe'),
          'python3',
          'python',
        ]
      : ['python3', 'python'];
    const pythonCmd = pythonCandidates.find((p) => {
      try {
        require('child_process').execFileSync(p, ['-c', 'import uvicorn'], { timeout: 5000 });
        return true;
      } catch { return false; }
    }) ?? 'python';
    return {
      cmd: pythonCmd,
      args: ['-m', 'backend.main', '--port', String(PORT)],
    };
  }

  private async _spawnProcess(): Promise<void> {
    const logPath = getLogPath();
    this.logStream = fs.createWriteStream(logPath, { flags: 'a' });

    const { cmd, args } = this._buildArgs();
    this.process = spawn(cmd, args, {
      stdio: 'pipe',
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });

    const timestamp = () => new Date().toISOString();
    this.process.stdout?.on('data', (d: Buffer) => {
      const msg = `[${timestamp()}] STDOUT: ${d.toString()}`;
      this.logStream?.write(msg);
    });
    this.process.stderr?.on('data', (d: Buffer) => {
      const msg = `[${timestamp()}] STDERR: ${d.toString()}`;
      this.logStream?.write(msg);
    });

    this.process.once('exit', (code) => {
      if (!this.stopping && this.crashCount < MAX_CRASH_RESTARTS) {
        this.crashCount++;
        // Exponential backoff capped at max delay so rapid crashes don't spin-loop
        const delay = Math.min(CRASH_RESTART_DELAY_MS * this.crashCount, CRASH_RESTART_MAX_DELAY_MS);
        this.logStream?.write(
          `[${timestamp()}] CRASH #${this.crashCount} (code=${code}), restarting in ${delay}ms\n`
        );
        setTimeout(() => {
          if (!this.stopping) this._spawnProcess();
        }, delay);
      }
    });
  }

  private async _pollHealth(): Promise<void> {
    for (let i = 0; i < MAX_HEALTH_RETRIES; i++) {
      await sleep(HEALTH_POLL_MS);
      try {
        const ok = await httpGet(HEALTH_URL);
        if (ok) return;
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

function httpGet(url: string): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      resolve(res.statusCode === 200);
      res.resume();
    });
    req.on('error', reject);
    req.setTimeout(400, () => { req.destroy(); reject(new Error('timeout')); });
  });
}
