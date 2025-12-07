import { spawn, ChildProcess } from 'child_process';
import { EventEmitter } from 'events';

/**
 * Message types that clio can send
 */
export interface EditMessage {
  type: 'edit';
  file: string;
  edits: Array<{
    range: {
      start: { line: number; character: number };
      end: { line: number; character: number };
    };
    newText: string;
  }>;
}

export interface ResponseMessage {
  type: 'response';
  content: string;
}

export interface StatusMessage {
  type: 'status';
  activity: string;
}

export type ClioMessage = EditMessage | ResponseMessage | StatusMessage;

/**
 * Manages the clio CLI process and handles communication via stdin/stdout
 */
export class ClioClient extends EventEmitter {
  private process: ChildProcess | null = null;
  private buffer: string = '';

  /**
   * Start the clio CLI process
   */
  async start(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        // Spawn clio with vscode subcommand for JSON protocol
        this.process = spawn('clio', ['vscode'], {
          stdio: ['pipe', 'pipe', 'pipe'],
        });

        // Handle stdout - parse JSON messages
        this.process.stdout?.on('data', (data: Buffer) => {
          this.handleStdout(data);
        });

        // Handle stderr - log errors
        this.process.stderr?.on('data', (data: Buffer) => {
          console.error(`[clio stderr]: ${data.toString()}`);
          this.emit('error', new Error(data.toString()));
        });

        // Handle process exit
        this.process.on('exit', (code, signal) => {
          console.log(`[clio] Process exited with code ${code}, signal ${signal}`);
          this.emit('exit', { code, signal });
        });

        // Handle process errors
        this.process.on('error', (err) => {
          console.error('[clio] Process error:', err);
          this.emit('error', err);
          reject(err);
        });

        // Assume successful start if no immediate error
        setTimeout(() => {
          if (this.process && !this.process.killed) {
            resolve();
          }
        }, 100);
      } catch (err) {
        reject(err);
      }
    });
  }

  /**
   * Handle stdout data and parse JSON messages
   */
  private handleStdout(data: Buffer): void {
    try {
      // Append to buffer
      this.buffer += data.toString();

      // Try to parse complete JSON messages (newline-delimited)
      const lines = this.buffer.split('\n');
      
      // Keep the last incomplete line in buffer
      this.buffer = lines.pop() || '';

      // Process complete lines
      for (const line of lines) {
        if (line.trim()) {
          try {
            const message: ClioMessage = JSON.parse(line);
            this.handleMessage(message);
          } catch (parseErr) {
            console.error('[clio] Failed to parse message:', line, parseErr);
          }
        }
      }
    } catch (err) {
      console.error('[clio] Error handling stdout:', err);
      this.emit('error', err);
    }
  }

  /**
   * Route parsed messages to appropriate event handlers
   */
  private handleMessage(message: ClioMessage): void {
    switch (message.type) {
      case 'edit':
        this.emit('edit', message);
        break;
      case 'response':
        this.emit('response', message);
        break;
      case 'status':
        this.emit('status', message);
        break;
      default:
        console.warn('[clio] Unknown message type:', message);
    }
  }

  /**
   * Send a message to clio via stdin
   */
  sendMessage(content: string): void {
    if (!this.process || !this.process.stdin) {
      console.error('[clio] Cannot send message: process not started');
      return;
    }

    try {
      const message = JSON.stringify({ content }) + '\n';
      this.process.stdin.write(message);
    } catch (err) {
      console.error('[clio] Error sending message:', err);
      this.emit('error', err);
    }
  }

  /**
   * Stop the clio process
   */
  stop(): void {
    if (this.process) {
      try {
        this.process.kill();
        this.process = null;
      } catch (err) {
        console.error('[clio] Error stopping process:', err);
      }
    }
  }

  /**
   * Check if the process is running
   */
  isRunning(): boolean {
    return this.process !== null && !this.process.killed;
  }
}
