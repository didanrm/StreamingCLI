#!/usr/bin/env node
"use strict";

const path = require("path");
const readline = require("readline");
const { spawnSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const python = process.env.STREAMINGCLI_PYTHON || (process.platform === "win32" ? "python" : "python3");
const streamPy = path.join(root, "stream.py");
const color = process.stdout.isTTY;
const c = {
  reset: color ? "\x1b[0m" : "",
  cyan: color ? "\x1b[36m" : "",
  blue: color ? "\x1b[34m" : "",
  green: color ? "\x1b[32m" : "",
  yellow: color ? "\x1b[33m" : "",
  red: color ? "\x1b[31m" : "",
  dim: color ? "\x1b[2m" : "",
  bold: color ? "\x1b[1m" : "",
  pick: color ? "\x1b[30;46m" : "",
};

const menuItems = [
  {
    key: "1",
    title: "Start Streaming",
    description: "Paste link video, lalu buka langsung di VLC",
  },
  {
    key: "2",
    title: "List Providers",
    description: "Lihat sumber link yang saat ini didukung",
  },
  {
    key: "3",
    title: "Exit",
    description: "Keluar dari StreamingCLI",
  },
];

function runPython(args) {
  const result = spawnSync(python, [streamPy, ...args], { stdio: "inherit" });
  if (result.error) {
    console.error(`streamingcli: gagal menjalankan ${python}: ${result.error.message}`);
    return 1;
  }
  return result.status ?? 1;
}

function ask(rl, question) {
  return new Promise((resolve) => rl.question(question, resolve));
}

function clear() {
  if (process.stdout.isTTY) process.stdout.write("\x1b[2J\x1b[H");
}

function terminalWidth() {
  return Math.max(48, Math.min(process.stdout.columns || 78, 90));
}

function stripAnsi(value) {
  return value.replace(/\x1b\[[0-9;]*m/g, "");
}

function visibleLength(value) {
  return stripAnsi(value).length;
}

function padRight(value, width) {
  const missing = Math.max(0, width - visibleLength(value));
  return `${value}${" ".repeat(missing)}`;
}

function center(value, width) {
  const missing = Math.max(0, width - visibleLength(value));
  const left = Math.floor(missing / 2);
  return `${" ".repeat(left)}${value}${" ".repeat(missing - left)}`;
}

function truncate(value, width) {
  if (width <= 0) return "";
  if (value.length <= width) return value;
  if (width <= 3) return value.slice(0, width);
  return `${value.slice(0, width - 3)}...`;
}

function line(width, left = "+", fill = "-", right = "+") {
  return `${left}${fill.repeat(width - 2)}${right}`;
}

function boxed(lines, width = terminalWidth()) {
  const inner = width - 4;
  console.log(`${c.blue}${line(width)}${c.reset}`);
  for (const item of lines) {
    console.log(`${c.blue}|${c.reset} ${padRight(item, inner)} ${c.blue}|${c.reset}`);
  }
  console.log(`${c.blue}${line(width)}${c.reset}`);
}

function banner() {
  const width = terminalWidth();
  const inner = width - 4;
  const titleLines =
    width >= 70
      ? [
          " ___ _                         _             ___ _    ___ ",
          "/ __| |_ _ _ ___ __ _ _ __  ___(_)_ _  __ _ / __| |  |_ _|",
          "\\__ \\  _| '_/ -_) _` | '  \\/ -_) | ' \\/ _` | (__| |__ | | ",
          "|___/\\__|_| \\___\\__,_|_|_|_\\___|_|_||_\\__, |\\___|____|___|",
          "                                      |___/                 ",
        ]
      : ["STREAMINGCLI"];
  boxed(
    [
      ...titleLines.map((item) => center(`${c.cyan}${c.bold}${item}${c.reset}`, inner)),
      center(`${c.dim}Link-to-VLC streamer with temporary cache${c.reset}`, inner),
    ],
    width,
  );
  console.log();
}

function statusLine(message, tone = "info") {
  if (!message) return "";
  const label = tone === "error" ? "ERROR" : tone === "success" ? "OK" : "INFO";
  const tint = tone === "error" ? c.red : tone === "success" ? c.green : c.yellow;
  return `${tint}${c.bold}${label}${c.reset} ${message}`;
}

function promptLabel(text) {
  return `${c.cyan}${c.bold}${text}${c.reset} `;
}

async function basicMenu() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    while (true) {
      banner();
      menuItems.forEach((item) => {
        console.log(`${c.bold}${item.key}. ${item.title}${c.reset}`);
        console.log(`   ${c.dim}${item.description}${c.reset}`);
      });

      const choice = (await ask(rl, `\n${promptLabel("Pilih menu:")}`)).trim();
      if (choice === "1") {
        const url = (await ask(rl, promptLabel("Masukkan URL:"))).trim();
        if (!url) {
          console.log(`\n${statusLine("URL kosong. Coba paste link video dulu.", "error")}\n`);
          continue;
        }
        rl.close();
        return runPython([url]);
      }
      if (choice === "2") {
        console.log();
        runPython(["--list-providers"]);
        console.log();
        continue;
      }
      if (choice === "3") return 0;
      console.log(`\n${statusLine("Pilihan tidak valid.", "error")}\n`);
    }
  } finally {
    rl.close();
  }
}

