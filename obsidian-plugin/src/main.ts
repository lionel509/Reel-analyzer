import { spawn } from "node:child_process";
import { homedir } from "node:os";

import {
  App,
  Editor,
  MarkdownView,
  Modal,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
  TFile,
  normalizePath,
} from "obsidian";

interface ReelAnalyzerSettings {
  /** Stored here rather than in an env var, so it lives in one place you can edit. */
  apiKey: string;
  pythonPath: string;
  /** Absolute path to the folder holding pyproject.toml. Absolute, because the
   *  code lives in Citadel while this plugin may be installed in any vault. */
  projectPath: string;
  visionModel: string;
  transcriptionModel: string;
  uniformFps: string;
  maxFrames: string;
  chunkSize: string;
  cookiesFile: string;
  /** Where a result goes when no note is open. */
  outputFolder: string;
  insertIntoActiveNote: boolean;
}

const PROJECT_HOME = `${homedir()}/Documents/Citadel/Active/Reel Analyzer MCP`;

const DEFAULT_SETTINGS: ReelAnalyzerSettings = {
  apiKey: "",
  pythonPath: `${homedir()}/.venvs/reel-analyzer/bin/python`,
  projectPath: PROJECT_HOME,
  visionModel: "google/gemma-4-26b-a4b-it",
  transcriptionModel: "openai/whisper-large-v3",
  uniformFps: "3.0",
  maxFrames: "360",
  chunkSize: "120",
  cookiesFile: "",
  outputFolder: "Active/Reel Analyzer MCP/Analyses",
  insertIntoActiveNote: true,
};

interface RunResult {
  output: string;
  code: number;
}

/** A single analysis run, with live progress from the pipeline's stderr. */
class Analysis {
  private stdout = "";
  private stderr = "";

  constructor(
    private settings: ReelAnalyzerSettings,
    private projectPath: string,
  ) {}

  run(target: string, onProgress: (line: string) => void): Promise<RunResult> {
    const env: Record<string, string> = {
      ...(process.env as Record<string, string>),
      OPENROUTER_API_KEY: this.settings.apiKey,
      VISION_MODEL: this.settings.visionModel,
      TRANSCRIPTION_MODEL: this.settings.transcriptionModel,
      UNIFORM_FPS: this.settings.uniformFps,
      MAX_FRAMES: this.settings.maxFrames,
      VISION_CHUNK_SIZE: this.settings.chunkSize,
    };
    if (this.settings.cookiesFile.trim()) {
      env.INSTAGRAM_COOKIES_FILE = this.settings.cookiesFile.trim();
    }

    return new Promise((resolve, reject) => {
      const child = spawn(
        this.settings.pythonPath,
        ["-m", "reel_analyzer.smoke", target, "-v"],
        { env, cwd: this.projectPath },
      );

      child.stdout.on("data", (chunk: Buffer) => {
        this.stdout += chunk.toString();
      });

      child.stderr.on("data", (chunk: Buffer) => {
        const text = chunk.toString();
        this.stderr += text;
        for (const line of text.split("\n")) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (trimmed.includes("extracted") && trimmed.includes("frames")) {
            onProgress(trimmed.replace(/^INFO [^:]+: /, ""));
          } else if (trimmed.includes("audio/transcriptions")) {
            onProgress("transcribing audio…");
          } else if (trimmed.includes("chat/completions")) {
            onProgress("reading the frames…");
          } else if (trimmed.startsWith("failed:") || trimmed.startsWith("config error:")) {
            onProgress(trimmed);
          }
        }
      });

      child.on("error", (error) => {
        reject(
          new Error(
            `Could not run ${this.settings.pythonPath} — check the Python path in settings. (${error.message})`,
          ),
        );
      });

      child.on("close", (code) => {
        if (code === 0) {
          resolve({ output: this.stdout.trim(), code });
          return;
        }
        const reason =
          this.stderr
            .split("\n")
            .map((l) => l.trim())
            .filter((l) => l.startsWith("failed:") || l.startsWith("config error:"))
            .pop() ?? this.stderr.trim().split("\n").slice(-3).join(" ");
        reject(new Error(reason || `analysis exited with code ${code}`));
      });
    });
  }
}

