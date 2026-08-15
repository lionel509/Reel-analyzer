"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.ts
var main_exports = {};
__export(main_exports, {
  default: () => ReelAnalyzerPlugin
});
module.exports = __toCommonJS(main_exports);
var import_node_child_process = require("node:child_process");
var import_node_os = require("node:os");
var import_obsidian = require("obsidian");
var PROJECT_HOME = `${(0, import_node_os.homedir)()}/Documents/Citadel/Active/Reel Analyzer MCP`;
var DEFAULT_SETTINGS = {
  apiKey: "",
  pythonPath: `${(0, import_node_os.homedir)()}/.venvs/reel-analyzer/bin/python`,
  projectPath: PROJECT_HOME,
  visionModel: "google/gemma-4-26b-a4b-it",
  transcriptionModel: "openai/whisper-large-v3",
  uniformFps: "3.0",
  maxFrames: "360",
  chunkSize: "120",
  cookiesFile: "",
  outputFolder: "Active/Reel Analyzer MCP/Analyses",
  insertIntoActiveNote: true
};
var Analysis = class {
  constructor(settings, projectPath) {
    this.settings = settings;
    this.projectPath = projectPath;
  }
  stdout = "";
  stderr = "";
  run(target, onProgress) {
    const env = {
      ...process.env,
      OPENROUTER_API_KEY: this.settings.apiKey,
      VISION_MODEL: this.settings.visionModel,
      TRANSCRIPTION_MODEL: this.settings.transcriptionModel,
      UNIFORM_FPS: this.settings.uniformFps,
      MAX_FRAMES: this.settings.maxFrames,
      VISION_CHUNK_SIZE: this.settings.chunkSize
    };
    if (this.settings.cookiesFile.trim()) {
      env.INSTAGRAM_COOKIES_FILE = this.settings.cookiesFile.trim();
    }
    return new Promise((resolve, reject) => {
      const child = (0, import_node_child_process.spawn)(
        this.settings.pythonPath,
        ["-m", "reel_analyzer.smoke", target, "-v"],
        { env, cwd: this.projectPath }
      );
      child.stdout.on("data", (chunk) => {
        this.stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk) => {
        const text = chunk.toString();
        this.stderr += text;
        for (const line of text.split("\n")) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (trimmed.includes("extracted") && trimmed.includes("frames")) {
            onProgress(trimmed.replace(/^INFO [^:]+: /, ""));
          } else if (trimmed.includes("audio/transcriptions")) {
            onProgress("transcribing audio\u2026");
          } else if (trimmed.includes("chat/completions")) {
            onProgress("reading the frames\u2026");
          } else if (trimmed.startsWith("failed:") || trimmed.startsWith("config error:")) {
            onProgress(trimmed);
          }
        }
      });
      child.on("error", (error) => {
        reject(
          new Error(
            `Could not run ${this.settings.pythonPath} \u2014 check the Python path in settings. (${error.message})`
          )
        );
      });
      child.on("close", (code) => {
        if (code === 0) {
          resolve({ output: this.stdout.trim(), code });
          return;
        }
        const reason = this.stderr.split("\n").map((l) => l.trim()).filter((l) => l.startsWith("failed:") || l.startsWith("config error:")).pop() ?? this.stderr.trim().split("\n").slice(-3).join(" ");
        reject(new Error(reason || `analysis exited with code ${code}`));
      });
    });
  }
};
var ReelPromptModal = class extends import_obsidian.Modal {
  constructor(app, plugin) {
    super(app);
    this.plugin = plugin;
  }
  value = "";
  statusEl;
  analyseButton;
  running = false;
  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("reel-analyzer-modal");
    contentEl.createEl("h3", { text: "Analyze a reel" });
    const input = contentEl.createEl("input", {
      cls: "reel-analyzer-input",
      attr: {
        type: "text",
        placeholder: "https://www.instagram.com/reel/\u2026 or a local video path"
      }
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
  async start() {
    if (!this.value) {
      this.statusEl.setText("Paste a link first.");
      return;
    }
    if (!this.plugin.settings.apiKey.trim()) {
      this.statusEl.setText("No OpenRouter API key \u2014 add one in Reel Analyzer settings.");
      return;
    }
    this.running = true;
    this.analyseButton.disabled = true;
    this.analyseButton.setText("Working\u2026");
    this.statusEl.setText("downloading\u2026");
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
  onClose() {
    this.contentEl.empty();
  }
};
var ReelAnalyzerSettingTab = class extends import_obsidian.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    new import_obsidian.Setting(containerEl).setName("Connection").setHeading();
    new import_obsidian.Setting(containerEl).setName("OpenRouter API key").setDesc("Stored in this plugin's data.json inside your vault. Never leaves this machine except in calls to OpenRouter.").addText((text) => {
      text.inputEl.type = "password";
      text.inputEl.style.width = "22em";
      text.setPlaceholder("sk-or-v1-\u2026").setValue(this.plugin.settings.apiKey).onChange(async (value) => {
        this.plugin.settings.apiKey = value.trim();
        await this.plugin.saveSettings();
      });
    });
    new import_obsidian.Setting(containerEl).setName("Python interpreter").setDesc("The venv that has reel_analyzer installed.").addText(
      (text) => text.setPlaceholder(DEFAULT_SETTINGS.pythonPath).setValue(this.plugin.settings.pythonPath).onChange(async (value) => {
        this.plugin.settings.pythonPath = value.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Project folder").setDesc(
      "Absolute path to the reel-analyzer code (the folder with pyproject.toml). It lives in Citadel even when this plugin runs from another vault."
    ).addText((text) => {
      text.inputEl.style.width = "22em";
      text.setPlaceholder(PROJECT_HOME).setValue(this.plugin.settings.projectPath).onChange(async (value) => {
        this.plugin.settings.projectPath = value.trim();
        await this.plugin.saveSettings();
      });
    });
    new import_obsidian.Setting(containerEl).setName("Check setup").setDesc("Confirm the interpreter, the package, and ffmpeg are all reachable.").addButton(
      (button) => button.setButtonText("Run check").onClick(async () => {
        button.setButtonText("Checking\u2026");
        const message = await this.plugin.checkSetup();
        new import_obsidian.Notice(message, 8e3);
        button.setButtonText("Run check");
      })
    );
    new import_obsidian.Setting(containerEl).setName("Models").setHeading();
    new import_obsidian.Setting(containerEl).setName("Vision model").setDesc("Reads the frames. Switch to google/gemma-4-31b-it if captions read poorly.").addText(
      (text) => text.setValue(this.plugin.settings.visionModel).onChange(async (value) => {
        this.plugin.settings.visionModel = value.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Transcription model").addText(
      (text) => text.setValue(this.plugin.settings.transcriptionModel).onChange(async (value) => {
        this.plugin.settings.transcriptionModel = value.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Frame sampling").setHeading();
    new import_obsidian.Setting(containerEl).setName("Frames per second").setDesc("How densely the clip is sampled. 3 is triple what a native-video model sees \u2014 raise it for very fast cuts.").addText(
      (text) => text.setValue(this.plugin.settings.uniformFps).onChange(async (value) => {
        this.plugin.settings.uniformFps = value.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Maximum frames").setDesc("Total cap across the whole clip. 360 covers two minutes at 3fps.").addText(
      (text) => text.setValue(this.plugin.settings.maxFrames).onChange(async (value) => {
        this.plugin.settings.maxFrames = value.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Frames per request").setDesc("Longer clips split across this many frames per call, run in parallel. 150 is the measured ceiling.").addText(
      (text) => text.setValue(this.plugin.settings.chunkSize).onChange(async (value) => {
        this.plugin.settings.chunkSize = value.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Access and output").setHeading();
    new import_obsidian.Setting(containerEl).setName("Instagram cookies file").setDesc("Netscape-format export, for private or rate-limited reels. Optional.").addText(
      (text) => text.setPlaceholder("/Users/\u2026/cookies.txt").setValue(this.plugin.settings.cookiesFile).onChange(async (value) => {
        this.plugin.settings.cookiesFile = value.trim();
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Insert into the open note").setDesc("When off, every analysis becomes a new note in the folder below.").addToggle(
      (toggle) => toggle.setValue(this.plugin.settings.insertIntoActiveNote).onChange(async (value) => {
        this.plugin.settings.insertIntoActiveNote = value;
        await this.plugin.saveSettings();
      })
    );
    new import_obsidian.Setting(containerEl).setName("Folder for new notes").addText(
      (text) => text.setPlaceholder(DEFAULT_SETTINGS.outputFolder).setValue(this.plugin.settings.outputFolder).onChange(async (value) => {
        this.plugin.settings.outputFolder = value.trim();
        await this.plugin.saveSettings();
      })
    );
  }
};
var ReelAnalyzerPlugin = class extends import_obsidian.Plugin {
  settings = { ...DEFAULT_SETTINGS };
  async onload() {
    await this.loadSettings();
    this.addRibbonIcon("clapperboard", "Analyze a reel", () => {
      new ReelPromptModal(this.app, this).open();
    });
    this.addCommand({
      id: "analyze-reel",
      name: "Analyze a reel from a link",
      callback: () => new ReelPromptModal(this.app, this).open()
    });
    this.addCommand({
      id: "analyze-reel-from-selection",
      name: "Analyze the selected link",
      editorCallback: (editor) => {
        const selection = editor.getSelection().trim();
        if (!selection) {
          new import_obsidian.Notice("Select a link first.");
          return;
        }
        void this.runInline(selection, editor);
      }
    });
    this.addSettingTab(new ReelAnalyzerSettingTab(this.app, this));
  }
  /** The folder holding pyproject.toml, used as the subprocess working directory. */
  projectPath() {
    return this.settings.projectPath || PROJECT_HOME;
  }
  /** Pick an output folder that exists in *this* vault.
   *
   *  The plugin runs from the umbrella vault (which contains Citadel/) as well
   *  as from Citadel itself, so the same relative path is not correct in both.
   *  Only applied on a fresh install — never overrides a saved choice.
   */
  resolveVaultDefaults(saved) {
    if (saved?.outputFolder) return;
    const nested = "Citadel/Active/Reel Analyzer MCP/Analyses";
    const direct = "Active/Reel Analyzer MCP/Analyses";
    this.settings.outputFolder = this.app.vault.getAbstractFileByPath("Citadel") ? nested : direct;
  }
  analyze(target, onProgress) {
    return new Analysis(this.settings, this.projectPath()).run(target, onProgress);
  }
  async runInline(target, editor) {
    const notice = new import_obsidian.Notice("Analyzing reel\u2026", 0);
    try {
      const result = await this.analyze(target, (line) => notice.setMessage(`Reel: ${line}`));
      editor.replaceSelection(`${target}

${this.asCallout(result.output)}
`);
      notice.hide();
      new import_obsidian.Notice("Analysis inserted.");
    } catch (error) {
      notice.hide();
      new import_obsidian.Notice(`Reel analysis failed: ${error instanceof Error ? error.message : error}`, 1e4);
    }
  }
  asCallout(output) {
    const body = output.split("\n").map((line) => `> ${line}`).join("\n");
    return `> [!abstract] Reel analysis
${body}`;
  }
  /** Put the finished analysis where the settings say it should go. */
  async deliver(target, result) {
    const view = this.app.workspace.getActiveViewOfType(import_obsidian.MarkdownView);
    if (this.settings.insertIntoActiveNote && view) {
      view.editor.replaceSelection(`${target}

${this.asCallout(result.output)}
`);
      new import_obsidian.Notice("Analysis inserted.");
      return;
    }
    const folder = (0, import_obsidian.normalizePath)(this.settings.outputFolder || DEFAULT_SETTINGS.outputFolder);
    if (!this.app.vault.getAbstractFileByPath(folder)) {
      await this.app.vault.createFolder(folder).catch(() => void 0);
    }
    const title = this.titleFor(result.output, target);
    const path = (0, import_obsidian.normalizePath)(`${folder}/${title}.md`);
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
      "Hub: [[Reel Analyzer MCP \u2014 Project Hub]]",
      ""
    ].join("\n");
    const existing = this.app.vault.getAbstractFileByPath(path);
    const file = existing instanceof import_obsidian.TFile ? (await this.app.vault.modify(existing, contents), existing) : await this.app.vault.create(path, contents);
    await this.app.workspace.getLeaf("tab").openFile(file);
    new import_obsidian.Notice(`Saved to ${path}`);
  }
  /** Build a filename-safe title from the clip's own title line. */
  titleFor(output, target) {
    const match = /^TITLE:\s*(.+)$/m.exec(output);
    const raw = (match?.[1] ?? target).trim();
    const cleaned = raw.replace(/https?:\/\//g, "").replace(/[\\/:*?"<>|#^[\]]/g, "-").replace(/\s+/g, " ").trim().slice(0, 80);
    return cleaned || "Reel analysis";
  }
  /** Verify the interpreter, the package, and ffmpeg before the user hits a failure mid-run. */
  async checkSetup() {
    const script = "import shutil, reel_analyzer, sys; print('python', sys.version.split()[0]); print('reel_analyzer', reel_analyzer.__version__); print('ffmpeg', 'yes' if shutil.which('ffmpeg') else 'MISSING'); print('ffprobe', 'yes' if shutil.which('ffprobe') else 'MISSING')";
    return new Promise((resolve) => {
      const child = (0, import_node_child_process.spawn)(this.settings.pythonPath, ["-c", script], {
        cwd: this.projectPath()
      });
      let out = "";
      let err = "";
      child.stdout.on("data", (c) => out += c.toString());
      child.stderr.on("data", (c) => err += c.toString());
      child.on(
        "error",
        (error) => resolve(`Cannot run ${this.settings.pythonPath}
${error.message}`)
      );
      child.on("close", (code) => {
        if (code !== 0) {
          resolve(`Setup check failed:
${err.trim().split("\n").slice(-4).join("\n")}`);
          return;
        }
        const key = this.settings.apiKey.trim() ? "API key set" : "API key MISSING";
        resolve(`${out.trim()}
${key}`);
      });
    });
  }
  async loadSettings() {
    const saved = await this.loadData();
    this.settings = Object.assign({}, DEFAULT_SETTINGS, saved);
    this.resolveVaultDefaults(saved);
  }
  async saveSettings() {
    await this.saveData(this.settings);
  }
};