function render(selected, note = "") {
  clear();
  banner();

  const width = terminalWidth();
  const inner = width - 4;
  const menuWidth = Math.min(inner, 72);
  const side = Math.max(0, Math.floor((width - menuWidth) / 2));
  const indent = " ".repeat(side);

  console.log(`${indent}${c.dim}${line(menuWidth)}${c.reset}`);
  menuItems.forEach((item, index) => {
    const selectedRow = index === selected;
    const marker = selectedRow ? ">" : " ";
    const titleWidth = Math.max(12, Math.min(18, Math.floor(menuWidth * 0.3)));
    const plainTitle = padRight(truncate(item.title, titleWidth), titleWidth);
    const prefix = `${marker} ${item.key}. ${plainTitle} `;
    const descriptionWidth = menuWidth - 4 - visibleLength(prefix);
    const plainDescription = truncate(item.description, descriptionWidth);
    const title = selectedRow ? plainTitle : `${c.bold}${plainTitle}${c.reset}`;
    const description = selectedRow ? plainDescription : `${c.dim}${plainDescription}${c.reset}`;
    const row = `${marker} ${item.key}. ${title} ${description}`;
    const content = ` ${padRight(row, menuWidth - 4)} `;
    if (selectedRow) {
      console.log(`${indent}${c.cyan}|${c.reset}${c.pick}${content}${c.reset}${c.cyan}|${c.reset}`);
    } else {
      console.log(`${indent}${c.dim}|${c.reset}${content}${c.dim}|${c.reset}`);
    }
  });
  console.log(`${indent}${c.dim}${line(menuWidth)}${c.reset}`);

  const help = width < 70 ? "Arrows move   Enter select   Ctrl+C exit" : "Arrow keys: move   Enter: select   1-3: shortcut   Ctrl+C: exit";
  console.log(`\n${center(`${c.dim}${help}${c.reset}`, width)}`);
  if (note) console.log(`\n${center(statusLine(note.message || note, note.tone || "info"), width)}`);
}

function selectMenu(note) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) return basicMenu();

  let selected = 0;
  readline.emitKeypressEvents(process.stdin);
  process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdout.write("\x1b[?25l");
  render(selected, note);

  return new Promise((resolve) => {
    function done(value) {
      process.stdin.off("keypress", onKey);
      process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdout.write("\x1b[?25h");
      resolve(value);
    }

    function onKey(_char, key) {
      if (key.ctrl && key.name === "c") done(2);
      else if (key.name === "up") {
        selected = (selected + 2) % 3;
        render(selected, note);
      } else if (key.name === "down") {
        selected = (selected + 1) % 3;
        render(selected, note);
      } else if (key.name === "return") {
        done(selected);
      } else if (["1", "2", "3"].includes(key.sequence)) {
        done(Number(key.sequence) - 1);
      }
    }

    process.stdin.on("keypress", onKey);
  });
}

async function prettyMenu() {
  let note = "";
  while (true) {
    const choice = await selectMenu(note);
    note = "";

    if (choice === 0) {
      clear();
      banner();
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      console.log(`${c.bold}Start Streaming${c.reset}`);
      console.log(`${c.dim}Paste link dari provider yang didukung. VLC akan dibuka otomatis.${c.reset}\n`);
      const url = (await ask(rl, promptLabel("Masukkan URL:"))).trim();
      rl.close();
      if (!url) {
        note = { message: "URL kosong. Coba paste link video dulu.", tone: "error" };
        continue;
      }
      return runPython([url]);
    }

    if (choice === 1) {
      clear();
      banner();
      console.log(`${c.bold}Supported Providers${c.reset}\n`);
      runPython(["--list-providers"]);
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      await ask(rl, `\n${promptLabel("Tekan Enter untuk kembali...")}`);
      rl.close();
      continue;
    }

    return 0;
  }
}

(async () => {
  const args = process.argv.slice(2);
  process.exitCode = args.length ? runPython(args) : await (process.stdin.isTTY ? prettyMenu() : basicMenu());
})();