class ReelPromptModal extends Modal {
  private value = "";
  private statusEl!: HTMLElement;
  private analyseButton!: HTMLButtonElement;
  private running = false;

  constructor(
    app: App,
    private plugin: ReelAnalyzerPlugin,
  ) {
    super(app);
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("reel-analyzer-modal");

    contentEl.createEl("h3", { text: "Analyze a reel" });

    const input = contentEl.createEl("input", {
      cls: "reel-analyzer-input",
      attr: {
        type: "text",
        placeholder: "https://www.instagram.com/reel/… or a local video path",
      },
    });
    input.focus();
    input.addEventListener("input", () => {
      this.value = input.value.trim();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !this.running) void this.start();
    });

    this.statusEl = contentEl.createDiv({ cls: "reel-analyzer-status" });
    this.statusEl.setText("A 30-second reel takes roughly a minute.");

    const buttons = contentEl.createDiv({ cls: "reel-analyzer-buttons" });
    this.analyseButton = buttons.createEl("button", { text: "Analyze", cls: "mod-cta" });
    this.analyseButton.addEventListener("click", () => void this.start());

    const cancel = buttons.createEl("button", { text: "Cancel" });
    cancel.addEventListener("click", () => this.close());
  }

  private async start(): Promise<void> {
    if (!this.value) {
      this.statusEl.setText("Paste a link first.");
      return;
    }
    if (!this.plugin.settings.apiKey.trim()) {
      this.statusEl.setText("No OpenRouter API key — add one in Reel Analyzer settings.");
      return;
    }

    this.running = true;
    this.analyseButton.disabled = true;
    this.analyseButton.setText("Working…");
    this.statusEl.setText("downloading…");

    try {
      const result = await this.plugin.analyze(this.value, (line) => {
        this.statusEl.setText(line);
      });
      await this.plugin.deliver(this.value, result);
      this.close();
    } catch (error) {
      this.statusEl.setText(String(error instanceof Error ? error.message : error));
      this.analyseButton.disabled = false;
      this.analyseButton.setText("Retry");
      this.running = false;
    }
  }

  onClose(): void {
    this.contentEl.empty();
  }
}

class ReelAnalyzerSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: ReelAnalyzerPlugin) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl).setName("Connection").setHeading();

    new Setting(containerEl)
      .setName("OpenRouter API key")
      .setDesc("Stored in this plugin's data.json inside your vault. Never leaves this machine except in calls to OpenRouter.")
      .addText((text) => {
        text.inputEl.type = "password";
        text.inputEl.style.width = "22em";
        text
          .setPlaceholder("sk-or-v1-…")
          .setValue(this.plugin.settings.apiKey)
          .onChange(async (value) => {
            this.plugin.settings.apiKey = value.trim();
            await this.plugin.saveSettings();
          });
      });

    new Setting(containerEl)
      .setName("Python interpreter")
      .setDesc("The venv that has reel_analyzer installed.")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.pythonPath)
          .setValue(this.plugin.settings.pythonPath)
          .onChange(async (value) => {
            this.plugin.settings.pythonPath = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Project folder")
      .setDesc(
        "Absolute path to the reel-analyzer code (the folder with pyproject.toml). It lives in Citadel even when this plugin runs from another vault.",
      )
      .addText((text) => {
        text.inputEl.style.width = "22em";
        text
          .setPlaceholder(PROJECT_HOME)
          .setValue(this.plugin.settings.projectPath)
          .onChange(async (value) => {
            this.plugin.settings.projectPath = value.trim();
            await this.plugin.saveSettings();
          });
      });

    new Setting(containerEl)
      .setName("Check setup")
      .setDesc("Confirm the interpreter, the package, and ffmpeg are all reachable.")
      .addButton((button) =>
        button.setButtonText("Run check").onClick(async () => {
          button.setButtonText("Checking…");
          const message = await this.plugin.checkSetup();
          new Notice(message, 8000);
          button.setButtonText("Run check");
        }),
      );

    new Setting(containerEl).setName("Models").setHeading();

    new Setting(containerEl)
      .setName("Vision model")
      .setDesc("Reads the frames. Switch to google/gemma-4-31b-it if captions read poorly.")
      .addText((text) =>
        text
          .setValue(this.plugin.settings.visionModel)
          .onChange(async (value) => {
            this.plugin.settings.visionModel = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Transcription model")
      .addText((text) =>
        text
          .setValue(this.plugin.settings.transcriptionModel)
          .onChange(async (value) => {
            this.plugin.settings.transcriptionModel = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl).setName("Frame sampling").setHeading();

    new Setting(containerEl)
      .setName("Frames per second")
      .setDesc("How densely the clip is sampled. 3 is triple what a native-video model sees — raise it for very fast cuts.")
      .addText((text) =>
        text.setValue(this.plugin.settings.uniformFps).onChange(async (value) => {
          this.plugin.settings.uniformFps = value.trim();
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Maximum frames")
      .setDesc("Total cap across the whole clip. 360 covers two minutes at 3fps.")
      .addText((text) =>
        text.setValue(this.plugin.settings.maxFrames).onChange(async (value) => {
          this.plugin.settings.maxFrames = value.trim();
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Frames per request")
      .setDesc("Longer clips split across this many frames per call, run in parallel. 150 is the measured ceiling.")
      .addText((text) =>
        text.setValue(this.plugin.settings.chunkSize).onChange(async (value) => {
          this.plugin.settings.chunkSize = value.trim();
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl).setName("Access and output").setHeading();

    new Setting(containerEl)
      .setName("Instagram cookies file")
      .setDesc("Netscape-format export, for private or rate-limited reels. Optional.")
      .addText((text) =>
        text
          .setPlaceholder("/Users/…/cookies.txt")
          .setValue(this.plugin.settings.cookiesFile)
          .onChange(async (value) => {
            this.plugin.settings.cookiesFile = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Insert into the open note")
      .setDesc("When off, every analysis becomes a new note in the folder below.")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.insertIntoActiveNote).onChange(async (value) => {
          this.plugin.settings.insertIntoActiveNote = value;
          await this.plugin.saveSettings();
        }),
      );

    new Setting(containerEl)
      .setName("Folder for new notes")
      .addText((text) =>
        text
          .setPlaceholder(DEFAULT_SETTINGS.outputFolder)
          .setValue(this.plugin.settings.outputFolder)
          .onChange(async (value) => {
            this.plugin.settings.outputFolder = value.trim();
            await this.plugin.saveSettings();
          }),
      );
  }
}

export default class ReelAnalyzerPlugin extends Plugin {
  settings: ReelAnalyzerSettings = { ...DEFAULT_SETTINGS };

  async onload(): Promise<void> {
    await this.loadSettings();

    this.addRibbonIcon("clapperboard", "Analyze a reel", () => {
      new ReelPromptModal(this.app, this).open();
    });

    this.addCommand({
      id: "analyze-reel",
      name: "Analyze a reel from a link",
      callback: () => new ReelPromptModal(this.app, this).open(),
    });

    this.addCommand({
      id: "analyze-reel-from-selection",
      name: "Analyze the selected link",
      editorCallback: (editor: Editor) => {
        const selection = editor.getSelection().trim();
        if (!selection) {
          new Notice("Select a link first.");
          return;
        }
        void this.runInline(selection, editor);
      },
    });

    this.addSettingTab(new ReelAnalyzerSettingTab(this.app, this));
  }

  /** The folder holding pyproject.toml, used as the subprocess working directory. */
  private projectPath(): string {
    return this.settings.projectPath || PROJECT_HOME;
  }

  /** Pick an output folder that exists in *this* vault.
   *
   *  The plugin runs from the umbrella vault (which contains Citadel/) as well
   *  as from Citadel itself, so the same relative path is not correct in both.
   *  Only applied on a fresh install — never overrides a saved choice.
   */
  private resolveVaultDefaults(saved: Partial<ReelAnalyzerSettings> | null): void {
    if (saved?.outputFolder) return;
    const nested = "Citadel/Active/Reel Analyzer MCP/Analyses";
    const direct = "Active/Reel Analyzer MCP/Analyses";
    this.settings.outputFolder = this.app.vault.getAbstractFileByPath("Citadel")
      ? nested
      : direct;
  }

  analyze(target: string, onProgress: (line: string) => void): Promise<RunResult> {
    return new Analysis(this.settings, this.projectPath()).run(target, onProgress);
  }

  private async runInline(target: string, editor: Editor): Promise<void> {
    const notice = new Notice("Analyzing reel…", 0);
    try {
      const result = await this.analyze(target, (line) => notice.setMessage(`Reel: ${line}`));
      editor.replaceSelection(`${target}\n\n${this.asCallout(result.output)}\n`);
      notice.hide();
      new Notice("Analysis inserted.");
    } catch (error) {
      notice.hide();
      new Notice(`Reel analysis failed: ${error instanceof Error ? error.message : error}`, 10000);
    }
  }

  private asCallout(output: string): string {
    const body = output
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    return `> [!abstract] Reel analysis\n${body}`;
  }

  /** Put the finished analysis where the settings say it should go. */
  async deliver(target: string, result: RunResult): Promise<void> {
    const view = this.app.workspace.getActiveViewOfType(MarkdownView);

    if (this.settings.insertIntoActiveNote && view) {
      view.editor.replaceSelection(`${target}\n\n${this.asCallout(result.output)}\n`);
      new Notice("Analysis inserted.");
      return;
    }

    const folder = normalizePath(this.settings.outputFolder || DEFAULT_SETTINGS.outputFolder);
    if (!this.app.vault.getAbstractFileByPath(folder)) {
      await this.app.vault.createFolder(folder).catch(() => undefined);
    }

    const title = this.titleFor(result.output, target);
    const path = normalizePath(`${folder}/${title}.md`);
    const contents = [
      "---",
      "tags:",
      "  - projects",
      "  - log",
      "  - reel-analysis",
      "---",
      "",
      `# ${title}`,
      "",
      `Source: ${target}`,
      "",
      result.output,
      "",
      "Hub: [[Reel Analyzer MCP — Project Hub]]",
      "",
    ].join("\n");

    const existing = this.app.vault.getAbstractFileByPath(path);
    const file =
      existing instanceof TFile
        ? (await this.app.vault.modify(existing, contents), existing)
        : await this.app.vault.create(path, contents);

    await this.app.workspace.getLeaf("tab").openFile(file);
    new Notice(`Saved to ${path}`);
  }

  /** Build a filename-safe title from the clip's own title line. */
  private titleFor(output: string, target: string): string {
    const match = /^TITLE:\s*(.+)$/m.exec(output);
    const raw = (match?.[1] ?? target).trim();
    const cleaned = raw
      .replace(/https?:\/\//g, "")
      .replace(/[\\/:*?"<>|#^[\]]/g, "-")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80);
    return cleaned || "Reel analysis";
  }

  /** Verify the interpreter, the package, and ffmpeg before the user hits a failure mid-run. */
  async checkSetup(): Promise<string> {
    const script =
      "import shutil, reel_analyzer, sys; " +
      "print('python', sys.version.split()[0]); " +
      "print('reel_analyzer', reel_analyzer.__version__); " +
      "print('ffmpeg', 'yes' if shutil.which('ffmpeg') else 'MISSING'); " +
      "print('ffprobe', 'yes' if shutil.which('ffprobe') else 'MISSING')";

    return new Promise((resolve) => {
      const child = spawn(this.settings.pythonPath, ["-c", script], {
        cwd: this.projectPath(),
      });
      let out = "";
      let err = "";
      child.stdout.on("data", (c: Buffer) => (out += c.toString()));
      child.stderr.on("data", (c: Buffer) => (err += c.toString()));
      child.on("error", (error) =>
        resolve(`Cannot run ${this.settings.pythonPath}\n${error.message}`),
      );
      child.on("close", (code) => {
        if (code !== 0) {
          resolve(`Setup check failed:\n${err.trim().split("\n").slice(-4).join("\n")}`);
          return;
        }
        const key = this.settings.apiKey.trim() ? "API key set" : "API key MISSING";
        resolve(`${out.trim()}\n${key}`);
      });
    });
  }

  async loadSettings(): Promise<void> {
    const saved = (await this.loadData()) as Partial<ReelAnalyzerSettings> | null;
    this.settings = Object.assign({}, DEFAULT_SETTINGS, saved);
    this.resolveVaultDefaults(saved);
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }
}
